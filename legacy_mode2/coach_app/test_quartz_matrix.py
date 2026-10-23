"""All input posts are mocked. No real Quartz or Unity interaction."""
import json
import contextlib
import io
from pathlib import Path
import tempfile
import signal
import sys
import unittest
from unittest.mock import MagicMock, patch

from .quartz_matrix import (CASES, MatrixExperiment, TelemetryReception, evaluate,
                           inspect_events, summarize, precondition_snapshot, print_preconditions)
from .quartz_matrix import PreconditionChanged, EmergencyStop, MatrixSignal, stop_for_signal, main
from .quartz_matrix import validate_mouse_frame_schema, validate_log_schema
from .test_quartz_delivery import sample


class MatrixTests(unittest.TestCase):
    def frame_trial(self, inputs):
        before = {**sample(), 'sensitivity': 2.0}
        rows = []
        x = y = yaw = pitch = 0.
        for i, (dx, dy) in enumerate(inputs, 1):
            x += dx; y += dy
            yaw += 2*dx; pitch -= 2*dy
            rows.append({'frame': before['frame']+i, 'input_sequence': i,
                         'timestamp': f'2026-10-23T01:38:49.{i:03d}Z', 'realtime': i/60,
                         'mouse_x': dx, 'mouse_y': dy, 'raw_x': dx, 'raw_y': dy,
                         'consumed_x': dx, 'consumed_y': dy, 'look_processed': True,
                         'yaw': yaw, 'pitch': pitch, 'yaw_delta': 2*dx, 'pitch_delta': -2*dy,
                         'application_focused': True, 'cursor_locked': True})
        after = {**before, 'frame': before['frame']+len(inputs)+1, 'axis_nonzero_frames': len(inputs),
                 'axis_sum_x': x, 'axis_sum_y': y, 'raw_sum_x': x, 'raw_sum_y': y,
                 'yaw': yaw, 'pitch': pitch, 'mouse_frame_version': 1, 'mouse_frames': rows}
        return before, after

    def test_single_frame_evidence_matches_input_and_camera(self):
        before, after = self.frame_trial([(.05, 0)])
        r = evaluate(before, after, (2, 0))
        self.assertTrue(r['success'])
        self.assertTrue(r['mouse_frame_evidence']['consistent'])
        self.assertEqual(r['unity_axis_per_requested_unit'], [.025, None])

    def test_two_frames_have_correct_direction_but_remain_unverified(self):
        before, after = self.frame_trial([(.05, 0), (.05, 0)])
        r = evaluate(before, after, (2, 0))
        self.assertFalse(r['success'])
        self.assertTrue(r['direction_matches'])
        self.assertTrue(r['response_in_existing_bounds'])
        self.assertTrue(r['mouse_frame_evidence']['consistent'])
        self.assertFalse(r['frame_count_valid'])
        self.assertEqual(r['rejected_checks'], ['nonzero_frame_count_not_one'])
        self.assertEqual(r['multiframe_provenance'], 'unverified')

    def test_split_and_doubled_totals_are_distinct_not_accepted(self):
        results = [evaluate(*self.frame_trial(inputs), (2, 0))
                   for inputs in ([ (.025, 0), (.025, 0)], [(.05, 0), (.05, 0)])]
        self.assertAlmostEqual(results[0]['unity_received_mouse_x'], .05)
        self.assertAlmostEqual(results[1]['unity_received_mouse_x'], .10)
        self.assertTrue(all(r['direction_matches'] and not r['success'] for r in results))

    def test_wrong_direction_is_not_confused_with_frame_count(self):
        before, after = self.frame_trial([(-.05, 0)])
        r = evaluate(before, after, (2, 0))
        self.assertTrue(r['frame_count_valid'])
        self.assertFalse(r['direction_matches'])
        self.assertTrue(r['response_in_existing_bounds'])
        self.assertFalse(r['success'])

    def test_excessive_rotation_still_fails(self):
        before, after = self.frame_trial([(2, 0)])
        r = evaluate(before, after, (2, 0))
        self.assertTrue(r['direction_matches'])
        self.assertFalse(r['response_in_existing_bounds'])
        self.assertFalse(r['success'])

    def test_trace_detects_cancelled_unexpected_axis_and_reversal(self):
        for inputs in ([(.05, .05), (.05, -.05)], [(.10, 0), (-.05, 0)]):
            before, after = self.frame_trial(inputs)
            r = evaluate(before, after, (2, 0))
            self.assertTrue(r['direction_matches'])  # Aggregate alone hides contamination.
            self.assertFalse(r['mouse_frame_evidence']['per_frame_direction_matches'])
            self.assertFalse(r['success'])

    def test_incomplete_malformed_and_inconsistent_traces_fail(self):
        for change in ('missing', 'malformed', 'totals', 'rotation', 'focus', 'order', 'quiet_rotation'):
            before, after = self.frame_trial([(.05, 0), (.05, 0)])
            if change == 'missing': after['mouse_frames'].pop()
            if change == 'malformed': after['mouse_frames'][0]['mouse_x'] = float('nan')
            if change == 'totals': after['axis_sum_x'] += .1
            if change == 'rotation': after['mouse_frames'][0]['pitch_delta'] = 1.
            if change == 'focus': after['mouse_frames'][0]['application_focused'] = False
            if change == 'order': after['mouse_frames'][1]['realtime'] = 0.
            if change == 'quiet_rotation': after['yaw'] += .1
            r = evaluate(before, after, (2, 0))
            self.assertFalse(r['mouse_frame_evidence']['consistent'], change)
            self.assertFalse(r['success'])

    def test_legacy_telemetry_does_not_invent_frames(self):
        before, after = self.frame_trial([(.05, 0)])
        after.pop('mouse_frame_version')
        r = evaluate(before, after, (2, 0))
        self.assertTrue(r['success'])
        self.assertFalse(r['mouse_frame_evidence']['available'])
        self.assertFalse(r['independently_verified'])

    def test_normal_coach_stream_is_not_misdiagnosed_as_old_build(self):
        state = {**sample(), 'mouse_frame_version': 0, 'mouse_frames': []}
        decoded = TelemetryReception().decode(json.dumps(state).encode(), 9900, 1.)
        self.assertEqual(decoded, state)  # Receiver does not strip optional fields.
        schema = validate_mouse_frame_schema(decoded)
        self.assertFalse(schema['available'])
        self.assertEqual(schema['reason'], 'normal_coach_stream_no_frame_history_check_port_mapping')
        self.assertEqual(schema['issues'], ['mouse_frame_version_is_0_expected_1'])

    def test_frame_arrays_survive_wire_decode_including_large_history(self):
        _, state = self.frame_trial([(.05, 0)]*32)
        data = json.dumps(state).encode()
        self.assertGreater(len(data), 8192)
        decoded = TelemetryReception().decode(data, 9900, 1.)
        self.assertEqual(decoded, state)
        self.assertTrue(validate_mouse_frame_schema(decoded)['schema_valid'])

    def test_empty_diagnostic_array_is_valid_schema_but_not_missing_history(self):
        state = {**sample(), 'mouse_frame_version': 1, 'mouse_frames': []}
        self.assertTrue(validate_mouse_frame_schema(state)['schema_valid'])
        for value in (None, {}, '[]'):
            state['mouse_frames'] = value
            self.assertFalse(validate_mouse_frame_schema(state)['consistent'])
        for value in (True, '1', 2):
            state['mouse_frame_version'] = value
            self.assertFalse(validate_mouse_frame_schema(state)['available'])

    def test_log_schema_validation_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'schema.jsonl'
            original = json.dumps({'event': 'sample', 'state': {
                **sample(), 'mouse_frame_version': 0, 'mouse_frames': []}})+'\n'
            path.write_text(original)
            with patch.object(sys, 'argv', ['matrix', '--validate-telemetry-log', str(path)]), \
                 patch('coach_app.quartz_matrix.post_relative_pulse') as post, \
                 patch('coach_app.quartz_matrix.socket.socket') as socket_factory, \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                main()
            report = json.loads(output.getvalue())
            self.assertFalse(report['input_events_posted'])
            self.assertEqual(report['logs'][0]['sample_schema_counts'], {
                'normal_coach_stream_no_frame_history_check_port_mapping': 1})
            self.assertEqual(path.read_text(), original)
            post.assert_not_called()
            socket_factory.assert_not_called()

    def test_repeated_history_logs_each_input_frame_once(self):
        e = self.engine('horizontal-positive')
        before, after = self.frame_trial([(.05, 0), (.05, 0)])
        e.pending = {'before': before, 'record': {'test_id': 'trace'}, 'posted_at': 0., 'method': 'pid'}
        e.log_sample(.05, after)
        e.log_sample(.06, after)
        records = [c.args[0] for c in self.log.write.call_args_list if c.args[0]['event'] == 'unity_mouse_frame']
        self.assertEqual(len(records), 2)
        self.assertEqual([r['state']['input_sequence'] for r in records], [1, 2])

    def setUp(self):
        self.now = 0.
        self.backend = MagicMock(pid=9900)
        self.backend.emergency.return_value = False
        self.backend.focused.return_value = True
        self.backend.trusted.return_value = True
        self.backend.snapshot.side_effect = lambda: {
            'foreground_pid': 9900 if self.backend.focused() else 42,
            'accessibility_trusted': self.backend.trusted()}
        self.backend.validate_destination.return_value = {'matrix_case': 'horizontal-positive', 'matrix_method': 'pid'}
        self.log = MagicMock()

    def engine(self, case):
        return MatrixExperiment(self.backend, self.log, {}, case, clock=lambda: self.now)

    def tick(self, e, t, delta=(0, 0), keys=None):
        self.now = t
        s = sample()
        s.update(frame=10+int(t*100), yaw=delta[0]*.05, pitch=delta[1]*.05,
                 axis_sum_x=delta[0]*.025, axis_sum_y=-delta[1]*.025,
                 axis_nonzero_frames=int(any(delta)))
        return e.tick(s, t, keys or {})

    def ready(self, e, start=0.):
        for offset in (0., .2, .4):
            self.tick(e, start+offset)
        self.assertEqual(e.control_state, 'READY')

    def test_all_seven_cases_and_signs(self):
        for case, delta in CASES.items():
            self.setUp()
            e = self.engine(case)
            self.ready(e)
            self.backend.post.assert_not_called()
            self.tick(e, .45, keys={'zero' if case == 'zero' else 'pid': True})
            self.tick(e, .95, delta)
            self.tick(e, 1.45, delta)
            self.assertTrue(e.last_result['controlled_trial_passed'], case)
            self.assertEqual(e.last_result['matrix_case'], case)
            starts=[c.args[0] for c in self.log.write.call_args_list if c.args[0]['event']=='activated']
            self.assertEqual((starts[0]['requested_dx'], starts[0]['requested_dy']), delta)
            self.assertEqual(self.backend.post.call_count, int(any(delta)))

    def test_silent_failure_stays_failed_and_requires_new_key(self):
        e = self.engine('horizontal-positive')
        self.ready(e)
        self.tick(e, .45, keys={'pid': True})
        self.tick(e, .95, keys={'pid': True})
        self.assertTrue(self.tick(e, 1.45, keys={'pid': True}))
        self.assertFalse(e.last_result['controlled_trial_passed'])
        self.assertEqual(e.last_result['outcome'], 'no_unity_delta')
        self.tick(e, 3, keys={'pid': True})
        self.assertEqual(self.backend.post.call_count, 1)

    def test_zero_control_in_other_case_is_not_counted_as_pulse(self):
        e = self.engine('horizontal-positive')
        self.ready(e)
        self.tick(e, .45, keys={'zero': True})
        self.tick(e, .95)
        self.tick(e, 1.45)
        self.assertEqual(e.last_result['matrix_case'], 'zero')
        self.backend.post.assert_not_called()

    def test_no_lowered_threshold_or_wrong_axis_acceptance(self):
        for yaw,pitch,dx,dy in ((.004,0,.05,0),(-.1,0,-.05,0),(.1,.1,.05,-.05)):
            before=sample(); after=sample()
            after.update(frame=20,yaw=yaw,pitch=pitch,axis_sum_x=dx,axis_sum_y=dy,axis_nonzero_frames=1)
            self.assertFalse(evaluate(before,after,(2,0))['success'])

    def test_stop_and_focus_loss(self):
        e = self.engine('diagonal-positive')
        self.tick(e, 0)
        self.backend.focused.return_value = False
        self.assertTrue(self.tick(e, .35, keys={'pid': True}))
        self.assertEqual(e.control_state, 'WAITING_FOR_GAME')
        self.backend.post.assert_not_called()
        self.setUp(); e=self.engine('diagonal-positive')
        self.backend.emergency.return_value=True
        self.assertFalse(self.tick(e, 0, keys={'pid':True}))
        self.backend.post.assert_not_called()

    def test_read_only_probe_never_posts_or_changes_timestamp(self):
        q=MagicMock()
        q.CGEventGetTimestamp.return_value=0
        rows=inspect_events(q)
        self.assertEqual(len(rows),7)
        self.assertTrue(all(r['timestamp_on_creation']==0 for r in rows))
        q.CGEventPostToPid.assert_not_called()
        q.CGEventPost.assert_not_called()
        q.CGEventSetTimestamp.assert_not_called()
        q.CGWarpMouseCursorPosition.assert_not_called()

    def test_summary_keeps_failed_trials_and_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'test.jsonl'
            row={'event':'result','matrix_case':'horizontal-positive','matrix_method':'pid',
                 'controlled_trial_passed':False,'outcome':'no_unity_delta','event_timestamp_ns':0,
                 'unity_received_mouse_x':0,'unity_received_mouse_y':0,
                 'camera_yaw_change':0,'camera_pitch_change':0}
            p.write_text(json.dumps(row)+'\n')
            result=summarize([p])['groups'][0]
            self.assertEqual(result['silent_failures'],1)
            self.assertEqual(result['controlled_passes'],0)
            self.assertEqual(result['event_timestamps_ns'],[0])

    def test_missing_stale_focus_and_permission_failures_are_distinct(self):
        for failure in ('missing', 'stale', 'focus', 'permission'):
            self.setUp()
            e = self.engine('horizontal-positive')
            if failure == 'focus':
                self.backend.focused.return_value = False
            if failure == 'permission':
                self.backend.trusted.return_value = False
            self.now = 1.
            e.tick(None if failure == 'missing' else sample(),
                   0 if failure == 'stale' else 1., {'pid': True})
            expected = {'missing': 'unity_telemetry_not_received', 'stale': 'unity_telemetry_stale',
                        'focus': 'foreground_pid_mismatch', 'permission': 'accessibility_permission_denied'}[failure]
            self.assertIn(expected, e.last_preconditions['rejected_preconditions'])
            self.assertEqual(e.last_preconditions['selected_game_pid'], 9900)
            self.assertEqual(e.last_preconditions['udp_diagnostic_port'], 8767)
            self.backend.post.assert_not_called()

    def test_legacy_fields_unknown_not_guessed(self):
        snapshot = precondition_snapshot(self.backend, sample(), .95, 1.)
        self.assertEqual(snapshot['rejected_preconditions'], [])
        self.assertIsNone(snapshot['paused'])
        self.assertIsNone(snapshot['cursor_locked'])
        self.assertIsNone(snapshot['session_active'])
        self.assertAlmostEqual(snapshot['last_telemetry_age_ms'], 50.)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            print_preconditions(snapshot)
        self.assertIn('Cursor locked: unknown (not published by Unity)', out.getvalue())

    def test_explicit_failed_unity_flag_blocks_even_if_aggregate_true(self):
        for field, value, reason in (('paused', True, 'session_paused'),
                                     ('cursor_locked', False, 'cursor_locked_false'),
                                     ('session_active', False, 'session_active_false')):
            self.setUp()
            e = self.engine('horizontal-positive')
            s = {**sample(), field: value}
            e.tick(s, 0., {'pid': True})
            self.assertIn(reason, e.last_preconditions['rejected_preconditions'])
            self.backend.post.assert_not_called()

    def test_rejected_key_is_consumed_and_cannot_fire_on_recovery(self):
        e = self.engine('horizontal-positive')
        e.tick(None, 0., {'pid': True})
        self.tick(e, .1, keys={'pid': True})
        self.tick(e, .5, keys={'pid': True})
        self.backend.post.assert_not_called()

    def test_wrong_pid_and_malformed_packets_reported(self):
        tracker = TelemetryReception()
        self.assertIsNone(tracker.decode(json.dumps({**sample(), 'pid': 123}).encode(), 9900, .9))
        snapshot = precondition_snapshot(self.backend, None, 0, 1., reception=tracker)
        self.assertEqual(snapshot['last_udp_packet_pid'], 123)
        self.assertTrue(any('telemetry_pid_mismatch' in r for r in snapshot['rejected_preconditions']))
        self.assertIsNone(tracker.decode(b'not-json', 9900, 1.))
        self.assertEqual(tracker.last_packet_rejection, 'malformed_json')
        self.assertIsNotNone(tracker.decode(json.dumps(sample()).encode(), 9900, 1.1))
        self.assertIsNone(tracker.last_packet_rejection)

    def test_initial_key_press_is_rejected_until_stable(self):
        e = self.engine('horizontal-positive')
        self.tick(e, 0., keys={'pid': True})
        records = [c.args[0] for c in self.log.write.call_args_list]
        self.assertTrue(any(r['event'] == 'hotkey_rejected' and r['reason'] == 'game_state_not_yet_stable'
                            for r in records))
        self.backend.post.assert_not_called()

    def test_ready_focus_loss_recovers_without_delayed_key(self):
        e = self.engine('horizontal-positive')
        self.ready(e)
        self.backend.focused.return_value = False
        self.assertTrue(self.tick(e, .5, keys={'pid': True}))
        self.assertEqual(e.control_state, 'WAITING_FOR_GAME')
        self.backend.focused.return_value = True
        for t in (.6, .8, 1., 1.1):
            self.assertTrue(self.tick(e, t, keys={'pid': True}))
        self.assertEqual(e.control_state, 'READY')
        self.backend.post.assert_not_called()
        self.tick(e, 1.2)
        self.tick(e, 1.3, keys={'pid': True})
        self.backend.post.assert_called_once()

    def test_foreground_matches_before_unity_focus_catches_up(self):
        e = self.engine('horizontal-positive')
        for t in (0., .1, .4):
            self.now = t
            s = {**sample(), 'gameplay': False, 'application_focused': False}
            self.assertTrue(e.tick(s, t, {'zero': True}))
        self.backend.post.assert_not_called()
        self.assertEqual(e.control_state, 'WAITING_FOR_GAME')
        self.ready(e, start=.5)
        self.tick(e, 1., keys={'zero': True})
        self.assertIsNotNone(e.pending)

    def test_single_valid_sample_cannot_arm_and_flapping_resets_timer(self):
        e = self.engine('horizontal-positive')
        self.tick(e, 0.)
        self.tick(e, .2, keys={'pid': True})
        self.backend.focused.return_value = False
        self.tick(e, .3)
        self.backend.focused.return_value = True
        self.tick(e, .4)
        self.tick(e, .6, keys={'pid': True})
        self.assertEqual(e.control_state, 'WAITING_FOR_GAME')
        self.backend.post.assert_not_called()

    def test_duplicate_frames_do_not_satisfy_stability(self):
        e = self.engine('horizontal-positive')
        for t in (0., .2, .4, .6):
            self.now = t
            e.tick(sample(), t, {'pid': True})
        self.assertEqual(e.control_state, 'WAITING_FOR_GAME')
        self.backend.post.assert_not_called()

    def test_focus_loss_during_pulse_cancels_without_retry(self):
        e = self.engine('horizontal-positive')
        self.ready(e)
        self.tick(e, .45, keys={'pid': True})
        self.backend.focused.return_value = False
        self.assertTrue(self.tick(e, .5, keys={'pid': True}))
        self.assertIsNone(e.pending)
        self.assertEqual(e.control_state, 'WAITING_FOR_GAME')
        self.assertEqual(self.backend.post.call_count, 1)

    def test_native_gate_race_returns_to_waiting(self):
        e = self.engine('horizontal-positive')
        self.ready(e)
        self.backend.post.side_effect = PreconditionChanged('focus changed before post')
        self.assertTrue(self.tick(e, .45, keys={'pid': True}))
        self.assertEqual(e.control_state, 'WAITING_FOR_GAME')
        self.assertIsNone(e.pending)

    def test_emergency_at_native_gate_stops_instead_of_waiting(self):
        e = self.engine('horizontal-positive')
        self.ready(e)
        self.backend.post.side_effect = EmergencyStop('hotkey_F8')
        self.assertFalse(self.tick(e, .45, keys={'pid': True}))
        self.assertEqual(e.stop_reason, 'hotkey_F8')

    def test_emergency_at_shared_gate_is_latched(self):
        e = self.engine('horizontal-positive')
        self.ready(e)
        self.backend.emergency.side_effect = [False, True, False]
        self.assertFalse(self.tick(e, .45, keys={'pid': True}))
        self.assertEqual(e.stop_reason, 'emergency_stop_native')
        self.backend.post.assert_not_called()

    def test_f8_and_escape_log_exact_emergency_source(self):
        for key in ('F8', 'ESC'):
            self.setUp()
            e = self.engine('horizontal-positive')
            self.assertFalse(e.tick(None, 0., {}, hotkeys={key: True}))
            self.assertEqual(e.stop_reason, 'hotkey_'+key)
            self.backend.post.assert_not_called()
            self.assertTrue(any(c.args[0]['event'] == 'hotkey' and c.args[0]['key'] == key
                                for c in self.log.write.call_args_list))

    def test_signal_handler_identifies_signal_without_sending_os_signal(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            with self.assertRaises(MatrixSignal) as caught:
                stop_for_signal(sig, None)
            self.assertEqual(caught.exception.signum, sig)

    def test_precise_publisher_blockers_and_menu_states_are_preserved(self):
        s = {**sample(), 'gameplay': False, 'precondition_version': 2,
             'application_focused': True, 'cursor_locked': False, 'cursor_lock_mode': 'None',
             'cursor_manager_present': True, 'session_present': True, 'session_active': True,
             'paused': True, 'gameplay_input_enabled': False,
             'settings_manager_present': True, 'settings_open': True, 'settings_panel_visible': True,
             'ui_manager_present': True, 'start_menu_visible': False,
             'summary_open': False, 'summary_panel_visible': False,
             'gameplay_blockers': ['cursor_not_locked', 'gameplay_input_disabled', 'session_paused'],
             'sent_at_utc': '2026-10-22T23:50:00.000Z', 'time_scale': 0.}
        report = precondition_snapshot(self.backend, s, 1., 1.)
        self.assertEqual(report['unity_gameplay_blockers'], s['gameplay_blockers'])
        self.assertTrue(report['settings_panel_visible'])
        self.assertFalse(report['summary_panel_visible'])
        self.assertEqual(report['unity_sent_at_utc'], s['sent_at_utc'])
        self.assertIn('session_paused', report['rejected_preconditions'])
        self.assertIn('settings_panel_visible', report['rejected_preconditions'])

    def test_missing_managers_do_not_report_nonexistent_panels_closed(self):
        s = {**sample(), 'gameplay': False, 'session_present': False,
             'ui_manager_present': False, 'settings_manager_present': False,
             'paused': False, 'summary_open': False, 'start_menu_visible': False,
             'summary_panel_visible': False, 'settings_panel_visible': False}
        report = precondition_snapshot(self.backend, s, 1., 1.)
        for key in ('paused', 'summary_open', 'start_menu_visible', 'summary_panel_visible', 'settings_panel_visible'):
            self.assertIsNone(report[key])
        self.assertIn('session_manager_missing', report['rejected_preconditions'])

    def test_old_gameplay_false_does_not_invent_blocker(self):
        report = precondition_snapshot(self.backend, {**sample(), 'gameplay': False}, 1., 1.)
        self.assertIsNone(report['unity_gameplay_blockers'])
        self.assertEqual(report['rejected_preconditions'], ['gameplay_inactive'])


class ShutdownTests(unittest.TestCase):
    def check_shutdown(self, failure, expected):
        q = MagicMock()
        q.CGEventSourceKeyState.return_value = False
        receiver = MagicMock()
        receiver.recvfrom.side_effect = BlockingIOError
        log = MagicMock()
        experiment = MagicMock(control_state='WAITING_FOR_GAME', stop_reason='hotkey_F8',
                               last_preconditions={}, previous_hotkeys={})
        if failure is None:
            experiment.tick.return_value = False
        else:
            experiment.tick.side_effect = failure
        with patch.dict(sys.modules, {'Quartz': q}), \
             patch.object(sys, 'argv', ['matrix', '--window-id', '123', '--case', 'horizontal-positive']), \
             patch('coach_app.quartz_matrix.accessibility_trusted', return_value=True), \
             patch('coach_app.quartz_matrix.resolve_destination', return_value={
                 'resolved_owner_pid': 9900, 'game_executable': '/game/Test.app/Contents/MacOS/Game'}), \
             patch('coach_app.quartz_matrix.ForegroundQuery') as foreground, \
             patch('coach_app.quartz_matrix.socket.socket', return_value=receiver), \
             patch('coach_app.quartz_matrix.CorrectionLog', return_value=log), \
             patch('coach_app.quartz_matrix.MatrixExperiment', return_value=experiment), \
             patch('coach_app.quartz_matrix.signal.signal'):
            foreground.return_value.snapshot.return_value = {'foreground_pid': 9900}
            if isinstance(failure, Exception):
                with self.assertRaises(type(failure)):
                    main()
            else:
                main()
        shutdown = [c.args[0] for c in log.write.call_args_list if c.args[0]['event'] == 'matrix_shutdown']
        self.assertEqual(len(shutdown), 1)
        self.assertEqual(shutdown[0]['reason'], expected)
        receiver.close.assert_called_once()
        log.close.assert_called_once()
        q.CGEventPostToPid.assert_not_called()
        q.CGEventPost.assert_not_called()
        return shutdown[0]

    def test_shutdown_records_emergency_reason(self):
        self.check_shutdown(None, 'hotkey_F8')

    def test_shutdown_records_keyboard_interrupt(self):
        self.check_shutdown(KeyboardInterrupt(), 'keyboard_interrupt')

    def test_shutdown_records_signals(self):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            row = self.check_shutdown(MatrixSignal(sig), 'signal_'+signal.Signals(sig).name)
            self.assertEqual(row['signal_number'], sig)

    def test_shutdown_records_exception_and_traceback(self):
        row = self.check_shutdown(RuntimeError('test failure'), 'exception')
        self.assertEqual(row['exception_type'], 'RuntimeError')
        self.assertIn('test failure', row['traceback'])


if __name__=='__main__':
    unittest.main()
