"""Opt-in, one-pulse Quartz provenance diagnostic for the Unity standalone game.

Start the listener without sending input. Each fresh F6 press can dispatch one
fixed +/-2 relative mouse pulse. F8 or Escape exits immediately.
"""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import queue
import secrets
import socket
import threading
import time

from .audit_destination import resolve_destination
from .macos_foreground import ForegroundQuery
from .macos_input import accessibility_trusted
from .quartz_matrix import (TelemetryReception, evaluate, precondition_snapshot,
                            validate_mouse_frame_schema)
from .telemetry import CorrectionLog

PORT = 8767
EXPECTED_APP = 'AI-Aim-Trainer-Test3.app'
PULSE_DELTAS = {(axis, sign): (2 * sign if axis == 'horizontal' else 0,
                               2 * sign if axis == 'vertical' else 0)
                for axis in ('horizontal', 'vertical') for sign in (-1, 1)}
F6_KEYCODE, F8_KEYCODE, ESC_KEYCODE = 97, 100, 53
OBSERVE_SECONDS = .65
QUIET_SECONDS = .30


def new_event_tag(randbits=secrets.randbits):
    """Unique positive signed-64-bit marker carried in kCGEventSourceUserData."""
    tag = randbits(63)
    if type(tag) is not int or not 0 < tag < (1 << 63):
        raise ValueError('Event tag generator must return a positive signed 64-bit value')
    return tag


def create_tagged_event(q, dx, dy, event_tag, pid):
    """Build and inspect one bounded tagged event without posting it."""
    if type(pid) is not int or pid <= 0:
        raise ValueError('A validated target PID is required')
    if type(dx) is not int or type(dy) is not int or (dx, dy) not in set(PULSE_DELTAS.values()):
        raise ValueError('Only one fixed +/-2 single-axis diagnostic pulse is allowed')
    if type(event_tag) is not int or not 0 < event_tag < (1 << 63):
        raise ValueError('Event tag must be a positive signed 64-bit value')
    location_event = q.CGEventCreate(None)
    if location_event is None:
        raise RuntimeError('Cannot read current Quartz cursor location')
    location = q.CGEventGetLocation(location_event)
    event = q.CGEventCreateMouseEvent(None, q.kCGEventMouseMoved, location, q.kCGMouseButtonRight)
    if event is None:
        raise RuntimeError('Cannot create Quartz diagnostic event')
    q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaX, dx)
    q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaY, dy)
    q.CGEventSetIntegerValueField(event, q.kCGEventSourceUserData, event_tag)
    record = {
        'target_pid': pid, 'event_tag': event_tag,
        'event_type': int(q.CGEventGetType(event)),
        'event_timestamp_ns_before_post': int(q.CGEventGetTimestamp(event)),
        'delta_x': int(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaX)),
        'delta_y': int(q.CGEventGetIntegerValueField(event, q.kCGMouseEventDeltaY)),
        'user_data_readback': int(q.CGEventGetIntegerValueField(event, q.kCGEventSourceUserData)),
        'location': [float(location.x), float(location.y)],
    }
    return event, record


def tap_event_record(q, event, target_pid, expected_tag, monotonic=None, utc_now=None):
    """Sanitize one listen-only tap callback; never alters or returns a new event."""
    get = q.CGEventGetIntegerValueField
    tag = int(get(event, q.kCGEventSourceUserData))
    return {
        'event': 'tap_mouse_moved',
        'observed_at': (utc_now or datetime.now(timezone.utc)).isoformat(),
        'observed_monotonic': (time.perf_counter() if monotonic is None else monotonic),
        'target_pid': target_pid,
        'event_type': int(q.CGEventGetType(event)),
        'event_timestamp_ns': int(q.CGEventGetTimestamp(event)),
        'delta_x': int(get(event, q.kCGMouseEventDeltaX)),
        'delta_y': int(get(event, q.kCGMouseEventDeltaY)),
        'event_tag': tag,
        'classification': ('tagged_current_pulse' if tag == expected_tag else
                           'untagged' if tag == 0 else 'tagged_other'),
        'source_pid': int(get(event, q.kCGEventSourceUnixProcessID)),
    }


