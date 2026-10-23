"""Isolated manual seven-case matrix. No posts on launch; F6 sends ONE trial."""
import argparse
import json
import math
import os
from pathlib import Path
import socket
import signal
import statistics
import threading
import time
import traceback

from .audit_destination import resolve_destination
from .macos_input import accessibility_trusted
from .macos_foreground import ForegroundQuery
from .quartz_delivery_test import Experiment, assess, angle_delta, valid_state, post_relative_pulse
from .telemetry import CorrectionLog
from .diagnostic_udp import DiagnosticAssembler

CASES = {'zero': (0, 0), 'horizontal-positive': (2, 0), 'horizontal-negative': (-2, 0),
         'vertical-positive': (0, 2), 'vertical-negative': (0, -2),
         'diagonal-positive': (2, 2), 'diagonal-negative': (-2, -2)}
DIAGNOSTIC_PORT = 8767
STABLE_GAME_SECONDS = .35


class PreconditionChanged(RuntimeError):
    """Native safety gate rejected the trial before creating/posting an event."""


class EmergencyStop(RuntimeError):
    """Latched emergency detected at the final native gate, before posting."""


class MatrixSignal(BaseException):
    def __init__(self, signum):
        self.signum = signum


def stop_for_signal(signum, _frame):
    # Do not write JSON from a signal handler: it could interrupt another write.
    raise MatrixSignal(signum)


class TelemetryReception:
    """Keep rejected packet diagnostics separate from last valid Unity state."""
    def __init__(self):
        self.last_packet_at = None
        self.last_packet_pid = None
        self.last_packet_rejection = None
        self.packet_count = 0
        self.valid_packet_count = 0
        self.pending_chunk_count = 0
        self.assembler = DiagnosticAssembler()
        self.last_state_received_at = None
        self.last_transport = None

    def decode(self, data, pid, now):
        self.packet_count += 1
        self.last_packet_at = now
        self.last_packet_pid = None
        try:
            candidate = self.assembler.feed(data, pid, now)
        except ValueError as error:
            self.last_packet_rejection = str(error)
            return None
        if candidate is None and self.assembler.pending:
            self.pending_chunk_count += 1
            self.last_packet_pid = pid
            # An in-flight next snapshot is normal, not invalid telemetry. It
            # never replaces/refreshes the last COMPLETE state or clears an error.
            return None
        if not isinstance(candidate, dict):
            self.last_packet_rejection = 'telemetry_not_an_object'
        elif candidate.get('pid') != pid:
            self.last_packet_pid = candidate.get('pid') if type(candidate.get('pid')) is int else None
            self.last_packet_rejection = f'telemetry_pid_mismatch (expected {pid}, received {self.last_packet_pid})'
        elif candidate.get('diagnostic_version') != 1:
            self.last_packet_pid = pid
            self.last_packet_rejection = 'diagnostic_version_missing_or_unsupported (enable Publish Quartz Diagnostics)'
        elif not valid_state(candidate, pid):
            self.last_packet_pid = pid
            self.last_packet_rejection = 'invalid_diagnostic_fields (check frame, axis counters, numeric values and boolean flags)'
        else:
            self.last_packet_pid = pid
            self.last_packet_rejection = None
            self.valid_packet_count += 1
            self.last_state_received_at = self.assembler.received_at
            self.last_transport = self.assembler.transport
            return candidate
        return None


