"""Explicit F6 calibration using the Quartz Matrix safety/observation engine."""
import json
import os
from pathlib import Path
import socket
import statistics
import threading
import time

from .quartz_matrix import (MatrixExperiment, TelemetryReception, CASES, evaluate,
                           precondition_snapshot, PreconditionChanged, EmergencyStop)
from .quartz_delivery_test import post_relative_pulse
from .telemetry import CorrectionLog
from .macos_input import accessibility_trusted, MacMouseBackend
from .macos_foreground import ForegroundQuery
from .audit_destination import resolve_destination

PLAN = [(0, 0), (2, 0), (-2, 0), (0, 2), (0, -2)] * 3
EXPECTED_APP = 'AI-Aim-Trainer-Test3.app'


def measurement(before, after, dx, dy, expected_gain=None):
    """Reporting only: all movement validation lives in the matrix."""
    result = evaluate(before, after, (dx, dy), expected_gain=expected_gain)
    if any((dx, dy)) and result['mouse_frame_evidence'].get('consistent') is not True:
        result['success'] = False
        result['rejected_checks'] = list(dict.fromkeys(result['rejected_checks'] + ['frame_history_required']))
    rotation = result['camera_yaw_change'] if dx else result['camera_pitch_change']
    return {**result, 'requested_dx': dx, 'requested_dy': dy,
            'valid': bool(result['success']),
            'degrees_per_delta': rotation/(dx or dy) if dx or dy else None,
            'yaw_before': before['yaw'], 'yaw_after': after['yaw'],
            'pitch_before': before['pitch'], 'pitch_after': after['pitch']}


def calibration_report(trials, complete=False, reason=None):
    axes = {}
    for axis, key in (('horizontal', 'requested_dx'), ('vertical', 'requested_dy')):
        selected = [t for t in trials if t['valid'] and t.get('controlled_trial_passed') and t[key]]
        factors = [t['degrees_per_delta'] for t in selected]
        mean = statistics.mean(factors) if factors else None
        deviation = statistics.pstdev(factors) if factors else None
        axes[axis] = {'valid_trials': len(selected), 'degrees_per_delta': mean,
                      'stddev': deviation, 'coefficient_of_variation': deviation/mean if mean else None,
                      'max_error_degrees': max((abs(t['camera_yaw_change' if axis == 'horizontal'
                          else 'camera_pitch_change']-t[key]*mean) for t in selected), default=None),
                      'positive_trials': sum(t[key] > 0 for t in selected),
                      'negative_trials': sum(t[key] < 0 for t in selected)}
    reliable = (complete and len(trials) == len(PLAN) and all(t['valid'] for t in trials) and
                all(a['positive_trials'] >= 3 and a['negative_trials'] >= 3 and
                    a['coefficient_of_variation'] <= .2 for a in axes.values()))
    return {'method': 'CGEventPostToPid', 'validator': 'quartz_matrix', 'complete': complete,
            'abort_reason': reason, 'valid_trials': sum(t['valid'] for t in trials),
            'required_trials': len(PLAN), 'total_trials': len(trials), 'axes': axes,
            'reliable': reliable, 'trials': trials, 'head_lock_enabled': False,
            'independently_verified': False,
            'limitation': 'Camera gain is measured; physical-input provenance is not conclusively established.'}


def format_calibration_report(report):
    def factor(axis):
        a = report['axes'][axis]
        value = a['degrees_per_delta']
        return f"{value:.6f} deg/delta ({a['valid_trials']}/6 valid)" if value is not None else 'pending'
    return (f"Camera Calibration | CGEventPostToPid\n"
            f"Valid trials: {report['valid_trials']}/{report['required_trials']}\n"
            f"Horizontal: {factor('horizontal')}\nVertical: {factor('vertical')}\n"
            f"Reliability: {'RELIABLE' if report['reliable'] else 'NOT VERIFIED'}\n"
            f"Reason: {report['abort_reason'] or ('completed' if report['complete'] else 'in progress')}\n"
            "Head Lock disabled. Full frame evidence is saved in the calibration JSONL/report.")