class ProcessMouseEventTap:
    """Read-only tap scoped to the target PID; captures only during an F6 trial."""
    def __init__(self, q, cf, pid, records):
        self.q, self.cf, self.pid, self.records = q, cf, pid, records
        self.enabled = threading.Event()
        self.ready = threading.Event()
        self.stop_event = threading.Event()
        self.errors = queue.Queue()
        self.thread = None
        self.tap = None
        self.loop = None
        self.expected_tag = None

    def callback(self, _proxy, event_type, event, _refcon):
        try:
            if event_type in (self.q.kCGEventTapDisabledByTimeout,
                              self.q.kCGEventTapDisabledByUserInput):
                self.errors.put(f'event tap disabled by system ({event_type})')
            elif self.enabled.is_set() and int(event_type) == int(self.q.kCGEventMouseMoved):
                self.records.put(tap_event_record(self.q, event, self.pid, self.expected_tag))
        except Exception as error:
            self.errors.put(f'event tap callback failed: {type(error).__name__}: {error}')
        return event  # Listen-only; return the original event unchanged.

    def _run(self):
        try:
            mask = 1 << self.q.kCGEventMouseMoved
            self.tap = self.q.CGEventTapCreateForPid(
                self.pid, self.q.kCGHeadInsertEventTap,
                self.q.kCGEventTapOptionListenOnly, mask, self.callback, None)
            if self.tap is None:
                raise RuntimeError('CGEventTapCreateForPid returned no tap; check Input Monitoring and Accessibility.')
            source = self.cf.CFMachPortCreateRunLoopSource(None, self.tap, 0)
            if source is None:
                raise RuntimeError('Could not create the event tap run-loop source.')
            self.loop = self.cf.CFRunLoopGetCurrent()
            self.cf.CFRunLoopAddSource(self.loop, source, self.cf.kCFRunLoopDefaultMode)
            self.q.CGEventTapEnable(self.tap, True)
            self.ready.set()
            while not self.stop_event.is_set():
                self.cf.CFRunLoopRunInMode(self.cf.kCFRunLoopDefaultMode, .05, True)
                if not self.errors.empty():
                    break
        except Exception as error:
            self.errors.put(f'{type(error).__name__}: {error}')
            self.ready.set()
        finally:
            if self.tap is not None:
                self.cf.CFMachPortInvalidate(self.tap)

    def start(self, timeout=3.):
        self.thread = threading.Thread(target=self._run, name='UnityMouseEventTap', daemon=True)
        self.thread.start()
        if not self.ready.wait(timeout):
            raise RuntimeError('Timed out creating the target-process event tap.')
        if not self.errors.empty():
            raise RuntimeError(self.errors.get())

    def stop(self):
        self.enabled.clear()
        self.stop_event.set()
        if self.loop is not None:
            self.cf.CFRunLoopStop(self.loop)
        if self.thread:
            self.thread.join(timeout=1.)


def analyze_trial(before, after, delta, unity_frames, tap_events, event_tag):
    """Keep the existing strict Matrix result alongside provenance evidence."""
    if after['frame'] <= before['frame']:
        strict = {'success': False, 'quiet': False, 'frame_count_valid': False,
                  'rejected_checks': ['unity_telemetry_did_not_advance'],
                  'camera_yaw_change': None, 'camera_pitch_change': None}
    else:
        strict = evaluate(before, after, delta)
    tagged = [e for e in tap_events if e['classification'] == 'tagged_current_pulse']
    untagged = [e for e in tap_events if e['classification'] == 'untagged']
    other_tagged = [e for e in tap_events if e['classification'] == 'tagged_other']
    matching_frames = [f for f in unity_frames
                       if before['frame'] < f['frame'] <= after['frame'] and
                       before['axis_nonzero_frames'] < f['input_sequence'] <= after['axis_nonzero_frames']]
    new_frames = after['axis_nonzero_frames'] - before['axis_nonzero_frames']
    event_tags = collections_tag_counts(tap_events)
    correlations = correlate_tap_events(tap_events, matching_frames)
    if len(tagged) == 1 and new_frames == 2 and not untagged:
        inference = 'one_tagged_tap_event_two_Unity_input_frames'
    elif len(tagged) > 1:
        inference = 'same_tag_observed_on_multiple_tap_callbacks'
    elif len(tagged) == 1 and untagged:
        inference = 'tagged_event_plus_untagged_movement_possible'
    elif not tagged:
        inference = 'tag_not_observed_at_target_tap'
    else:
        inference = 'event_and_Unity_frame_counts_differ'
    return {
        'event': 'provenance_trial_result', 'target_pid': after['pid'],
        'event_tag': event_tag, 'requested_delta': list(delta),
        'tagged_event_count': len(tagged), 'untagged_event_count': len(untagged),
        'other_tagged_event_count': len(other_tagged), 'event_tag_counts': event_tags,
        'tagged_events': tagged, 'untagged_events': untagged,
        'unity_frame_count': new_frames, 'unity_frames': matching_frames,
        'event_frame_correlations': correlations,
        'unity_total_mouse_x': after['axis_sum_x'] - before['axis_sum_x'],
        'unity_total_mouse_y': after['axis_sum_y'] - before['axis_sum_y'],
        'yaw_change': strict['camera_yaw_change'], 'pitch_change': strict['camera_pitch_change'],
        'strict_matrix_verdict': strict,
        'provenance_interpretation': inference,
        'limitations': ['A target-process event tap observes the event stream at its tap point, not Unity consumption.',
                        'Untagged events are not automatically attributable to a physical device.',
                        'Unity frame telemetry contains no Quartz event identifier.'],
        'head_lock_enabled': False,
    }