def precondition_snapshot(backend, state, received_at, now, port=DIAGNOSTIC_PORT, reception=None,
                          require_frame_history=False):
    process = backend.snapshot()
    checked_at = process.get('foreground_checked_monotonic')
    if type(checked_at) in (int, float) and math.isfinite(checked_at):
        now = max(now, checked_at)  # Include time spent servicing foreground notifications.
    valid = state is not None and valid_state(state, backend.pid)
    age = ((now-received_at)*1000 if valid and type(received_at) in (int, float)
           and math.isfinite(received_at) else None)
    fresh = age is not None and 0 <= age < 200
    failures = []
    if process.get('foreground_pid') != backend.pid:
        failures.append('foreground_pid_mismatch')
    if process.get('accessibility_trusted') is not True:
        failures.append('accessibility_permission_denied')
    if state is None:
        failures.append('unity_telemetry_not_received')
    elif not valid:
        failures.append('invalid_unity_telemetry')
    elif not fresh:
        failures.append('unity_telemetry_stale' if age is not None and age >= 200 else 'invalid_telemetry_age')
    if valid and state['gameplay'] is not True:
        failures.append('gameplay_inactive')
    if valid and require_frame_history and not validate_mouse_frame_schema(state).get('schema_valid'):
        failures.append('calibration_requires_frame_history_schema_v1')
    details = {k: state.get(k) if valid and type(state.get(k)) is bool else None
               for k in ('cursor_locked', 'session_active', 'paused', 'application_focused',
                         'gameplay_input_enabled', 'session_present', 'cursor_manager_present',
                         'cursor_visible', 'settings_manager_present', 'ui_manager_present',
                         'settings_open', 'settings_panel_visible', 'summary_open',
                         'summary_panel_visible', 'start_menu_visible')}
    for key in ('cursor_locked', 'session_active', 'application_focused', 'gameplay_input_enabled'):
        if details[key] is False:
            failures.append(key + '_false')
    if details['paused'] is True:
        failures.append('session_paused')
    if details['session_present'] is False:
        failures.append('session_manager_missing')
        details['paused'] = None
        details['summary_open'] = None
    if details['cursor_manager_present'] is False:
        failures.append('cursor_manager_missing')
    if details['ui_manager_present'] is False:
        details['summary_panel_visible'] = details['start_menu_visible'] = None
    if details['settings_manager_present'] is False:
        details['settings_open'] = details['settings_panel_visible'] = None
    for key in ('settings_open', 'settings_panel_visible', 'summary_open', 'summary_panel_visible', 'start_menu_visible'):
        if details[key] is True:
            failures.append(key)
    if valid and require_frame_history:
        # Calibration must not infer cursor/menu safety from an aggregate flag.
        for key in ('application_focused', 'cursor_locked', 'session_active', 'paused',
                    'gameplay_input_enabled', 'settings_open', 'settings_panel_visible',
                    'summary_open', 'summary_panel_visible', 'start_menu_visible'):
            if details[key] is None:
                failures.append('calibration_requires_explicit_' + key)
    blockers = state.get('gameplay_blockers') if valid else None
    if not isinstance(blockers, list) or not all(isinstance(b, str) for b in blockers):
        blockers = None
    if blockers and valid and state['gameplay']:
        failures.append('publisher_gameplay_blockers_conflict')
    try:
        backend.validate_destination()
    except RuntimeError as error:
        failures.append('destination_validation_failed: ' + str(error))
    if reception and reception.last_packet_rejection:
        failures.append(reception.last_packet_rejection)
    return {'selected_game_pid': backend.pid, 'foreground_pid': process.get('foreground_pid'),
            **{k: process.get(k) for k in ('nsworkspace_before_pump_pid', 'nsworkspace_after_pump_pid',
                                         'foreground_query', 'foreground_checked_at')},
            'unity_telemetry_received': valid, 'last_telemetry_age_ms': age,
            'gameplay_active': state['gameplay'] if valid else None, **details,
            'unity_gameplay_blockers': blockers,
            'unity_sent_at_utc': state.get('sent_at_utc') if valid else None,
            'unity_frame': state.get('frame') if valid else None,
            'unity_precondition_version': state.get('precondition_version') if valid else None,
            'cursor_lock_mode': state.get('cursor_lock_mode') if valid else None,
            'unity_time_scale': state.get('time_scale') if valid else None,
            'accessibility_trusted': process.get('accessibility_trusted'),
            'udp_diagnostic_port': port,
            'udp_packets_received': reception.packet_count if reception else None,
            'udp_valid_packets_received': reception.valid_packet_count if reception else None,
            'udp_invalid_packets_received': reception.packet_count-reception.valid_packet_count-reception.pending_chunk_count if reception else None,
            'udp_pending_chunks_received': reception.pending_chunk_count if reception else None,
            'diagnostic_transport': reception.last_transport if reception else None,
            'last_udp_packet_pid': reception.last_packet_pid if reception else None,
            'last_udp_packet_rejection': reception.last_packet_rejection if reception else None,
            'rejected_preconditions': failures}


def print_preconditions(snapshot):
    def flag(value):
        return 'yes' if value is True else 'no' if value is False else 'unknown (not published by Unity)'
    age = snapshot['last_telemetry_age_ms']
    # Keep formatting separate so a missing age is never converted to a fake zero.
    lines = [('Selected game PID', snapshot['selected_game_pid']), ('Foreground PID', snapshot['foreground_pid']),
             ('Unity telemetry received', flag(snapshot['unity_telemetry_received'])),
             ('Last telemetry age', f'{age:.1f} ms' if age is not None else 'unknown (no valid telemetry)'),
             ('Gameplay active', flag(snapshot['gameplay_active'])), ('Cursor locked', flag(snapshot['cursor_locked'])),
             ('Session active', flag(snapshot['session_active'])), ('Paused', flag(snapshot['paused'])),
             ('Unity application focused', flag(snapshot.get('application_focused'))),
             ('Gameplay input enabled', flag(snapshot.get('gameplay_input_enabled'))),
             ('Settings panel visible', flag(snapshot.get('settings_panel_visible'))),
             ('Summary logically open', flag(snapshot.get('summary_open'))),
             ('Summary panel visible', flag(snapshot.get('summary_panel_visible'))),
             ('Start menu visible', flag(snapshot.get('start_menu_visible'))),
             ('Unity gameplay blockers', ', '.join(snapshot['unity_gameplay_blockers']) or 'none'
              if snapshot.get('unity_gameplay_blockers') is not None else 'unknown (old telemetry)'),
             ('Unity frame / send time', f"{snapshot.get('unity_frame')} / {snapshot.get('unity_sent_at_utc')}"),
             ('Accessibility trusted', flag(snapshot['accessibility_trusted'])),
             ('UDP diagnostic port', snapshot['udp_diagnostic_port']),
             ('UDP packets / valid / invalid',
              f"{snapshot.get('udp_packets_received')} / {snapshot.get('udp_valid_packets_received')} / {snapshot.get('udp_invalid_packets_received')}"),
             ('Exact rejected precondition(s)', '; '.join(snapshot['rejected_preconditions']) or 'none')]
    if snapshot.get('last_udp_packet_rejection'):
        lines.append(('Last rejected UDP packet', snapshot['last_udp_packet_rejection']))
    print('\nMatrix preconditions:\n' + '\n'.join(f'  {name}: {value}' for name, value in lines), flush=True)


