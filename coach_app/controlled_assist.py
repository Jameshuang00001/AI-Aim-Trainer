"""Phase 2: opt-in, time-bounded correction in our verified Test3 game only.

Dry-run never posts. Live requires a matching reliable calibration, a successful
live-game dry-run, a separate UI confirmation, Start, and physical RMB. No firing.
"""
from collections import deque
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import queue
import socket
import threading
import time
from types import SimpleNamespace

from .aimbot import HeadTracker, center
from .camera_calibration import (CalibrationBackend, CameraCalibration, EXPECTED_APP,
                                 PLAN, calibration_report, measurement)
from .quartz_matrix import MatrixExperiment, TelemetryReception, CASES, precondition_snapshot
from .quartz_delivery_test import assess
from .audit_destination import resolve_destination
from .telemetry import CorrectionLog
from .runtime_paths import project_root


@dataclass(frozen=True)
class Limits:
    deadzone: float = 8.
    gain: float = .15
    counts_per_second: float = 8.
    acceleration: float = 16.
    max_corrections: int = 5
    hold_seconds: float = 10.
    detection_age: float = .35

    def __post_init__(self):
        if not (4 <= self.deadzone <= 32 and 0 < self.gain <= .15 and
                0 < self.counts_per_second <= 8 and 0 < self.acceleration <= 16 and
                1 <= self.max_corrections <= 5 and 0 < self.hold_seconds <= 10 and
                0 < self.detection_age <= .35):
            raise ValueError('Phase 2 safety limits exceeded')