def correlate_tap_events(tap_events, unity_frames):
    """Pair each tap observation with its nearest Unity frame in UTC time."""
    parsed_frames = []
    for frame in unity_frames:
        try:
            frame_time = datetime.fromisoformat(frame['timestamp'].replace('Z', '+00:00'))
        except (KeyError, TypeError, ValueError):
            continue
        parsed_frames.append((frame_time, frame))
    output = []
    for event in tap_events:
        try:
            tap_time = datetime.fromisoformat(event['observed_at'].replace('Z', '+00:00'))
        except (KeyError, TypeError, ValueError):
            continue
        nearest = min(parsed_frames, key=lambda pair: abs((pair[0]-tap_time).total_seconds())) if parsed_frames else None
        row = {'event_tag': event['event_tag'], 'classification': event['classification'],
               'event_timestamp_ns': event['event_timestamp_ns'],
               'tap_observed_at': event['observed_at']}
        if nearest:
            frame_time, frame = nearest
            row.update(unity_frame=frame['frame'], unity_input_sequence=frame['input_sequence'],
                       unity_frame_timestamp=frame['timestamp'],
                       unity_realtime_seconds=frame['realtime'],
                       frame_minus_tap_observed_ms=(frame_time-tap_time).total_seconds()*1000,
                       event_uptime_minus_unity_realtime_seconds=(
                           event['event_timestamp_ns']/1_000_000_000-frame['realtime']))
        else:
            row['unity_frame_match'] = None
        output.append(row)
    return output


def collections_tag_counts(events):
    counts = {}
    for event in events:
        key = str(event['event_tag'])
        counts[key] = counts.get(key, 0) + 1
    return counts


class Backend:
    def __init__(self, pid, window_id, expected_app, foreground, q):
        self.pid, self.window_id, self.expected_app = pid, window_id, expected_app
        self.foreground, self.q = foreground, q

    def trusted(self):
        return accessibility_trusted()

    def snapshot(self):
        return {**self.foreground.snapshot(), 'accessibility_trusted': self.trusted()}

    def validate_destination(self):
        return resolve_destination(self.window_id, self.pid, expected_app=self.expected_app)