def validate_mouse_frame_schema(state):
    """Read-only wire-schema check; no sockets, native APIs, or input posting."""
    version = state.get('mouse_frame_version')
    if 'mouse_frame_version' not in state:
        return {'available': False, 'consistent': None, 'reason': 'requires_updated_Unity_publisher',
                'issues': ['mouse_frame_version_missing']}
    if type(version) is int and version == 0:
        return {'available': False, 'consistent': None,
                'reason': 'normal_coach_stream_no_frame_history_check_port_mapping',
                'issues': ['mouse_frame_version_is_0_expected_1'],
                'hint': 'Check Unity Coach State Port=8766 and Quartz Diagnostic Port=8767; do not swap them.'}
    if type(version) is not int or version != 1:
        return {'available': False, 'consistent': None, 'reason': 'unsupported_mouse_frame_version',
                'issues': ['mouse_frame_version_not_supported']}
    rows = state.get('mouse_frames')
    numeric = ('realtime', 'mouse_x', 'mouse_y', 'raw_x', 'raw_y', 'yaw', 'pitch',
               'yaw_delta', 'pitch_delta', 'consumed_x', 'consumed_y')
    if not isinstance(rows, list) or any(
            not isinstance(r, dict) or type(r.get('frame')) is not int or
            type(r.get('input_sequence')) is not int or
            not isinstance(r.get('timestamp'), str) or
            any(type(r.get(k)) not in (int, float) or not math.isfinite(r[k]) for k in numeric)
            for r in rows):
        return {'available': True, 'consistent': False, 'reason': 'malformed_frame_history',
                'issues': ['mouse_frames_missing_or_invalid_array_entries']}
    return {'available': True, 'schema_valid': True, 'issues': [], 'history_entries': len(rows)}


def validate_log_schema(paths):
    reports = []
    for path in paths:
        counts = {}
        with Path(path).open(encoding='utf-8') as source:
            for line in source:
                row = json.loads(line)
                if row.get('event') != 'sample' or not isinstance(row.get('state'), dict):
                    continue
                schema = validate_mouse_frame_schema(row['state'])
                key = schema.get('reason', 'frame_history_schema_valid')
                counts[key] = counts.get(key, 0)+1
        reports.append({'path': str(path), 'sample_schema_counts': counts})
    return {'logs': reports, 'input_events_posted': False, 'head_lock_enabled': False}