def load_calibration(directory=None, explicit=None):
    directory = Path(directory or Path.home()/'Library/Logs/AI-Aim-Trainer/camera_calibration')
    paths = [Path(explicit)] if explicit else sorted(directory.glob('*.report.json'),
                                                    key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            raw = path.read_bytes()
            report = json.loads(raw)
            if (report.get('method') != 'CGEventPostToPid' or report.get('validator') != 'quartz_matrix' or report.get('reliable') is not True or
                    report.get('complete') is not True or report.get('valid_trials') != 15 or
                    len(report.get('trials', [])) != 15):
                continue
            if [(t.get('requested_dx'), t.get('requested_dy')) for t in report['trials']] != PLAN:
                continue
            # Recompute reliability rather than trusting just the saved label.
            recomputed = calibration_report(report['trials'], complete=True)
            if not recomputed['reliable']:
                continue
            for trial in report['trials']:
                if trial.get('requested_dx') or trial.get('requested_dy'):
                    if trial.get('mouse_frame_evidence', {}).get('consistent') is not True:
                        raise ValueError('Missing calibrated input-frame evidence')
            log_path = path.with_name(path.name.replace('.report.json', '.jsonl'))
            target = fingerprint = None
            with log_path.open() as source:
                for line in source:
                    row = json.loads(line)
                    if row.get('event') == 'calibration_startup':
                        target = {k: row.get(k) for k in ('resolved_owner_pid', 'game_executable', 'selected_window_id')}
                    if row.get('event') == 'posted':
                        s = row['baseline_state']
                        fp = tuple(s[k] for k in ('sensitivity', 'fov', 'aspect'))
                        if fingerprint is not None and fp != fingerprint:
                            raise ValueError('Calibration settings changed')
                        fingerprint = fp
            if not target or not fingerprint or Path(target['game_executable']).parents[2].name != EXPECTED_APP:
                continue
            gains = tuple(recomputed['axes'][a]['degrees_per_delta'] for a in ('horizontal', 'vertical'))
            if not all(type(g) in (int, float) and math.isfinite(g) and .0025 < g < 1.5 for g in gains):
                continue
            return {'path': str(path), 'digest': hashlib.sha256(raw).hexdigest(),
                    'target': target, 'fingerprint': fingerprint, 'gains': gains}
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            continue
    raise RuntimeError('No complete RELIABLE matrix calibration with paired Unity evidence. Calibrate Camera first.')


def assist_crop():
    for path in (project_root()/'yolo_dev/capture_region.assist.json',
                 Path.home()/'Library/Application Support/AI-Aim-Trainer/capture_region.assist.json'):
        if path.is_file(): return path, hashlib.sha256(path.read_bytes()).hexdigest()
    return None, None


def plan_step(dx, dy, width, height, fov, aspect, gains, limits):
    if not all(math.isfinite(v) for v in (dx, dy, width, height, fov, aspect, *gains)):
        raise ValueError('Invalid projection values')
    if width <= 0 or height <= 0 or not 1 < fov < 179 or min(gains) <= 0 or aspect <= 0:
        raise ValueError('Invalid camera projection')
    if abs(width/height/aspect-1) > .01:
        raise ValueError('Capture aspect differs from gameplay camera; verify full-window ROI')
    if math.hypot(dx, dy) <= limits.deadzone:
        return (0, 0)
    fy = height/(2*math.tan(math.radians(fov/2)))
    fx = width/(2*math.tan(math.radians(fov/2))*aspect)
    angles = (math.degrees(math.atan(dx/fx)), math.degrees(math.atan2(dy/fy, math.sqrt(1+(dx/fx)**2))))
    axis = max(range(2), key=lambda i: abs(angles[i]/gains[i]))
    # Only the single-axis +/-2 pulses calibrated in Phase 1 are permitted.
    # Do not round a fractional request into an overshooting pulse.
    if abs(angles[axis]) <= 2*gains[axis] or abs(angles[axis])*limits.gain < gains[axis]:
        return (0, 0)
    return (2 if angles[0] > 0 else -2, 0) if axis == 0 else (0, 2 if angles[1] > 0 else -2)


class MotionBudget:
    def __init__(self, limits):
        self.limits = limits
        self.reset()

    def reset(self):
        self.last = None
        self.speed = self.credit = 0.
        self.events = deque()

    def ready(self, now):
        dt = min(.1, max(0., now-self.last)) if self.last is not None else 0.
        self.last = now
        self.speed = min(self.limits.counts_per_second, self.speed+self.limits.acceleration*dt)
        self.credit = min(2., self.credit+self.speed*dt)
        while self.events and now-self.events[0] >= 1.: self.events.popleft()
        return self.credit >= 2 and len(self.events)*2+2 <= self.limits.counts_per_second

    def consume(self, now):
        self.credit -= 2
        self.events.append(now)


class ResponseExperiment(MatrixExperiment):
    def __init__(self, backend, log, calibration, reception, clock):
        self.calibration = calibration
        super().__init__(backend, log, {}, 'horizontal-positive', clock=clock,
                         reception=reception, require_frame_history=True)
        self.wait_reason = None

    def wait_for_game(self, reason, keys):
        self.wait_reason = reason
        return super().wait_for_game(reason, keys)

    def assess_response(self, before, after, method):
        result = measurement(before, after, *self.requested_delta(method))
        if method == 'pid' and result['success']:
            axis = 0 if self.delta[0] else 1
            expected = self.delta[axis]*self.calibration['gains'][axis]
            observed = result['camera_yaw_change' if axis == 0 else 'camera_pitch_change']
            if abs(observed/expected-1) > .2:
                result['success'] = False
                result['rejected_checks'].append('response_differs_from_calibration_over_20_percent')
                result['outcome'] = 'unexpected_or_inconsistent_response'
        return result


class ControlledLoop:
    """Deterministic control policy; tests supply detections, telemetry and backend."""
    def __init__(self, backend, log, calibration, reception, dry_run=True, limits=None, clock=time.perf_counter,
                 wall_clock=time.time):
        self.backend, self.log, self.calibration, self.clock = backend, log, calibration, clock
        self.wall_clock = wall_clock
        self.dry_run, self.limits = dry_run, limits or Limits()
        self.core = ResponseExperiment(backend, log, calibration, reception, clock)
        self.tracker = HeadTracker()
        self.budget = MotionBudget(self.limits)
        self.normal = self.diagnostic = None
        self.normal_at = self.diagnostic_at = 0.
        self.done = self.ever_ready = self.was_held = False
        self.reason = 'waiting_for_gameplay'
        self.selected = self.capture_size = None
        self.capture_at = 0.
        self.require_capture_after = 0.
        self.hold_started = None
        self.count = self.proposals = 0
        self.last_proposal = -math.inf
        self.actual = (0, 0)
        self.observed = None
        self.dry_passed = False
        self.feedback_capture_pending = False
        self.acquired = False

    def stop(self, reason):
        if not self.done:
            self.core.cancel(reason)
            self.log.write({'event': 'safety_interruption', 'reason': reason,
                            'dry_run': self.dry_run, 'corrections': self.count})
        self.done, self.reason = True, reason

    def gates(self, now):
        check = precondition_snapshot(self.backend, self.diagnostic, self.diagnostic_at, now,
                                      reception=self.core.reception, require_frame_history=True)
        failures = list(check['rejected_preconditions'])
        s = self.normal
        if s is None or s.get('pid') != self.backend.pid or not 0 <= now-self.normal_at < .2:
            failures.append('coach_state_missing_or_stale')
        else:
            for key, expected in (('gameplay', True), ('application_focused', True), ('cursor_locked', True),
                    ('session_active', True), ('gameplay_input_enabled', True), ('paused', False),
                    ('settings_open', False), ('settings_panel_visible', False), ('summary_open', False),
                    ('summary_panel_visible', False), ('start_menu_visible', False)):
                if s.get(key) is not expected: failures.append('coach_state_' + key)
            if tuple(s.get(k) for k in ('sensitivity', 'fov', 'aspect')) != tuple(self.calibration['fingerprint']):
                failures.append('coach_camera_settings_differ_from_calibration')
        if self.diagnostic:
            fp = tuple(self.diagnostic.get(k) for k in ('sensitivity', 'fov', 'aspect'))
            if fp != tuple(self.calibration['fingerprint']): failures.append('camera_settings_differ_from_calibration')
        for name, snapshot in (('coach', self.normal), ('diagnostic', self.diagnostic)):
            scale = snapshot.get('time_scale') if snapshot else None
            if type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
                failures.append(name + '_time_scale_missing_or_paused')
            # A freshly read packet may have sat in the OS queue. Arrival time
            # alone is not evidence of a fresh Unity observation on this host.
            try:
                stamp = datetime.fromisoformat(snapshot['sent_at_utc'].replace('Z', '+00:00'))
                if stamp.tzinfo is None or not 0 <= self.wall_clock()-stamp.timestamp() < .2:
                    failures.append(name + '_source_timestamp_stale')
            except (TypeError, KeyError, ValueError, AttributeError):
                failures.append(name + '_source_timestamp_missing_or_invalid')
        target = self.calibration['target']
        if target['resolved_owner_pid'] != self.backend.pid: failures.append('calibration_pid_changed_recalibrate')
        return failures

    def update(self, normal, normal_at, diagnostic, diagnostic_at, detection=None):
        if self.done: return
        now = self.clock()
        self.normal, self.normal_at = normal, normal_at
        self.diagnostic, self.diagnostic_at = diagnostic, diagnostic_at
        if self.backend.emergency() or any(s and s.get('emergency') is True for s in (normal, diagnostic)):
            self.stop('emergency_F8_or_ESC'); return
        failures = self.gates(now)
        if failures:
            if self.ever_ready or any('destination_validation_failed' in f or 'calibration_pid' in f or
                                     'settings_differ_from_calibration' in f for f in failures):
                self.stop('; '.join(failures))
            else: self.reason = '; '.join(failures)
            return
        previous = self.core.last_result
        held = normal.get('held') is True and diagnostic.get('held') is True and self.backend.held()
        if not held:
            if self.was_held:
                if self.core.pending:
                    self.stop('RMB_released_during_feedback_unverified'); return
                self.core.wait_for_game('RMB_released', {})
                self.log.write({'event': 'RMB_released', 'pending_cancelled': True})
            self.was_held = False
            self.tracker.reset(); self.selected = None; self.budget.reset(); self.hold_started = None
            self.acquired = False
            self.reason = 'Hold RMB in active gameplay'
        elif self.selected and now-self.capture_at > self.limits.detection_age:
            self.stop('stale_detection'); return
        self.was_held = held
        if detection is not None:
            width, height, boxes, scores, captured = detection
            if not 0 <= now-captured <= self.limits.detection_age:
                if self.selected: self.stop('stale_detection')
                return
            if self.capture_size and self.capture_size != (width, height):
                self.stop('capture_dimensions_changed'); return
            self.capture_size = (width, height)
            if captured <= self.capture_at: return
            self.capture_at = captured
            if held:
                prior = self.selected
                selected = self.tracker.update(boxes, scores, width, height, now)
                if prior and selected is None:
                    self.log.write({'event': 'target_loss', 'target_id': prior[2]})
                    self.stop('target_lost_or_ambiguous'); return
                self.selected = selected if self.tracker.stable >= 3 else None
                if self.selected and self.hold_started is None: self.hold_started = now
                self.log.write({'event': 'detection', 'captured_at': captured,
                    'target_id': self.selected[2] if self.selected else None,
                    'bbox': self.selected[0] if self.selected else None,
                    'confidence': self.selected[1] if self.selected else None})
                if self.selected and self.feedback_capture_pending and captured > self.require_capture_after:
                    x, y = center(self.selected[0])
                    self.log.write({'event': 'post_correction_detection', 'target_id': self.selected[2],
                                    'dx': x-width/2, 'dy': y-height/2, 'captured_at': captured})
                    self.feedback_capture_pending = False
        if self.hold_started is not None and now-self.hold_started >= self.limits.hold_seconds:
            self.stop('ten_second_hold_limit'); return
        proposal = None
        if held and self.selected and not self.core.pending:
            box, confidence, identity = self.selected
            width, height = self.capture_size
            dx, dy = center(box)[0]-width/2, center(box)[1]-height/2
            step = plan_step(dx, dy, width, height, diagnostic['fov'], diagnostic['aspect'],
                             self.calibration['gains'], self.limits)
            self.reason = 'inside_deadzone' if math.hypot(dx, dy) <= self.limits.deadzone else 'waiting_for_quiet_observation'
            if step == (0, 0) and math.hypot(dx, dy) > self.limits.deadzone:
                self.reason = 'below_safe_quantized_step_no_overshoot'
            if math.hypot(dx, dy) <= self.limits.deadzone and not self.acquired:
                self.log.write({'event': 'acquisition_result', 'successfully_acquired': True,
                                'target_id': identity, 'acquisition_time_ms': (now-self.tracker.started)*1000,
                                'dry_run': self.dry_run})
                self.acquired = True
            if (step != (0, 0) and self.core.control_state == 'READY' and
                    self.capture_at > self.require_capture_after and self.budget.ready(now) and
                    now-self.last_proposal >= 1. and now-self.core.last_completed >= 1. and
                    len(self.core.history) >= 2 and now-self.core.history[0][0] >= .3 and
                    assess(self.core.history[0][1], diagnostic, 'zero')['quiet']):
                proposal = step
                self.core.delta = step
                self.core.case = next(name for name, delta in CASES.items() if delta == step)
                self.log.write({'event': 'proposal', 'dry_run': self.dry_run, 'dx': dx, 'dy': dy,
                    'delta': list(step), 'target_id': identity, 'confidence': confidence})
                if self.dry_run:
                    self.proposals += 1
                    self.last_proposal = now; self.budget.consume(now)
                    proposal = None
                    if self.proposals >= 3:
                        self.dry_passed = True
                        self.stop('dry_run_passed_no_input_sent'); return
        was_ready = self.core.control_state == 'READY'
        running = self.core.tick(diagnostic, diagnostic_at, {'pid': proposal is not None})
        if was_ready and self.core.control_state != 'READY' and held:
            self.stop(self.core.wait_reason or 'native_safety_state_changed'); return
        if self.core.control_state == 'READY': self.ever_ready = True
        if proposal and self.core.pending:
            self.count += 1
            self.actual = proposal
            self.observed = None
            self.last_proposal = now; self.budget.consume(now)
            self.log.write({'event': 'correction', 'delta': list(proposal), 'correction_index': self.count,
                            'target_id': self.selected[2], 'confidence': self.selected[1],
                            'target_bbox': self.selected[0], 'correction_magnitude': math.hypot(*proposal),
                            'dx': center(self.selected[0])[0]-self.capture_size[0]/2,
                            'dy': center(self.selected[0])[1]-self.capture_size[1]/2,
                            'acquisition_time_ms': (now-self.tracker.started)*1000,
                            'capture_age_ms': (now-self.capture_at)*1000})
        if self.core.pending and now-self.core.pending['posted_at'] > 1.2:
            self.stop('camera_response_timeout'); return
        if self.core.last_result is not previous:
            result = self.core.last_result
            self.observed = (result['camera_yaw_change'], result['camera_pitch_change'])
            self.log.write({'event': 'observed_camera_response', **result})
            if not result['controlled_trial_passed']:
                self.stop('; '.join(result.get('rejected_checks', [])) or result['outcome']); return
            self.require_capture_after = now  # Must capture/detect AGAIN after feedback completes.
            self.feedback_capture_pending = True
            if self.count >= self.limits.max_corrections:
                self.stop('five_correction_burst_limit'); return
        if not running: self.stop(self.core.stop_reason or 'matrix_safety_stop')

    def text(self):
        head = 'Head: pending'
        if self.selected:
            x, y = center(self.selected[0]); w, h = self.capture_size
            head = f'Head {self.selected[1]:.2f} | dx {x-w/2:+.1f}, dy {y-h/2:+.1f} px'
        observed = (f'yaw {self.observed[0]:+.3f}, pitch {self.observed[1]:+.3f}' if self.observed is not None
                    else 'no input (dry run)' if self.dry_run else 'response pending')
        return (f"{'DRY RUN' if self.dry_run else 'LIVE'} | Calibrated H {self.calibration['gains'][0]:.5f}, "
                f"V {self.calibration['gains'][1]:.5f}\n{head}\n"
                f"Sent {self.actual} ({self.count}/5) | Observed {observed}\n{self.reason}")


class ControlledBackend(CalibrationBackend):
    def before_dispatch(self):
        if (self.controller.dry_run or not self.controller.live_run or self.controller.stop_event.is_set()
                or not self.held() or self.emergency()):
            raise RuntimeError('Live gate/RMB/emergency changed immediately before dispatch')

    def post(self, method):
        with self.controller.post_lock:
            loop = self.controller.loop
            if self.controller.dry_run or not self.controller.live_run or loop.dry_run:
                raise RuntimeError('Live correction not explicitly confirmed')
            if not self.held() or self.controller.stop_event.is_set() or self.emergency():
                raise RuntimeError('RMB released or emergency stop before dispatch')
            failures = loop.gates(time.perf_counter())
            if failures: raise RuntimeError('; '.join(failures))
            if not self.held(): raise RuntimeError('RMB released before dispatch')
            return super().post(method)


class ControlledAssistController(CameraCalibration):
    """One detector + one bounded control worker; no Nebius calls on either."""
    def __init__(self):
        super().__init__()
        self.lock = self.post_lock
        self.detector = None
        self.loop = None
        self.status, self.detail = 'OFF', 'Dry run is the default. Start explicitly; hold RMB.'
        self.dry_run = True
        self.live_run = self.live_authorized = False
        self.dry_proof = None
        self.log_path = None

    def snapshot(self):
        with self.lock: return self.status, self.detail

    def verify(self):
        try:
            c = load_calibration()
            self.detail = (f"Saved RELIABLE calibration: H {c['gains'][0]:.5f}, V {c['gains'][1]:.5f}. "
                           'Start also checks the current window/PID. No pulse sent.')
        except RuntimeError as error: self.detail = str(error)

    def stop(self):
        with self.lock:
            super().stop()
            self.live_run = self.live_authorized = False
            self.status, self.detail = 'OFF', 'Stopped; live confirmation cleared.'

    def confirm_live(self):
        with self.lock:
            if self.dry_proof is None: return False
            self.live_authorized = True
            return True

    def start(self, window_id=None, dry_run=True, deadzone=8.):
        with self.lock:
            if type(window_id) is not int or window_id <= 0:
                raise ValueError('Select the verified Test3 window')
            if any(w and w.is_alive() for w in (self.thread, self.detector)): return False
            if not dry_run and (not self.live_authorized or self.dry_proof is None):
                self.detail = 'Complete a live-game dry run and separately confirm live correction.'
                return False
            self.limits = Limits(deadzone=float(deadzone))
            self.dry_run, self.live_run = dry_run, not dry_run
            self.live_authorized = False
            self.stop_event = threading.Event()
            self.loop = None
            self.log_path = None
            self.status, self.detail = 'READY', 'Loading detector and checking calibration.'
            self.thread = threading.Thread(target=self.run, args=(window_id,), daemon=True)
            self.thread.start()
            return True

    def run(self, window_id):
        sockets = []
        log = None
        try:
            from yolo_dev import live_detect as live
            destination = resolve_destination(window_id, expected_app=EXPECTED_APP)
            calibration = load_calibration()
            if calibration['target'] != {k: destination[k] for k in calibration['target']}:
                raise RuntimeError('Calibration belongs to a different window/PID/executable. Recalibrate Test3.')
            proof_key = (calibration['digest'], destination['resolved_owner_pid'], window_id, self.limits.deadzone)
            crop, crop_digest = assist_crop()
            model_path = live.resolve_model()
            proof_key += (crop_digest, hashlib.sha256(model_path.read_bytes()).hexdigest())
            if not self.dry_run and self.dry_proof['key'] != proof_key:
                raise RuntimeError('Dry-run proof does not match this game/calibration/deadzone; repeat dry run.')
            backend = ControlledBackend(destination['resolved_owner_pid'], window_id, self, None)
            live.capture.check_permission()
            window = next(w for w in live.capture.unity_windows() if w['id'] == window_id and w['pid'] == backend.pid)
            log = CorrectionLog()
            self.log_path = log.path
            backend.log = log
            log.write({'event': 'controlled_assist_start', **destination, 'dry_run': self.dry_run,
                       'calibration_path': calibration['path'], 'limits': self.limits.__dict__})
            for port in (8766, 8767):
                receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sockets.append(receiver); receiver.bind(('127.0.0.1', port)); receiver.setblocking(False)
            normal_rx, diagnostic_rx = TelemetryReception(), TelemetryReception()
            loop = self.loop = ControlledLoop(backend, log, calibration, diagnostic_rx,
                                              self.dry_run, self.limits)
            self.experiment = loop.core
            messages = queue.Queue(maxsize=1)
            args = SimpleNamespace(model=model_path, config=None, imgsz=640, conf=.5, unity_app_name=None,
                                   assist_crop=crop, assist_crop_digest=crop_digest)
            self.detector = threading.Thread(target=live.worker, args=(args, window, messages, self.stop_event), daemon=True)
            self.detector.start()
            states, times = [None, None], [0., 0.]
            while not self.stop_event.wait(.01) and not loop.done:
                for i, (receiver, reception) in enumerate(zip(sockets, (normal_rx, diagnostic_rx))):
                    for _ in range(32):
                        try: data, address = receiver.recvfrom(65535)
                        except BlockingIOError: break
                        if address[0] == '127.0.0.1':
                            candidate = reception.decode(data, backend.pid, time.perf_counter())
                            if candidate is not None: states[i], times[i] = candidate, reception.last_state_received_at
                    if reception.last_packet_rejection:
                        loop.stop(reception.last_packet_rejection)
                detection = None
                try:
                    kind, payload = messages.get_nowait()
                    if kind == 'error': raise RuntimeError(payload)
                    if kind == 'frame':
                        h, w = payload[0].shape[:2]
                        if not self.dry_run and (w, h) != self.dry_proof['capture_size']:
                            raise RuntimeError('Capture dimensions differ from dry run; repeat dry run.')
                        detection = (w, h, payload[1], payload[2], payload[6])
                    elif loop.selected: loop.stop('capture_unavailable')
                except queue.Empty: pass
                loop.update(states[0], times[0], states[1], times[1], detection)
                with self.lock:
                    if not self.stop_event.is_set():
                        self.status = 'OFF' if loop.done else 'ACTIVE' if loop.core.pending else 'READY'
                        self.detail = loop.text()
                if loop.dry_passed: self.dry_proof = {'key': proof_key, 'capture_size': loop.capture_size}
            if not loop.done: loop.stop('Stop_button_or_shutdown')
        except Exception as error:
            if self.loop:
                self.loop.stop(f'{type(error).__name__}: {error}')
            elif log:
                log.write({'event': 'safety_interruption', 'reason': f'{type(error).__name__}: {error}'})
            with self.lock: self.status, self.detail = 'OFF', f'{type(error).__name__}: {error}'
            print('[controlled-assist] ' + self.detail, flush=True)
        finally:
            self.stop_event.set()
            with self.lock:
                self.live_run = False
                self.status = 'OFF'
            for receiver in sockets: receiver.close()
            if log: log.close()