def run(args):
    import Quartz as q
    import CoreFoundation as cf

    if not accessibility_trusted():
        raise RuntimeError('Accessibility permission is required for the Python host to post the explicit test pulse.')
    if not q.CGPreflightListenEventAccess():
        raise RuntimeError('Input Monitoring permission is required for the read-only event tap. No permission prompt was requested.')
    destination = resolve_destination(args.window_id, expected_app=args.expect_app)
    pid = destination['resolved_owner_pid']
    log = CorrectionLog(Path.home() / 'Library/Logs/AI-Aim-Trainer/quartz_provenance')
    records = queue.Queue()
    tap = ProcessMouseEventTap(q, cf, pid, records)
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        receiver.bind(('127.0.0.1', args.port))
    except OSError:
        receiver.close()
        raise
    receiver.setblocking(False)
    reception = TelemetryReception()
    foreground = ForegroundQuery()
    backend = Backend(pid, args.window_id, args.expect_app, foreground, q)
    delta = PULSE_DELTAS[(args.axis, 1 if args.direction == 'positive' else -1)]
    history = deque()
    latest = None
    f6_was_down = bool(q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, F6_KEYCODE))
    logger = log
    try:
        tap.start()
        logger.write({'event': 'provenance_started', **destination, 'tap_pid': pid,
                      'tap_scope': 'target_process_mouse_moved_listen_only',
                      'udp_port': args.port, 'accessibility_trusted': True,
                      'input_monitoring_preflight': True, 'head_lock_enabled': False,
                      'instruction': 'No pulse sent at startup. One fresh F6 press sends one bounded event.'})
        print(f"Provenance listener ready for PID {pid}. No pulse sent. F6: one {delta} pulse; F8/Esc: stop.", flush=True)
        while True:
            if q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, F8_KEYCODE) or \
                    q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, ESC_KEYCODE):
                logger.write({'event': 'provenance_stopped', 'reason': 'F8_or_escape', 'head_lock_enabled': False})
                break
            try:
                while True:
                    packet, _address = receiver.recvfrom(65535)
                    decoded = reception.decode(packet, pid, time.perf_counter())
                    if decoded is not None:
                        latest = decoded
                        history.append((reception.last_state_received_at, dict(decoded)))
                        while history and time.perf_counter() - history[0][0] > 1.5:
                            history.popleft()
            except BlockingIOError:
                pass

            f6_down = bool(q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, F6_KEYCODE))
            fresh_edge = f6_down and not f6_was_down
            f6_was_down = f6_down
            if not tap.errors.empty():
                raise RuntimeError(tap.errors.get())
            if fresh_edge:
                now = time.perf_counter()
                check = precondition_snapshot(backend, latest, reception.last_state_received_at,
                                              now, args.port, reception, require_frame_history=True)
                baseline = history[0][1] if history else None
                baseline_quiet = (baseline is not None and history and
                                  now - history[0][0] >= QUIET_SECONDS and
                                  evaluate(baseline, latest, (0, 0))['quiet'])
                if check['rejected_preconditions'] or not baseline_quiet:
                    failures = check['rejected_preconditions'] + ([] if baseline_quiet else ['quiet_baseline_not_ready'])
                    logger.write({'event': 'pulse_rejected', 'reason': failures,
                                  'preconditions': check, 'input_events_posted': False,
                                  'head_lock_enabled': False})
                    print('Pulse blocked: ' + '; '.join(failures), flush=True)
                    time.sleep(.01)
                    continue
                # Recheck destination, focus, permission, and current telemetry immediately
                # before constructing/posting. No retries and no queued pulse.
                destination = backend.validate_destination()
                latest = history[-1][1]
                check = precondition_snapshot(backend, latest, reception.last_state_received_at,
                                              time.perf_counter(), args.port, reception,
                                              require_frame_history=True)
                if check['rejected_preconditions']:
                    logger.write({'event': 'pulse_rejected', 'reason': check['rejected_preconditions'],
                                  'preconditions': check, 'input_events_posted': False,
                                  'head_lock_enabled': False})
                    print('Pulse blocked at final check: ' + '; '.join(check['rejected_preconditions']), flush=True)
                    continue

                event_tag = new_event_tag()
                tap.expected_tag = event_tag
                tap.enabled.set()
                before = dict(latest)
                before_time = reception.last_state_received_at
                tap_events = []
                for _ in range(records.qsize()):
                    tap_events.append(records.get_nowait())
                try:
                    event, event_record = create_tagged_event(q, *delta, event_tag, pid)
                    dispatch_utc = datetime.now(timezone.utc).isoformat()
                    dispatch_monotonic = time.perf_counter()
                    q.CGEventPostToPid(pid, event)
                    post_return = time.perf_counter()
                except Exception as error:
                    tap.enabled.clear()
                    logger.write({'event': 'pulse_post_error', 'event_tag': event_tag,
                                  'error': f'{type(error).__name__}: {error}',
                                  'input_events_posted': 'unknown', 'head_lock_enabled': False})
                    raise
                logger.write({'event': 'tagged_pulse_posted', **destination, **event_record,
                              'dispatch_utc': dispatch_utc, 'dispatch_monotonic': dispatch_monotonic,
                              'post_return_monotonic': post_return, 'post_call_returned': True,
                              'input_events_posted': True, 'unity_acceptance_confirmed': False,
                              'head_lock_enabled': False})
                print(f"Posted one tagged pulse {delta}; observing {OBSERVE_SECONDS:.2f}s. Do not move the physical mouse.", flush=True)

                deadline = post_return + OBSERVE_SECONDS
                after = before
                unity_frames = {}
                safety_interruption = []
                while time.perf_counter() < deadline:
                    if q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, F8_KEYCODE) or \
                            q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, ESC_KEYCODE):
                        logger.write({'event': 'trial_cancelled', 'event_tag': event_tag,
                                      'reason': 'F8_or_escape', 'head_lock_enabled': False})
                        raise KeyboardInterrupt
                    if not tap.errors.empty():
                        safety_interruption = ['target_process_event_tap_failed']
                        logger.write({'event': 'trial_observation_failed', 'event_tag': event_tag,
                                      'reason': safety_interruption, 'head_lock_enabled': False})
                        break
                    try:
                        while True:
                            packet, _address = receiver.recvfrom(65535)
                            decoded = reception.decode(packet, pid, time.perf_counter())
                            if decoded is not None:
                                after = decoded
                                history.append((reception.last_state_received_at, dict(decoded)))
                                frame_result = validate_mouse_frame_schema(decoded)
                                if frame_result.get('schema_valid'):
                                    for frame in decoded.get('mouse_frames', []):
                                        seq = frame.get('input_sequence')
                                        if type(seq) is int and seq > before['axis_nonzero_frames']:
                                            unity_frames[seq] = frame
                    except BlockingIOError:
                        pass
                    while not records.empty():
                        tap_events.append(records.get_nowait())
                    current = time.perf_counter()
                    foreground_snapshot = foreground.snapshot()
                    current_check = precondition_snapshot(backend, after,
                        reception.last_state_received_at, current, args.port, reception,
                        require_frame_history=True)
                    # Focus/menu/session changes abort observation; they never schedule another pulse.
                    if current_check['rejected_preconditions']:
                        safety_interruption = list(current_check['rejected_preconditions'])
                        logger.write({'event': 'trial_safety_interruption', 'event_tag': event_tag,
                                      'reason': safety_interruption,
                                      'foreground': foreground_snapshot, 'head_lock_enabled': False})
                        break
                    time.sleep(.005)
                tap.enabled.clear()
                while not records.empty():
                    tap_events.append(records.get_nowait())
                result = analyze_trial(before, after, delta, list(unity_frames.values()), tap_events, event_tag)
                result.update(dispatch_utc=dispatch_utc, dispatch_monotonic=dispatch_monotonic,
                              unity_observation_start_frame=before.get('frame'),
                              unity_observation_end_frame=after.get('frame'),
                              unity_observation_age_ms=(time.perf_counter()-reception.last_state_received_at)*1000
                              if reception.last_state_received_at is not None else None,
                              pre_pulse_telemetry_age_ms=(dispatch_monotonic-before_time)*1000,
                              observation_interrupted=bool(safety_interruption),
                              observation_interruption_reasons=safety_interruption,
                              input_events_posted=True)
                logger.write(result)
                logger.write({'event': 'pulse_window_closed', 'event_tag': event_tag,
                              'reason': 'observation_complete', 'head_lock_enabled': False})
                print(json.dumps({k: result[k] for k in (
                    'event_tag', 'tagged_event_count', 'untagged_event_count', 'unity_frame_count',
                    'unity_total_mouse_x', 'unity_total_mouse_y', 'yaw_change', 'pitch_change',
                    'provenance_interpretation', 'strict_matrix_verdict')}, indent=2), flush=True)
            time.sleep(.01)
    finally:
        tap.stop()
        receiver.close()
        logger.write({'event': 'provenance_stopped', 'reason': 'shutdown', 'head_lock_enabled': False})
        logger.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-id', type=int, required=True)
    parser.add_argument('--expect-app', default=EXPECTED_APP)
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--axis', choices=('horizontal', 'vertical'), default='horizontal')
    parser.add_argument('--direction', choices=('positive', 'negative'), default='positive')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    try:
        run(args)
    except KeyboardInterrupt:
        print('Stopped by user. No automatic retry was performed.', flush=True)
    except Exception as error:
        parser.exit(1, f'Provenance diagnostic stopped safely: {type(error).__name__}: {error}\n')


if __name__ == '__main__':
    main()