def mouse_frame_evidence(before, after, delta):
    """Compare Unity frame history with counters; never infer hardware provenance."""
    schema = validate_mouse_frame_schema(after)
    if not schema.get('schema_valid'):
        return schema
    count = after['axis_nonzero_frames'] - before['axis_nonzero_frames']
    rows = after['mouse_frames']
    frames = [r for r in rows if before['frame'] < r['frame'] <= after['frame']]
    complete = len(frames) == count and all(
        r['input_sequence'] == before['axis_nonzero_frames']+i+1 for i, r in enumerate(frames))
    ordered = all(b['frame'] > a['frame'] and b['realtime'] > a['realtime']
                  for a, b in zip(frames, frames[1:]))
    sums = {k: sum(r[k] for r in frames) for k in ('mouse_x', 'mouse_y', 'raw_x', 'raw_y')}
    # Counter subtraction is float32 in Unity; this tolerance is diagnostic
    # reconciliation only, not a relaxation of rotation or direction limits.
    totals_match = all(math.isclose(sums[k], after[field]-before[field], abs_tol=1e-5, rel_tol=1e-5)
                       for k, field in (('mouse_x', 'axis_sum_x'), ('mouse_y', 'axis_sum_y'),
                                        ('raw_x', 'raw_sum_x'), ('raw_y', 'raw_sum_y')))
    per_frame_direction = all(
        (r['mouse_x']*delta[0] > 0 if delta[0] else abs(r['mouse_x']) < 1e-6) and
        (-r['mouse_y']*delta[1] > 0 if delta[1] else abs(r['mouse_y']) < 1e-6)
        for r in frames)
    sensitivity = before.get('sensitivity')
    camera_matches = None
    if type(sensitivity) in (int, float) and math.isfinite(sensitivity):
        camera_matches = all(r.get('look_processed') is True and
                             abs(r['consumed_x']-r['mouse_x']) < 1e-6 and
                             abs(r['consumed_y']-r['mouse_y']) < 1e-6 and
                             abs(r['yaw_delta']-r['consumed_x']*sensitivity) <= .005 and
                             abs(r['pitch_delta']+r['consumed_y']*sensitivity) <= .005
                             for r in frames)
    camera_totals_match = all(abs(sum(r[field] for r in frames)-angle_delta(after[axis], before[axis])) <= .005
                              for field, axis in (('yaw_delta', 'yaw'), ('pitch_delta', 'pitch')))
    safe_frames = all(r.get('application_focused') is True and r.get('cursor_locked') is True
                      for r in frames)
    consistent = (complete and ordered and len(frames) == count and totals_match and
                  per_frame_direction and safe_frames and camera_matches is not False and camera_totals_match)
    return {'available': True, 'consistent': consistent, 'history_complete': complete,
            'chronological': ordered, 'frame_count': len(frames), 'totals': sums,
            'totals_match_counters': totals_match, 'per_frame_direction_matches': per_frame_direction,
            'camera_matches_consumed_input': camera_matches, 'frame_focus_and_lock_valid': safe_frames,
            'camera_totals_match': camera_totals_match,
            'frames': frames, 'physical_contamination_ruled_out': False}


def evaluate(before, after, delta, expected_gain=None):
    result = assess(before, after, 'zero')
    if delta == (0, 0):
        return result
    frame_count_valid = result['unity_nonzero_mouse_frames'] == 1
    direction_valid = True
    bounds_valid = True
    for requested, rotation, received in (
            (delta[0], result['camera_yaw_change'], result['unity_received_mouse_x']),
            (delta[1], result['camera_pitch_change'], -result['unity_received_mouse_y'])):
        if requested:
            direction_valid = direction_valid and rotation*requested > 0 and received*requested > 0
            bounds_valid = bounds_valid and .005 < abs(rotation) < 3
        else:
            direction_valid = direction_valid and abs(rotation) <= .005 and abs(received) < 1e-6
            bounds_valid = bounds_valid and abs(rotation) <= .005 and abs(received) < 1e-6
    evidence = mouse_frame_evidence(before, after, delta)
    # Compare the TOTAL response independently of frame count. Two full-sized
    # responses are not evidence of one pulse split over two frames.
    magnitude = {'valid': None, 'expected_gain': expected_gain,
                 'relative_tolerance': .2, 'axes': []}
    if expected_gain is not None:
        if type(expected_gain) not in (int, float) or not math.isfinite(expected_gain) or expected_gain <= 0:
            raise ValueError('Expected gain must be finite and positive')
        for axis, requested, rotation, received in (
                ('horizontal', delta[0], result['camera_yaw_change'], result['unity_received_mouse_x']),
                ('vertical', delta[1], result['camera_pitch_change'], -result['unity_received_mouse_y'])):
            if not requested:
                continue
            expected_rotation = requested * expected_gain
            rotation_error = abs(rotation / expected_rotation - 1)
            sensitivity = before.get('sensitivity')
            expected_input = (expected_rotation / sensitivity if type(sensitivity) in (int, float)
                              and math.isfinite(sensitivity) and sensitivity > 0 else None)
            input_error = abs(received / expected_input - 1) if expected_input is not None else None
            magnitude['axes'].append({'axis': axis, 'expected_rotation': expected_rotation,
                'observed_rotation': rotation, 'rotation_relative_error': rotation_error,
                'expected_unity_input': expected_input, 'observed_unity_input': received,
                'input_relative_error': input_error,
                'valid': rotation_error <= .2 and (input_error is None or input_error <= .2)})
        magnitude['valid'] = all(a['valid'] for a in magnitude['axes'])
    frames = evidence.get('frames', [])
    timing = {'chronological': evidence.get('chronological'),
              'span_ms': (frames[-1]['realtime']-frames[0]['realtime'])*1000 if frames else None,
              'frame_gaps': [b['frame']-a['frame'] for a, b in zip(frames, frames[1:])],
              'note': 'Pulse membership and quiet pre/post windows are checked by the experiment.'}
    good = (frame_count_valid and direction_valid and bounds_valid and
            evidence['consistent'] is not False and magnitude['valid'] is not False)
    reasons = []
    if not frame_count_valid:
        reasons.append('nonzero_frame_count_not_one')
    if not direction_valid:
        reasons.append('unexpected_axis_or_direction')
    if not bounds_valid:
        reasons.append('rotation_outside_existing_bounds')
    if evidence['consistent'] is False:
        reasons.append('inconsistent_or_incomplete_frame_evidence')
    if magnitude['valid'] is False:
        reasons.append('total_response_magnitude_outside_20_percent')
    return {**result, 'success': bool(good), 'direction_matches': bool(direction_valid),
            'response_in_existing_bounds': bool(bounds_valid), 'frame_count_valid': frame_count_valid,
            'rejected_checks': reasons, 'mouse_frame_evidence': evidence,
            'total_magnitude': magnitude, 'input_timing': timing,
            'requested_quartz_delta': list(delta),
            # Different units: report a measured ratio, not an assumed 1:1 mapping.
            'unity_axis_per_requested_unit': [result['unity_received_mouse_x']/delta[0] if delta[0] else None,
                                             -result['unity_received_mouse_y']/delta[1] if delta[1] else None],
            'multiframe_provenance': 'unverified' if result['unity_nonzero_mouse_frames'] > 1 else 'not_applicable',
            'outcome': 'observed_response' if good else 'no_unity_delta' if result['quiet']
                       else 'unexpected_or_inconsistent_response'}