class CalibrationExperiment(MatrixExperiment):
    """Adds a trial plan and gain statistics to the proven matrix engine."""
    def __init__(self, backend, log, initial_key=False, clock=time.perf_counter, reception=None):
        self.trials = []
        self.done = False
        self.report = None
        self.last_physical_key = initial_key
        super().__init__(backend, log, {}, 'zero', clock=clock, reception=reception,
                         require_frame_history=True)

    def finish(self, reason=None):
        if self.done:
            return
        self.cancel(reason or 'complete')
        self.done = True
        self.report = calibration_report(self.trials, reason is None, reason)
        self.log.write({'event': 'calibration_report', **self.report})

    def assess_response(self, before, after, method):
        key = 'requested_dx' if self.delta[0] else 'requested_dy'
        prior = [t['degrees_per_delta'] for t in self.trials if t['valid'] and t[key]]
        result = measurement(before, after, *self.requested_delta(method),
                             expected_gain=statistics.mean(prior) if prior else None)
        result['matrix_case'] = self.case
        if result.get('total_magnitude', {}).get('valid') is False:
            result['rejected_checks'].append('calibration_gain_inconsistent_over_20_percent')
        return result

    def tick(self, state, received, key=False, stop=False):
        if self.done:
            return
        if not self.backend.trusted():
            self.finish('accessibility_permission_denied')
            return
        fingerprint = tuple(state.get(k) for k in ('sensitivity', 'fov', 'aspect')) if state else None
        if state and state.get('gameplay'):
            if not hasattr(self, 'fingerprint'):
                self.fingerprint = fingerprint
            elif fingerprint != self.fingerprint:
                self.finish('camera_settings_changed')
                return
        # A held F6 must not become a fresh edge when the direction changes.
        edge = key and not self.last_physical_key
        self.last_physical_key = key
        action = 'pid' if any(self.delta) else 'zero'
        previous = self.last_result
        running = super().tick(state, received, {action: edge}, emergency=stop,
                               hotkeys={'F6': key, 'F8': stop})
        if self.last_result is not previous:
            result = dict(self.last_result)
            result['valid'] = bool(result['controlled_trial_passed'])
            if not result['pre_window']['quiet']:
                result.setdefault('rejected_checks', []).append('pre_window_not_quiet')
            if not result['post_window']['quiet']:
                result.setdefault('rejected_checks', []).append('post_window_not_quiet')
            self.trials.append(result)
            self.log.write({'event': 'trial_result', 'trial': len(self.trials), **result})
            if not result['valid']:
                self.finish('; '.join(result.get('rejected_checks', [])) or result['outcome'])
                return
            if len(self.trials) == len(PLAN):
                self.finish()
                return
            self.delta = PLAN[len(self.trials)]
            self.case = next(name for name, delta in CASES.items() if delta == self.delta)
        if not running:
            self.finish(self.stop_reason or 'matrix_stopped')

    def progress_text(self):
        report = self.report or calibration_report(self.trials)
        h = report['axes']['horizontal']['degrees_per_delta']
        v = report['axes']['vertical']['degrees_per_delta']
        factors = f"H: {h:.5f}" if h is not None else 'H: pending'
        factors += f" | V: {v:.5f}" if v is not None else ' | V: pending'
        reason = report['abort_reason']
        if not self.done:
            failures = (self.last_preconditions or {}).get('rejected_preconditions', [])
            reason = '; '.join(failures) or ('observing' if self.pending else 'F6: one trial; F8: stop')
        reliability = 'RELIABLE' if report['reliable'] else 'NOT VERIFIED' if self.done else 'PENDING'
        return (f"{self.case} | Valid {report['valid_trials']}/{len(PLAN)} | {self.control_state}\n"
                f"{factors} deg/delta | {reliability}\n{reason or 'complete'}")


