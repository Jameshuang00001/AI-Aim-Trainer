"""Isolated opt-in Quartz A/B pulses, never aiming or firing.

F4: stationary no-event control. F5: physical baseline. F6: one PID pulse. F7: one HID-tap
pulse. F8/ESC: emergency exit. No key held at launch can trigger a test.
"""
import argparse
from collections import deque
import json
import math
import os
from pathlib import Path
import socket
import time
import threading
import uuid

from .audit_destination import resolve_destination
from .macos_input import accessibility_trusted
from .telemetry import CorrectionLog
from .diagnostic_udp import DiagnosticAssembler

KEYS = {'zero': 118, 'physical': 96, 'pid': 97, 'hid': 98}  # macOS virtual F4/F5/F6/F7.
FIELDS = ('yaw', 'pitch', 'axis_sum_x', 'axis_sum_y', 'raw_sum_x', 'raw_sum_y')


def valid_state(state, pid):
    return (isinstance(state, dict) and state.get('pid') == pid and
            state.get('diagnostic_version') == 1 and
            type(state.get('gameplay')) is bool and type(state.get('emergency')) is bool and
            type(state.get('frame')) is int and type(state.get('axis_nonzero_frames')) is int and
            all(type(state.get(k)) in (int, float) and math.isfinite(state[k]) for k in FIELDS))


def angle_delta(after, before):
    return (after-before+180) % 360-180


def assess(before, after, method, direction=1):
    dx, dy = after['axis_sum_x']-before['axis_sum_x'], after['axis_sum_y']-before['axis_sum_y']
    yaw, pitch = angle_delta(after['yaw'], before['yaw']), angle_delta(after['pitch'], before['pitch'])
    nonzero = after['axis_nonzero_frames']-before['axis_nonzero_frames']
    if after['frame'] <= before['frame'] or nonzero < 0:
        raise RuntimeError('Unity restarted or frame/counter data is invalid; retry the test.')
    # Original camera verification bounds, not relaxed to make an injection pass.
    in_bounds = 0.005 < yaw*direction < 3 and 0.005 < pitch*direction < 3
    success = nonzero > 0 and (in_bounds if method != 'physical' else bool(yaw or pitch))
    quiet = (nonzero == 0 and dx == 0 and dy == 0 and
             after['raw_sum_x'] == before['raw_sum_x'] and after['raw_sum_y'] == before['raw_sum_y'] and
             abs(yaw) <= .005 and abs(pitch) <= .005)
    direction_matches = dx*direction > 0 and dy*direction < 0 and yaw*direction > 0 and pitch*direction > 0
    if method == 'zero':
        success = quiet
    outcome = ('observed_response' if success else 'no_unity_delta' if nonzero == 0 else
               'input_received_no_camera_rotation' if not (yaw or pitch) else 'response_outside_existing_bounds')
    if method == 'zero':
        outcome = 'quiet_control' if quiet else 'control_movement_detected'
    return {'unity_received_mouse_x': dx, 'unity_received_mouse_y': dy,
            'unity_raw_mouse_x': after['raw_sum_x']-before['raw_sum_x'],
            'unity_raw_mouse_y': after['raw_sum_y']-before['raw_sum_y'],
            'unity_nonzero_mouse_frames': nonzero, 'camera_yaw_change': yaw,
            'camera_pitch_change': pitch, 'response_in_existing_bounds': in_bounds,
            'quiet':quiet, 'direction_matches':direction_matches,
            'success': success, 'outcome': outcome,
            'independently_verified': False, 'head_lock_enabled': False,
            'provenance_warning': 'Physical mouse movement can contaminate results; response is not source attribution.'}


