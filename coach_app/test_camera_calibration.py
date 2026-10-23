"""Mocked events only. No native posting or app activation in these tests."""
import copy
import json
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from coach_app.camera_calibration import (CalibrationExperiment, CalibrationBackend, CameraCalibration,
    PLAN, EXPECTED_APP, calibration_report, measurement, format_calibration_report)
from coach_app.quartz_matrix import evaluate, PreconditionChanged, EmergencyStop, TelemetryReception
from coach_app.test_quartz_delivery import sample


def state():
    return {**sample(), 'sensitivity': 2., 'fov': 60., 'aspect': 1.5,
            'mouse_frame_version': 1, 'mouse_frames': [], 'application_focused': True,
            'cursor_locked': True, 'session_active': True, 'paused': False,
            'gameplay_input_enabled': True, 'settings_open': False, 'summary_open': False,
            'settings_panel_visible': False, 'summary_panel_visible': False, 'start_menu_visible': False}


def advance(before, delta=(0, 0), gain=.05, realtime=1.):
    s = copy.deepcopy(before)
    s['frame'] += 1
    dx, dy = delta
    if any(delta):
        x, y = dx*gain/2, -dy*gain/2
        s['axis_sum_x'] += x; s['axis_sum_y'] += y
        s['raw_sum_x'] += x; s['raw_sum_y'] += y
        s['axis_nonzero_frames'] += 1
        s['yaw'] += dx*gain; s['pitch'] += dy*gain
        s['mouse_frames'].append({'frame': s['frame'], 'input_sequence': s['axis_nonzero_frames'],
            'timestamp': '2026-10-23T02:45:00Z', 'realtime': realtime,
            'mouse_x': x, 'mouse_y': y, 'raw_x': x, 'raw_y': y,
            'consumed_x': x, 'consumed_y': y, 'look_processed': True,
            'yaw': s['yaw'], 'pitch': s['pitch'], 'yaw_delta': dx*gain, 'pitch_delta': dy*gain,
            'application_focused': True, 'cursor_locked': True})
    return s