class MatrixExperiment(Experiment):
    def __init__(self, backend, log, initial_keys, case, clock=time.perf_counter,
                 port=DIAGNOSTIC_PORT, reception=None, initial_hotkeys=None, require_frame_history=False):
        self.require_frame_history = require_frame_history
        self.case = case
        self.delta = CASES[case]
        super().__init__(backend, log, initial_keys, clock=clock)
        self.engaged = False
        self.port, self.reception = port, reception
        self.last_preconditions = None
        self.last_failure_signature = None
        self.control_state = 'WAITING_FOR_GAME'
        self.stable_since = None
        self.stable_frames = set()
        self.stop_reason = None
        self.previous_hotkeys = dict(initial_hotkeys or {})
        self.native_emergency_latched = False
        self.log.write({'event': 'state_transition', 'state': self.control_state,
                        'reason': 'startup', 'head_lock_enabled': False})

    def stop(self, reason):
        self.stop_reason = reason
        self.cancel(reason)
        return False

    def wait_for_game(self, reason, keys):
        if self.pending:
            self.cancel(reason)
            self.last_completed = self.clock()
        if self.control_state != 'WAITING_FOR_GAME':
            self.log.write({'event': 'state_transition', 'state': 'WAITING_FOR_GAME',
                            'reason': reason, 'head_lock_enabled': False})
            print('WAITING_FOR_GAME: ' + reason, flush=True)
        self.control_state = 'WAITING_FOR_GAME'
        self.stable_since = None
        self.stable_frames.clear()
        self.previous = dict(keys)
        self.history.clear()

    def log_hotkeys(self, keys):
        for key in sorted(set(self.previous_hotkeys) | set(keys)):
            if bool(keys.get(key)) != bool(self.previous_hotkeys.get(key)):
                self.log.write({'event': 'hotkey', 'key': key, 'pressed': bool(keys.get(key)),
                                'state': self.control_state, 'head_lock_enabled': False})
        self.previous_hotkeys = dict(keys)

    def emit_preconditions(self):
        self.log.write({'event': 'precondition_check', **self.last_preconditions,
                        'input_events_posted': False, 'head_lock_enabled': False})
        print_preconditions(self.last_preconditions)

    def reject(self, method, reason):
        if reason == 'emergency_stop':
            self.native_emergency_latched = True
        if self.last_preconditions is not None:
            state, received_at = self.latest_input
            self.last_preconditions = precondition_snapshot(self.backend, state, received_at,
                                                           self.clock(), self.port, self.reception,
                                                           self.require_frame_history)
            self.last_preconditions = {**self.last_preconditions,
                'rejected_preconditions': list(dict.fromkeys(self.last_preconditions['rejected_preconditions'] + [reason]))}
            self.emit_preconditions()
        super().reject(method, reason)

    def requested_delta(self, method):
        return self.delta if method in ('pid', 'hid') else (0, 0)

    def assess_response(self, before, after, method):
        return {**evaluate(before, after, self.requested_delta(method)),
                'matrix_case': self.case if method in ('pid', 'hid') else 'zero'}

    def log_sample(self, timestamp, state):
        super().log_sample(timestamp, state)
        if self.pending is None or state.get('mouse_frame_version') != 1:
            return
        pending = self.pending
        seen = pending.setdefault('logged_input_sequences', set())
        for frame in state.get('mouse_frames', []):
            if (not isinstance(frame, dict) or type(frame.get('input_sequence')) is not int or
                    type(frame.get('frame')) is not int):
                continue
            sequence = frame['input_sequence']
            if sequence in seen or sequence <= pending['before']['axis_nonzero_frames']:
                continue
            seen.add(sequence)
            pulse_end = pending.get('pulse_after')
            self.log.write({'event': 'unity_mouse_frame', 'test_id': pending['record']['test_id'],
                            'phase': 'post' if pulse_end and frame['frame'] > pulse_end['frame'] else 'pulse',
                            'receive_monotonic': timestamp, 'state': frame,
                            'hardware_provenance': 'unknown', 'head_lock_enabled': False})

    def tick(self, state, received_at, keys, emergency=False, hotkeys=None):
        now = self.clock()
        self.latest_input = (state, received_at)
        raw = hotkeys if hotkeys is not None else {
            'F4': bool(keys.get('zero')), 'F6': bool(keys.get('pid') or keys.get('hid'))}
        self.log_hotkeys(raw)
        edges = [k for k, pressed in keys.items() if pressed and not self.previous.get(k, False)]
        if raw.get('F8') or raw.get('ESC') or emergency or self.backend.emergency():
            return self.stop('hotkey_F8' if raw.get('F8') else 'hotkey_ESC' if raw.get('ESC') else 'emergency_stop_native')
        self.last_preconditions = precondition_snapshot(self.backend, state, received_at, now,
                                                       self.port, self.reception, self.require_frame_history)
        age = self.last_preconditions['last_telemetry_age_ms']
        fresh = age is not None and 0 <= age < 200
        safe = not self.last_preconditions['rejected_preconditions']
        if fresh and state['emergency']:
            self.last_preconditions['rejected_preconditions'].append('emergency_stop')
            self.emit_preconditions()
            return self.stop('emergency_stop_unity_telemetry')
        if not safe:
            signature = (tuple(self.last_preconditions['rejected_preconditions']),
                         self.last_preconditions['foreground_pid'])
            if edges or self.control_state == 'READY' or signature != self.last_failure_signature:
                self.emit_preconditions()
            self.last_failure_signature = signature
            reason = '; '.join(self.last_preconditions['rejected_preconditions'])
            self.wait_for_game(reason, keys)
            if edges:
                self.log.write({'event': 'hotkey_rejected', 'actions': edges,
                                'reason': reason, 'state': self.control_state})
            if any(r.startswith('destination_validation_failed') for r in self.last_preconditions['rejected_preconditions']):
                return self.stop(reason)
            return True
        self.last_failure_signature = None
        if edges:
            self.emit_preconditions()
        if safe:
            self.backend.validate_destination()
            self.engaged = True
        if self.control_state != 'READY':
            if self.stable_since is None:
                self.stable_since = now
            if len(self.stable_frames) < 3:
                self.stable_frames.add(state['frame'])
            if not self.history or self.history[-1][1]['frame'] != state['frame']:
                self.history.append((received_at, dict(state)))
            while self.history and now-self.history[0][0] > .6:
                self.history.popleft()
            self.previous = dict(keys)  # Includes a key held across the READY boundary.
            if edges:
                self.log.write({'event': 'hotkey_rejected', 'actions': edges,
                                'reason': 'game_state_not_yet_stable', 'state': self.control_state})
                print('WAITING_FOR_GAME: let game state settle, release F4/F6, then press again after READY.', flush=True)
            if now-self.stable_since >= STABLE_GAME_SECONDS and len(self.stable_frames) >= 3:
                self.control_state = 'READY'
                self.log.write({'event': 'state_transition', 'state': 'READY',
                                'stable_seconds': now-self.stable_since,
                                'distinct_frames': len(self.stable_frames), 'head_lock_enabled': False})
                print('READY: foreground and Unity gameplay are stable. F4 zero; F6 ONE trial; F8/ESC stop.', flush=True)
            return True
        if self.pending and fresh:
            before = self.pending['before']
            if (state['frame'] < before['frame'] or
                    state['axis_nonzero_frames'] < before['axis_nonzero_frames'] or
                    max(abs(angle_delta(state[k], before[k])) for k in ('yaw', 'pitch')) >= 3):
                self.log_sample(received_at, state)
                return self.stop('camera_limit_or_unity_counter_reset')
        previous = self.last_result
        try:
            running = super().tick(state, received_at, keys, emergency)
        except EmergencyStop as error:
            return self.stop(str(error))
        except PreconditionChanged as error:
            self.wait_for_game(str(error), keys)
            return True
        if not running:
            if self.native_emergency_latched or self.backend.emergency():
                return self.stop('emergency_stop_native')
            self.wait_for_game('last_moment_safety_gate_failed', keys)
            return True
        # The shared A/B engine can detect focus loss after our initial snapshot.
        if not self.backend.focused():
            self.wait_for_game('foreground_changed_during_tick', keys)
            return True
        if self.last_result is not previous:
            result = self.last_result
            # A silent failed pulse is useful matrix evidence, never a passing trial.
            # Any next pulse STILL requires a new manual key press and quiet baseline.
            quiet_windows = result['pre_window']['quiet'] and result['post_window']['quiet']
            if not quiet_windows or not result['success'] and result['outcome'] != 'no_unity_delta':
                return self.stop('noisy_windows_or_unexpected_camera_response')
        return running