def post_relative_pulse(q, method, pid, dx, dy):
    """Shared event construction for both diagnostics; native return is not acceptance."""
    if method not in ('pid', 'hid'):
        raise ValueError('Only explicit PID/HID tests may post an event')
    if (type(pid) is not int or pid <= 0 or type(dx) is not int or type(dy) is not int or
            (dx, dy) not in ((2, 2), (-2, -2), (2, 0), (-2, 0), (0, 2), (0, -2))):
        raise ValueError('Only fixed bounded diagnostic pulses and a valid PID are allowed')
    # Same construction for both methods: no absolute displacement/warping,
    # no clicks, no drag changes, no event-source spoofing.
    location = q.CGEventGetLocation(q.CGEventCreate(None))
    event = q.CGEventCreateMouseEvent(None, q.kCGEventMouseMoved, location, q.kCGMouseButtonRight)
    if event is None:
        raise RuntimeError('Cannot create Quartz diagnostic event')
    q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaX, dx)
    q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaY, dy)
    record = {'delivery_method': 'CGEventPostToPid' if method == 'pid' else 'CGEventPost(kCGHIDEventTap)',
              'destination_pid_argument': pid if method == 'pid' else None,
              'requested_dx': dx, 'requested_dy': dy,
              'event_type': int(q.CGEventGetType(event)),
              'event_timestamp_ns': int(q.CGEventGetTimestamp(event)),
              'event_dx': int(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaX)),
              'event_dy': int(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaY)),
              'event_location': [float(location.x), float(location.y)],
              'post_start_monotonic': time.perf_counter()}
    if method == 'pid':
        q.CGEventPostToPid(pid, event)
    else:
        q.CGEventPost(q.kCGHIDEventTap, event)
    return {**record, 'post_end_monotonic': time.perf_counter(), 'post_call_returned': True,
            'input_events_posted': True, 'unity_acceptance_confirmed': False}


def post_pulse(q, method, pid, direction=1):
    if type(direction) is not int or direction not in (-1,1):
        raise ValueError('Direction must be exactly +1 or -1; magnitude is fixed')
    return post_relative_pulse(q, method, pid, 2*direction, 2*direction)