class MeasurementTests(unittest.TestCase):
    def test_independent_count_magnitude_and_timing_for_single_and_split_frames(self):
        before = state()
        single = measurement(before, advance(before, (2, 0)), 2, 0, expected_gain=.05)
        self.assertTrue(single['valid'])
        self.assertTrue(single['total_magnitude']['valid'])
        # Hypothetical correctly summed split: valid magnitude, NOT evidence to
        # authorize two frames. No such split was found in the recent real logs.
        split = advance(advance(before, (2, 0), gain=.025, realtime=1.),
                        (2, 0), gain=.025, realtime=1.017)
        r = measurement(before, split, 2, 0, expected_gain=.05)
        self.assertTrue(r['mouse_frame_evidence']['consistent'])
        self.assertTrue(r['direction_matches'])
        self.assertTrue(r['total_magnitude']['valid'])
        self.assertFalse(r['frame_count_valid'])
        self.assertFalse(r['valid'])
        self.assertEqual(r['rejected_checks'], ['nonzero_frame_count_not_one'])
        self.assertAlmostEqual(r['input_timing']['span_ms'], 17.)
        self.assertEqual(r['input_timing']['frame_gaps'], [1])

    def test_doubled_response_reports_excess_even_when_count_already_fails(self):
        before = state()
        doubled = advance(advance(before, (2, 0), realtime=1.), (2, 0), realtime=1.017)
        r = measurement(before, doubled, 2, 0, expected_gain=.05)
        self.assertTrue(r['mouse_frame_evidence']['consistent'])
        self.assertTrue(r['direction_matches'])
        self.assertFalse(r['total_magnitude']['valid'])
        self.assertFalse(r['valid'])
        self.assertIn('nonzero_frame_count_not_one', r['rejected_checks'])
        self.assertIn('total_response_magnitude_outside_20_percent', r['rejected_checks'])
        a = r['total_magnitude']['axes'][0]
        self.assertAlmostEqual(a['rotation_relative_error'], 1.)
        self.assertAlmostEqual(a['input_relative_error'], 1.)

    def test_contamination_wrong_axis_missing_history_and_excess_stay_rejected(self):
        before = state()
        contaminated = advance(advance(before, (2, 0), realtime=1.), (-2, 0), realtime=1.017)
        wrong_axis = advance(before, (2, 2))
        missing = advance(before, (2, 0)); missing['mouse_frames'] = []
        excessive = advance(before, (2, 0), gain=.1)
        for after in (contaminated, wrong_axis, missing, excessive):
            with self.subTest(after=after):
                self.assertFalse(measurement(before, after, 2, 0, expected_gain=.05)['valid'])

    def test_all_directions_match_matrix_verdict_and_frames(self):
        for delta in PLAN:
            before = state(); after = advance(before, delta)
            r = measurement(before, after, *delta)
            self.assertTrue(r['valid'])
            self.assertEqual(r['direction_matches'], evaluate(before, after, delta)['direction_matches'])
            if any(delta): self.assertAlmostEqual(r['degrees_per_delta'], .05)

    def test_no_response_wrong_direction_missing_or_two_frame_history_rejected(self):
        before = state()
        for after in (advance(before), advance(before, (-2, 0)),
                      advance(advance(before, (2, 0)), (2, 0), realtime=2.)):
            self.assertFalse(measurement(before, after, 2, 0)['valid'])
        after = advance(before, (2, 0)); after.pop('mouse_frame_version')
        self.assertFalse(measurement(before, after, 2, 0)['valid'])

    def test_report_needs_controlled_both_signs_and_all_trials(self):
        trials = [{**measurement(state(), advance(state(), d), *d), 'controlled_trial_passed': True} for d in PLAN]
        self.assertTrue(calibration_report(trials, True)['reliable'])
        trials[-1]['controlled_trial_passed'] = False
        self.assertFalse(calibration_report(trials, True)['reliable'])
        self.assertFalse(calibration_report(trials[:5], True)['reliable'])
        text = format_calibration_report(calibration_report(trials))
        for label in ('Horizontal:', 'Vertical:', 'Reliability:', 'Reason:', 'Head Lock disabled'):
            self.assertIn(label, text)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.
        self.backend = Mock(spec_set=['pid', 'trusted', 'snapshot', 'validate_destination', 'focused', 'emergency', 'post'])
        self.backend.pid = 9900
        self.backend.trusted.return_value = True
        self.backend.focused.return_value = True
        self.backend.emergency.return_value = False
        self.backend.snapshot.side_effect = lambda: {'foreground_pid': 9900 if self.backend.focused() else 99,
                                                     'accessibility_trusted': self.backend.trusted()}
        self.backend.validate_destination.return_value = {'resolved_owner_pid': 9900}
        self.log = Mock()
        self.e = CalibrationExperiment(self.backend, self.log, clock=lambda: self.now)
        self.s = state()

    def tick(self, t, key=False, delta=(0, 0), stop=False, changes=None, gain=.05, received=None):
        self.now = t
        self.s = advance(self.s, delta, gain, t)
        if changes: self.s.update(changes)
        self.e.tick(self.s, t if received is None else received, key, stop)

    def ready(self, start=0.):
        for offset in (0., .2, .4): self.tick(start+offset)
        self.assertEqual(self.e.control_state, 'READY')

    def trial(self, start, delta):
        self.ready(start)
        self.tick(start+.45, key=True)
        self.assertIsNotNone(self.e.pending)
        self.tick(start+.95, delta=delta)
        self.tick(start+1.45)

    def test_authorized_zero_first_trial_and_no_automatic_pulse(self):
        self.trial(0., (0, 0))
        self.assertEqual(len(self.e.trials), 1)
        self.assertTrue(self.e.trials[0]['valid'])
        self.backend.post.assert_not_called()
        self.assertEqual(self.e.case, 'horizontal-positive')

    def test_complete_plan_factors_and_head_lock_remains_disabled(self):
        for i, delta in enumerate(PLAN): self.trial(i*2.5, delta)
        self.assertTrue(self.e.report['reliable'])
        self.assertEqual(self.backend.post.call_count, 12)
        self.assertTrue(all(c.args == ('pid',) for c in self.backend.post.call_args_list))
        for axis in self.e.report['axes'].values():
            self.assertEqual(axis['positive_trials'], 3)
            self.assertEqual(axis['negative_trials'], 3)
            self.assertAlmostEqual(axis['degrees_per_delta'], .05)
        self.assertFalse(self.e.report['head_lock_enabled'])

    def test_permission_denied_or_revoked_stops_before_post(self):
        self.backend.trusted.return_value = False
        self.tick(0., key=True)
        self.assertEqual(self.e.report['abort_reason'], 'accessibility_permission_denied')
        self.backend.post.assert_not_called()

    def test_focus_transition_waits_and_never_queues_held_key(self):
        self.ready()
        self.backend.focused.return_value = False
        self.tick(.5, key=True)
        self.assertFalse(self.e.done)
        self.assertEqual(self.e.control_state, 'WAITING_FOR_GAME')
        self.backend.focused.return_value = True
        for t in (.6, .8, 1., 1.1): self.tick(t, key=True)
        self.assertIsNone(self.e.pending)
        self.tick(1.2)
        self.tick(1.3, key=True)
        self.assertIsNotNone(self.e.pending)

    def test_menus_stale_schema_or_telemetry_never_post(self):
        for changes in ({'settings_open': True}, {'summary_open': True}, {'paused': True},
                        {'cursor_locked': False}, {'mouse_frame_version': 0}):
            self.setUp(); self.tick(0., key=True, changes=changes)
            self.assertIsNone(self.e.pending)
            self.backend.post.assert_not_called()
        self.setUp(); self.tick(1., key=True, received=0.)
        self.backend.post.assert_not_called()

    def test_missing_individual_safety_flags_are_not_guessed(self):
        self.s.pop('cursor_locked')
        self.tick(0., key=True)
        self.assertIn('calibration_requires_explicit_cursor_locked',
                      self.e.last_preconditions['rejected_preconditions'])
        self.backend.post.assert_not_called()

    def test_focus_loss_mid_trial_cancels_and_waits(self):
        self.ready(); self.tick(.45, key=True)
        self.backend.focused.return_value = False
        self.tick(.5)
        self.assertIsNone(self.e.pending)
        self.assertFalse(self.e.done)
        self.assertEqual(len(self.e.trials), 0)

    def test_stop_and_f8_abort(self):
        self.ready(); self.tick(.45, key=True); self.tick(.5, stop=True)
        self.assertTrue(self.e.done)
        self.assertFalse(self.e.report['reliable'])
        self.backend.post.assert_not_called()

    def test_sensitivity_change_or_excess_rotation_still_aborts(self):
        self.ready(); self.tick(.45, key=True); self.tick(.5, changes={'yaw': 4.})
        self.assertEqual(self.e.report['abort_reason'], 'camera_limit_or_unity_counter_reset')
        self.setUp(); self.ready(); self.tick(.5, changes={'sensitivity': 3.})
        self.assertEqual(self.e.report['abort_reason'], 'camera_settings_changed')

    def test_invalid_pulse_has_precise_failure_and_no_factor(self):
        self.trial(0., (0, 0))
        self.trial(2.5, (0, 0))
        self.assertIn('nonzero_frame_count_not_one', self.e.report['abort_reason'])
        self.assertIsNone(self.e.report['axes']['horizontal']['degrees_per_delta'])

    def test_gain_consistency_and_noisy_post_window_rejected(self):
        self.trial(0., (0, 0)); self.trial(2.5, (2, 0))
        self.ready(5.); self.tick(5.45, key=True)
        self.tick(5.95, delta=(-2, 0), gain=.1); self.tick(6.45)
        self.assertIn('calibration_gain_inconsistent', self.e.report['abort_reason'])
        self.setUp(); self.ready(); self.tick(.45, key=True)
        self.tick(.95); self.tick(1.45, delta=(2, 0))
        self.assertIn('post_window_not_quiet', self.e.report['abort_reason'])

    def test_two_full_responses_report_both_count_and_magnitude_failure(self):
        self.trial(0., (0, 0)); self.trial(2.5, (2, 0))
        self.ready(5.); self.tick(5.45, key=True)
        self.tick(5.6, delta=(-2, 0)); self.tick(5.617, delta=(-2, 0))
        self.tick(5.95); self.tick(6.45)
        reason = self.e.report['abort_reason']
        self.assertIn('nonzero_frame_count_not_one', reason)
        self.assertIn('total_response_magnitude_outside_20_percent', reason)
        self.assertIn('calibration_gain_inconsistent_over_20_percent', reason)
        self.assertTrue(self.e.trials[-1]['mouse_frame_evidence']['consistent'])
        self.assertFalse(self.e.report['head_lock_enabled'])