def summarize(paths):
    groups = {}
    for path in paths:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            if r.get('event') != 'result' or 'matrix_case' not in r:
                continue
            key = (r['matrix_case'], r.get('matrix_method', 'pid'))
            groups.setdefault(key, []).append(r)
    output = []
    for (case, method), rows in groups.items():
        measured = [r for r in rows if isinstance(r.get('unity_received_mouse_x'), (int, float))]
        stats = {}
        for key in ('unity_received_mouse_x', 'unity_received_mouse_y', 'camera_yaw_change', 'camera_pitch_change'):
            values = [r[key] for r in measured]
            stats[key] = {'mean': statistics.mean(values) if values else None,
                          'stddev': statistics.pstdev(values) if values else None}
        output.append({'case': case, 'method': method, 'trials': len(rows),
                       'measured_trials': len(measured),
                       'controlled_passes': sum(bool(r.get('controlled_trial_passed')) for r in rows),
                       'silent_failures': sum(r.get('outcome') == 'no_unity_delta' for r in rows),
                       'direction_valid_trials': sum(r.get('direction_matches') is True for r in rows),
                       'nonzero_frame_counts': [r.get('unity_nonzero_mouse_frames') for r in rows],
                       'multiframe_trials': sum(r.get('unity_nonzero_mouse_frames', 0) > 1
                                               for r in rows if type(r.get('unity_nonzero_mouse_frames')) is int),
                       'complete_consistent_frame_traces': sum(
                           r.get('mouse_frame_evidence', {}).get('consistent') is True for r in rows),
                       'event_timestamps_ns': [r.get('event_timestamp_ns') for r in rows],
                       'statistics': stats})
    return {'groups': output, 'head_lock_enabled': False, 'independently_verified': False}