class Experiment:
    """Small state machine; unit tests substitute input and telemetry entirely."""
    def __init__(self, backend, log, initial_keys, clock=time.perf_counter, direction=1):
        if type(direction) is not int or direction not in (-1,1):
            raise ValueError('Only bounded forward/reverse trials are supported')
        self.direction = direction
        self.backend, self.log, self.clock = backend, log, clock
        self.context = backend.validate_destination()
        self.previous = dict(initial_keys)
        self.history = deque()
        self.pending = None
        self.last_completed = -math.inf
        self.last_result = None

    def requested_delta(self, method):
        return (2*self.direction, 2*self.direction) if method in ('pid', 'hid') else (0, 0)

    def assess_response(self, before, after, method):
        return assess(before, after, method, self.direction)

    def reject(self, method, reason):
        self.log.write({**self.context, 'event':'rejected', 'method':method, 'success':False,
                        'outcome':reason, 'posted_dx':0, 'posted_dy':0, 'input_events_posted':False,
                        'unity_received_mouse_x':None, 'unity_received_mouse_y':None,
                        'camera_yaw_change':None, 'camera_pitch_change':None,
                        'head_lock_enabled':False, 'independently_verified':False})

    def cancel(self, reason):
        if self.pending:
            self.log.write({**self.pending['record'], 'event': 'result', 'success': False,
                            'outcome': reason, 'independently_verified': False,
                            'unity_received_mouse_x': None, 'unity_received_mouse_y': None,
                            'camera_yaw_change': None, 'camera_pitch_change': None})
        self.pending = None

    def log_sample(self, timestamp, state):
        pending = self.pending
        if pending is None or state['frame'] == pending.get('last_logged_frame'):
            return
        relative = timestamp-pending['posted_at']
        self.log.write({'event':'sample', 'record_schema':2, 'test_id':pending['record']['test_id'],
                        'method':pending['method'], 'receive_monotonic':timestamp,
                        'relative_ms':relative*1000,
                        'phase':'pre' if relative <= 0 else 'pulse' if pending.get('pulse_after') is None else 'post',
                        'state':dict(state)})
        pending['last_logged_frame'] = state['frame']

    def tick(self, state, received_at, keys, emergency=False):
        now = self.clock()
        edges = [method for method in KEYS if keys.get(method, False) and not self.previous.get(method, False)]
        self.previous = dict(keys)  # Edges are consumed even if focus/safety is invalid.
        if emergency or state and state.get('emergency') and now-received_at < .2:
            self.cancel('emergency_stop')
            return False
        safe = (state is not None and now-received_at < .2 and state['gameplay'] and self.backend.focused())
        if not safe:
            self.cancel('focus_or_telemetry_lost')
            self.history.clear()
            if edges:
                for method in edges:
                    self.reject(method,'focus_or_telemetry_missing')
                print('Test rejected: game focus or fresh diagnostic telemetry is missing. Press again after fixing it.', flush=True)
            return True
        if not self.history or self.history[-1][1]['frame'] != state['frame']:
            self.history.append((received_at, dict(state)))
        while self.history and now-self.history[0][0] > .6:
            self.history.popleft()
        if self.pending:
            self.log_sample(received_at,state)
            if self.pending.get('pulse_after') is None and received_at-self.pending['posted_at'] >= .4:
                self.pending['pulse_after'] = dict(state)
                self.pending['pulse_received'] = received_at
            if self.pending.get('pulse_after') is not None and received_at-self.pending['pulse_received'] >= .4:
                try:
                    self.backend.validate_destination()
                    result = self.assess_response(self.pending['before'], self.pending['pulse_after'], self.pending['method'])
                    post = assess(self.pending['pulse_after'],state,'zero')
                    controlled = (self.pending['pre']['quiet'] and post['quiet'] and result['success'] and
                                  (self.pending['method'] not in ('pid','hid') or result['direction_matches']))
                    result.update(pre_window=self.pending['pre'], pulse_window=dict(result), post_window=post,
                        controlled_trial_passed=controlled,
                        pulse_observation_ms=(self.pending['pulse_received']-self.pending['posted_at'])*1000,
                        post_observation_ms=(received_at-self.pending['pulse_received'])*1000)
                    self.log.write({**self.pending['record'], 'event':'result', **result})
                    self.last_result = result
                    print(f"{self.pending['method']} result: {result}", flush=True)
                except RuntimeError as error:
                    self.cancel(str(error))
                self.pending = None
                self.last_completed = now
                self.history.clear()
            return True
        if len(edges) != 1 or now-self.last_completed < 1:
            return True
        method = edges[0]
        if len(self.history) < 2 or now-self.history[0][0] < .3:
            self.reject(method,'insufficient_focused_baseline')
            print('Not ready: wait for fresh, focused Unity telemetry and press again.', flush=True)
            return True
        baseline = self.history[0][1]
        if method != 'physical' and not assess(baseline,state,'zero')['quiet']:
            self.reject(method,'physical_movement_in_baseline')
            print('Not ready: keep the physical mouse still for at least 0.3 seconds, then press again.', flush=True)
            return True
        destination = self.backend.validate_destination()
        dx, dy = self.requested_delta(method)
        # Recheck AX, F8 and foreground immediately before the single post.
        trusted, emergency, focused = self.backend.trusted(), self.backend.emergency(), self.backend.focused()
        if not trusted or emergency or not focused:
            self.reject(method,'emergency_stop' if emergency else 'last_moment_safety_gate_failed')
            return False
        record = {'test_id':uuid.uuid4().hex, 'method':method, **destination,
                  'record_schema':2, 'direction':self.direction,
                  'delivery_method': {'pid':'CGEventPostToPid', 'hid':'CGEventPost(kCGHIDEventTap)',
                                      'physical':'physical baseline; no synthetic event', 'zero':'stationary no-event control'}[method],
                  'destination_pid_argument': self.backend.pid if method == 'pid' else None,
                  'CGEventPostToPid_destination_pid':self.backend.pid if method == 'pid' else None,
                  'requested_dx':dx,
                  'requested_dy':dy,
                  'posted_dx':0, 'posted_dy':0,
                  'event_type':'kCGEventMouseMoved' if method in ('pid','hid') else None,
                  'right_mouse_held':state.get('held'),
                  'head_lock_enabled':False}
        self.log.write({**record, 'event':'activated'})
        post_start = self.clock()
        if method in ('pid','hid'):
            try:
                native_record = self.backend.post(method)
                if isinstance(native_record, dict):
                    record.update(native_record)
            except Exception:
                self.log.write({**record, 'event':'result', 'success':False, 'outcome':'post_error',
                                'input_events_posted':None, 'independently_verified':False,
                                'unity_received_mouse_x':None, 'unity_received_mouse_y':None,
                                'camera_yaw_change':None, 'camera_pitch_change':None})
                raise
            record.update(posted_dx=dx, posted_dy=dy, input_events_posted=True)
        post_end = self.clock()
        record.update(post_start_monotonic=post_start,post_end_monotonic=post_end,
                      baseline_receive_monotonic=received_at,baseline_state=dict(state))
        self.log.write({**record, 'event':'posted' if method in ('pid','hid') else 'baseline_started'})
        self.pending = {'record':record, 'method':method, 'before':dict(state), 'posted_at':post_end,
                        'pre':assess(baseline,state,'zero')}
        for timestamp, old_state in self.history:
            self.log_sample(timestamp,old_state)
        action = 'one bounded pulse' if method in ('pid','hid') else 'no synthetic event'
        print(f'{method} activated: {action}. Keep still through the pulse and post windows.', flush=True)
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-id', type=int, required=True)
    parser.add_argument('--expect-app', default='AI-Aim-Trainer-Test.app')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--direction', choices=('positive','negative'), default='positive',
                        help='Fixed +2/+2 or -2/-2 pulse; each pulse still requires a fresh key press')
    args = parser.parse_args()
    import Quartz as q
    import AppKit
    if not accessibility_trusted():
        parser.error('Accessibility denied for this diagnostic process. No events sent. Grant access manually and restart.')
    destination = resolve_destination(args.window_id, expected_app=args.expect_app)
    pid, executable = destination['resolved_owner_pid'], destination['game_executable']
    class Backend:
        def __init__(self): self.pid = pid
        def trusted(self): return accessibility_trusted()
        def focused(self):
            app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            return app is not None and int(app.processIdentifier()) == pid
        def emergency(self):
            return any(q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, k) for k in (100,53))
        def validate_destination(self):
            return resolve_destination(args.window_id, pid, executable, args.expect_app)
        def post(self, method):
            # Final native safety check; HID posting is global, not PID-addressed.
            self.validate_destination()
            trusted = self.trusted()
            if not trusted or not self.focused() or self.emergency():
                raise RuntimeError('Safety gate changed before posting; no event sent.')
            app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
            foreground_pid = int(app.processIdentifier()) if app is not None else None
            if foreground_pid != pid:
                raise RuntimeError('Foreground PID changed before posting; no event sent.')
            native = post_pulse(q, method, pid, 1 if args.direction=='positive' else -1)
            return {**native, 'foreground_pid': foreground_pid, 'game_focused': True,
                    'accessibility_trusted': trusted, 'coach_pid': os.getpid(),
                    'posting_thread': threading.current_thread().name}
    def keys():
        return {name:bool(q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState,key)) for name,key in KEYS.items()}
    receiver = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:
        receiver.bind(('127.0.0.1',args.port))
        receiver.setblocking(False)
        log = CorrectionLog(Path.home()/'Library/Logs/AI-Aim-Trainer/quartz_diagnostics')
        print(f'No events on launch. F4 zero control; F5 physical; F6 PID; F7 HID; F8/ESC stop.\nLog: {log.path}', flush=True)
        print('HID-tap posting is global: focus/lock the game, keep the physical mouse still. Head Lock stays disabled.', flush=True)
        print('Requires rebuilt Unity AssistStatePublisher with Publish Quartz Diagnostics enabled (port 8767).', flush=True)
        experiment = Experiment(Backend(),log,keys(),direction=1 if args.direction=='positive' else -1)
        state, received = None, 0
        assembler = DiagnosticAssembler()
        try:
            while True:
                for _ in range(32):
                    try: data,address = receiver.recvfrom(65535)
                    except BlockingIOError: break
                    if address[0] != '127.0.0.1': continue
                    try: candidate = assembler.feed(data, pid, time.perf_counter())
                    except (ValueError,UnicodeError): continue
                    if address[0]=='127.0.0.1' and valid_state(candidate,pid):
                        state,received = candidate,assembler.received_at
                if not experiment.tick(state,received,keys(),experiment.backend.emergency()): break
                time.sleep(.01)
        except KeyboardInterrupt:
            experiment.cancel('ctrl_c')
        except Exception:
            experiment.cancel('diagnostic_error')
            raise
        finally: log.close()
    finally: receiver.close()


if __name__ == '__main__':
    main()