class NativeBackendTests(unittest.TestCase):
    def setUp(self):
        self.b = object.__new__(CalibrationBackend)
        self.b.pid, self.b.window_id = 9900, 456
        self.b.q, self.b.log = Mock(), Mock()
        self.now = 10.
        experiment = SimpleNamespace(latest_input=(state(), self.now), delta=(2, 0), reception=None)
        self.b.controller = SimpleNamespace(post_lock=threading.RLock(), stop_event=threading.Event(),
            experiment=experiment, foreground_snapshot={'foreground_pid': 9900, 'foreground_checked_monotonic': self.now})
        self.b.validate_destination = Mock(return_value={'resolved_owner_pid': 9900})
        self.b.emergency = Mock(return_value=False)

    def test_real_ax_interface_and_shared_pid_pulse_helper(self):
        with patch('coach_app.camera_calibration.time.perf_counter', return_value=self.now), \
             patch('coach_app.camera_calibration.accessibility_trusted', return_value=True) as trust, \
             patch('coach_app.camera_calibration.post_relative_pulse', return_value={}) as post:
            self.b.post('pid')
            post.assert_called_once_with(self.b.q, 'pid', 9900, 2, 0)
            self.assertTrue(trust.called)

    def test_stale_foreground_menu_permission_and_stop_never_post(self):
        for reason in ('focus', 'stale_focus', 'menu', 'permission', 'stop'):
            self.setUp()
            if reason == 'focus': self.b.controller.foreground_snapshot['foreground_pid'] = 42
            if reason == 'stale_focus': self.b.controller.foreground_snapshot['foreground_checked_monotonic'] = 0.
            if reason == 'menu': self.b.controller.experiment.latest_input[0]['settings_open'] = True
            if reason == 'stop': self.b.controller.stop_event.set()
            with patch('coach_app.camera_calibration.time.perf_counter', return_value=self.now), \
                 patch('coach_app.camera_calibration.accessibility_trusted', return_value=reason != 'permission'), \
                 patch('coach_app.camera_calibration.post_relative_pulse') as post:
                with self.assertRaises((PreconditionChanged, EmergencyStop)): self.b.post('pid')
                post.assert_not_called()

    def test_tk_main_thread_supplies_corrected_foreground_query(self):
        c = CameraCalibration()
        with patch('coach_app.camera_calibration.ForegroundQuery') as query:
            query.return_value.snapshot.return_value = {'foreground_pid': 9900}
            c.refresh_foreground()
            self.assertEqual(c.foreground_snapshot['foreground_pid'], 9900)
            query.return_value.snapshot.assert_called_once()