def inspect_events(q):
    """Read-only creation/readback. Never posts, warps or clicks."""
    rows = []
    location = q.CGEventGetLocation(q.CGEventCreate(None))
    for name, (dx, dy) in CASES.items():
        event = q.CGEventCreateMouseEvent(None, q.kCGEventMouseMoved, location, q.kCGMouseButtonRight)
        if event is None:
            raise RuntimeError('Cannot create read-only probe event')
        created = int(q.CGEventGetTimestamp(event))
        q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaX, dx)
        q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaY, dy)
        rows.append({'case': name, 'timestamp_on_creation': created,
                     'timestamp_after_fields': int(q.CGEventGetTimestamp(event)),
                     'event_dx': int(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaX)),
                     'event_dy': int(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaY)),
                     'input_events_posted': False})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-id', type=int)
    parser.add_argument('--case', choices=CASES)
    parser.add_argument('--method', choices=('pid', 'hid'), default='pid')
    parser.add_argument('--expect-app', default='AI-Aim-Trainer-Test2.app')
    parser.add_argument('--port', type=int, default=DIAGNOSTIC_PORT, help='Unity diagnostic UDP port (default 8767)')
    parser.add_argument('--summarize', nargs='+', metavar='JSONL')
    parser.add_argument('--validate-telemetry-log', nargs='+', metavar='JSONL',
                        help='Read-only frame-history schema validation; no native APIs or input')
    parser.add_argument('--inspect-events', action='store_true', help='Read-only timestamp/delta probe; no posting')
    args = parser.parse_args()
    if args.validate_telemetry_log:
        print(json.dumps(validate_log_schema(args.validate_telemetry_log), indent=2))
        return
    if args.summarize:
        print(json.dumps(summarize(args.summarize), indent=2, allow_nan=False))
        return
    if args.inspect_events:
        import Quartz
        print(json.dumps(inspect_events(Quartz), indent=2))
        return
    if args.window_id is None or args.case is None:
        parser.error('--window-id and --case are required for manual trials')
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    import Quartz as q
    if not accessibility_trusted():
        parser.error('AX Accessibility denied for this process; no events sent.')
    destination = resolve_destination(args.window_id, expected_app=args.expect_app)
    pid = destination['resolved_owner_pid']
    reception = TelemetryReception()
    foreground_query = ForegroundQuery()

    class Backend:
        def __init__(self):
            self.pid = pid

        def validate_destination(self):
            return {**resolve_destination(args.window_id, pid, destination['game_executable'], args.expect_app),
                    'matrix_case': args.case, 'matrix_method': args.method}

        def trusted(self):
            return accessibility_trusted()

        def snapshot(self):
            foreground = foreground_query.snapshot()
            return {**foreground, 'game_focused': foreground['foreground_pid'] == pid,
                    'accessibility_trusted': self.trusted(), 'source_pid': os.getpid(),
                    'posting_thread': threading.current_thread().name}

        def focused(self):
            return self.snapshot()['game_focused']

        def emergency(self):
            return any(q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, k) for k in (100, 53))

        def post(self, method):
            context, before = self.validate_destination(), self.snapshot()
            check = precondition_snapshot(self, state, received, time.perf_counter(), args.port, reception)
            emergency_keys = hotkeys()
            emergency_source = ('hotkey_F8' if emergency_keys['F8'] else
                                'hotkey_ESC' if emergency_keys['ESC'] else None)
            if emergency_source:
                check['rejected_preconditions'].append('emergency_stop')
            log.write({'event': 'native_precondition_check', **check, 'input_events_posted': False})
            if check['rejected_preconditions'] or not before['game_focused'] or not before['accessibility_trusted']:
                print_preconditions(check)
                if emergency_source:
                    raise EmergencyStop(emergency_source)
                raise PreconditionChanged('Native pre-post safety gate failed: ' +
                                   '; '.join(check['rejected_preconditions'] or ['process_state_changed']))
            native = post_relative_pulse(q, method, pid, *CASES[args.case])
            return {**context, **native, **before, 'focus_after': self.snapshot()}

    def hotkeys():
        pressed = lambda code: bool(q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, code))
        return {name: pressed(code) for name, code in (('F4', 118), ('F6', 97), ('F8', 100), ('ESC', 53))}

    def keys(raw):
        trigger = raw['F6']
        return {'zero': raw['F4'] or trigger and args.case == 'zero',
                args.method: trigger and args.case != 'zero'}

    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    log = experiment = None
    shutdown_reason = 'startup_incomplete'
    shutdown_details = {}
    old_handlers = {}
    try:
        try:
            receiver.bind(('127.0.0.1', args.port))
        except OSError as error:
            raise RuntimeError(f'Cannot listen on UDP diagnostic port {args.port}: {error}. '
                               'Check the port and stop any other calibration/A-B receiver.') from error
        receiver.setblocking(False)
        log = CorrectionLog(Path.home()/'Library/Logs/AI-Aim-Trainer/quartz_matrix')
        backend = Backend()
        log.write({'event': 'matrix_startup', **backend.validate_destination(), **backend.snapshot(),
                   'delta': CASES[args.case], 'udp_diagnostic_port': args.port, 'head_lock_enabled': False})
        initial_keys = hotkeys()
        experiment = MatrixExperiment(backend, log, keys(initial_keys), args.case, port=args.port,
                                      reception=reception, initial_hotkeys=initial_keys)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            old_handlers[sig] = signal.signal(sig, stop_for_signal)
        print(f'Case {args.case}, delta={CASES[args.case]}, method={args.method}.\n'
              f'No events on launch. Focus game, keep mouse still. F6 ONE trial; F4 zero; F8/ESC stop.\nLog: {log.path}', flush=True)
        state, received = None, 0
        while True:
            for _ in range(32):
                try:
                    data, address = receiver.recvfrom(65535)
                except BlockingIOError:
                    break
                if address[0] == '127.0.0.1':
                    packet_time = time.perf_counter()
                    candidate = reception.decode(data, pid, packet_time)
                    if candidate is not None:
                        state, received = candidate, reception.last_state_received_at
            raw = hotkeys()
            if not experiment.tick(state, received, keys(raw), backend.emergency(), hotkeys=raw):
                shutdown_reason = experiment.stop_reason or 'tick_requested_stop_without_reason'
                break
            time.sleep(.01)
    except KeyboardInterrupt:
        shutdown_reason = 'keyboard_interrupt'
        if experiment:
            experiment.cancel('ctrl_c')
    except MatrixSignal as error:
        shutdown_reason = 'signal_' + signal.Signals(error.signum).name
        shutdown_details = {'signal_number': error.signum}
        if experiment:
            experiment.cancel(shutdown_reason)
    except Exception as error:
        shutdown_reason = 'exception'
        shutdown_details = {'exception_type': type(error).__name__, 'exception_message': str(error),
                            'traceback': traceback.format_exc()}
        if experiment:
            experiment.cancel('matrix_error')
        raise
    finally:
        receiver.close()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        if log:
            log.write({'event': 'matrix_shutdown', 'reason': shutdown_reason, **shutdown_details,
                       'state': experiment.control_state if experiment else None,
                       'last_preconditions': experiment.last_preconditions if experiment else None,
                       'last_hotkeys': experiment.previous_hotkeys if experiment else None,
                       'head_lock_enabled': False})
            log.close()
        print('Matrix shutdown: ' + shutdown_reason, flush=True)


if __name__ == '__main__':
    main()