class CalibrationBackend(MacMouseBackend):
    def __init__(self, pid, window_id, controller, log):
        self.controller, self.log = controller, log
        super().__init__(pid, window_id)

    def validate_destination(self):
        return resolve_destination(self.window_id, self.pid, self.destination_executable, EXPECTED_APP)

    def trusted(self):
        return accessibility_trusted()  # Actual AXIsProcessTrusted, never a cached grant.

    def key(self):
        return bool(self.q.CGEventSourceKeyState(self.q.kCGEventSourceStateHIDSystemState, 97))

    def focus_snapshot(self):
        # Cocoa is serviced by Tk's main thread, not this calibration worker.
        focus = dict(self.controller.foreground_snapshot)
        age = time.perf_counter()-focus.get('foreground_checked_monotonic', -float('inf'))
        if not 0 <= age < .2:
            focus['foreground_pid'] = None
            focus['foreground_query'] = 'main_thread_observation_stale'
        return {**focus, 'game_focused': focus.get('foreground_pid') == self.pid,
                'source_pid': os.getpid(), 'posting_thread': threading.current_thread().name}

    def snapshot(self):
        return {**self.focus_snapshot(), 'accessibility_trusted': self.trusted()}

    def focused(self):
        return self.focus_snapshot()['game_focused']

    def before_dispatch(self):
        """Optional stricter consumer gate immediately before the native helper."""

    def post(self, method):
        with self.controller.post_lock:
            if self.controller.stop_event.is_set() or self.emergency():
                raise EmergencyStop('cancelled_or_emergency_stop')
            experiment = self.controller.experiment
            state, received = experiment.latest_input
            destination = self.validate_destination()
            check = precondition_snapshot(self, state, received, time.perf_counter(),
                                          reception=experiment.reception, require_frame_history=True)
            self.log.write({'event': 'native_precondition_check', **destination, **check})
            if check['rejected_preconditions']:
                raise PreconditionChanged('; '.join(check['rejected_preconditions']))
            delta = experiment.delta
            if method != 'pid' or delta not in PLAN or not any(delta):
                raise ValueError('Only explicit fixed PID calibration pulses allowed')
            if self.controller.stop_event.is_set() or self.emergency():
                raise EmergencyStop('cancelled_or_emergency_stop')
            self.before_dispatch()
            native = post_relative_pulse(self.q, 'pid', self.pid, *delta)
            return {**destination, **native, **self.snapshot()}


class CameraCalibration:
    """Worker owns calibration; Tk's after loop supplies fresh foreground state."""
    def __init__(self):
        self.stop_event = threading.Event()
        self.post_lock = threading.RLock()
        self.thread = None
        self.experiment = None
        self.foreground_query = None
        self.foreground_snapshot = {}
        self.status = 'Calibration idle'
        self.report = None
        self.report_path = None

    def refresh_foreground(self):
        if self.foreground_query is None:
            self.foreground_query = ForegroundQuery()
        self.foreground_snapshot = self.foreground_query.snapshot()

    def stop(self):
        with self.post_lock:
            self.stop_event.set()

    def start(self, window_id):
        if self.thread and self.thread.is_alive():
            return False
        self.refresh_foreground()  # Called from Tk's button handler.
        self.stop_event.clear()
        self.report = self.report_path = None
        self.status = 'Waiting for Test3 gameplay. F6: one trial; F8: stop.'
        self.thread = threading.Thread(target=self.run, args=(window_id,), daemon=True)
        self.thread.start()
        return True

    def run(self, window_id):
        log = receiver = experiment = None
        try:
            destination = resolve_destination(window_id, expected_app=EXPECTED_APP)
            log = CorrectionLog(Path.home()/'Library/Logs/AI-Aim-Trainer/camera_calibration')
            backend = CalibrationBackend(destination['resolved_owner_pid'], window_id, self, log)
            log.write({'event': 'calibration_startup', **destination, **backend.snapshot(),
                       'telemetry_port': 8767, 'head_lock_enabled': False})
            receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            receiver.bind(('127.0.0.1', 8767))
            receiver.setblocking(False)
            reception = TelemetryReception()
            experiment = self.experiment = CalibrationExperiment(backend, log, backend.key(), reception=reception)
            state, received = None, 0
            while not experiment.done:
                for _ in range(32):
                    try:
                        data, address = receiver.recvfrom(65535)
                    except BlockingIOError:
                        break
                    if address[0] == '127.0.0.1':
                        candidate = reception.decode(data, backend.pid, time.perf_counter())
                        if candidate is not None:
                            state, received = candidate, reception.last_state_received_at
                experiment.tick(state, received, backend.key(), self.stop_event.is_set())
                self.status = experiment.progress_text()
                time.sleep(.01)
            self.report = experiment.report
        except Exception as error:
            if experiment:
                experiment.finish(f'{type(error).__name__}: {error}')
                self.report = experiment.report
            else:
                self.report = calibration_report([], reason=f'{type(error).__name__}: {error}')
            self.status = f'Calibration stopped: {self.report["abort_reason"]}'
        finally:
            if log and self.report:
                self.report_path = log.path.with_suffix('.report.json')
                self.report_path.write_text(json.dumps(self.report, indent=2, allow_nan=False), encoding='utf-8')
                print(f'[calibration] reliable={self.report["reliable"]} report={self.report_path}', flush=True)
            if receiver:
                receiver.close()
            if log:
                log.close()