class RealLogReplayTests(unittest.TestCase):
    def test_recent_two_frame_failures_are_double_responses_not_splits(self):
        names = ('f3ca6ca84be6498e8a767d8e6c23c00f', 'b5b273e341d84ff28678aaed18eabda7',
                 'eccab7fc3dcb489ea06e5bb15903370b', 'a2d415f4c571402d812d3f8f3d56dc9b')
        folder = Path.home()/'Library/Logs/AI-Aim-Trainer/camera_calibration'
        checked = 0
        for name in names:
            path = folder/f'assist-{name}.jsonl'
            if not path.is_file():
                continue
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            recorded = [r for r in rows if r.get('event') == 'result'][-1]
            after = [r['state'] for r in rows if r.get('event') == 'sample' and
                     r.get('test_id') == recorded['test_id']][-1]
            result = measurement(recorded['baseline_state'], after,
                                 recorded['requested_dx'], recorded['requested_dy'], expected_gain=.05)
            self.assertTrue(recorded['pre_window']['quiet'])
            self.assertTrue(recorded['post_window']['quiet'])
            self.assertTrue(result['mouse_frame_evidence']['consistent'])
            self.assertEqual(result['mouse_frame_evidence']['frame_count'], 2)
            self.assertFalse(result['valid'])
            self.assertFalse(result['total_magnitude']['valid'])
            self.assertAlmostEqual(result['degrees_per_delta'], .1, places=4)
            checked += 1
        if not checked:
            self.skipTest('Local recorded calibration evidence unavailable')

    def test_recorded_matrix_responses_match_calibration_validator(self):
        path = Path.home()/'Library/Logs/AI-Aim-Trainer/quartz_matrix/assist-5185f0395dd04cd8a29def127cc53a76.jsonl'
        if not path.is_file():
            self.skipTest('Local recorded Unity evidence unavailable')
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        checked = passed = 0
        for trial in rows:
            if trial.get('event') != 'result' or trial.get('matrix_case') == 'zero':
                continue
            if type(trial.get('controlled_trial_passed')) is not bool:
                continue
            before = trial['baseline_state']
            after = next(r['state'] for r in rows if r.get('event') == 'sample' and
                         r.get('test_id') == trial['test_id'] and r['state']['frame'] > before['frame'] and
                         r['state']['axis_nonzero_frames']-before['axis_nonzero_frames'] == trial['unity_nonzero_mouse_frames'])
            result = measurement(before, after, trial['requested_dx'], trial['requested_dy'])
            self.assertEqual(result['success'], trial['success'])
            checked += 1
            if result['valid']:
                passed += 1
                self.assertTrue(result['mouse_frame_evidence']['consistent'])
                self.assertAlmostEqual(result['degrees_per_delta'], .05, places=4)
        self.assertGreaterEqual(checked, 5)
        self.assertEqual(passed, 4)
