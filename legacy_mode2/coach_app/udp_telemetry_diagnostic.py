"""Receive ONE loopback Unity packet. Never inject input or send a datagram."""
import argparse
import json
import socket
import time

from .quartz_matrix import TelemetryReception, validate_mouse_frame_schema


def packet_summary(data, expected_pid, reception=None):
    reception = reception if reception is not None else TelemetryReception()
    state = reception.decode(data, expected_pid, time.monotonic())
    result = {'status': 'valid_packet' if state is not None else 'invalid_packet',
              'packet_received': True, 'packet_bytes': len(data),
              # Never print raw JSON, arbitrary strings, paths, or frame history.
              'rejection': (reception.last_packet_rejection or '').split(' (')[0] or None,
              'input_events_posted': False, 'head_lock_enabled': False}
    if state is None and reception.assembler.pending:
        result['status'] = 'incomplete_diagnostic_batch'
    if state is not None:
        result['fields'] = {k: state.get(k) if type(state.get(k)) in (int, bool) else None
                            for k in ('pid', 'frame', 'diagnostic_version', 'mouse_frame_version',
                                      'axis_nonzero_frames', 'gameplay', 'application_focused',
                                      'cursor_locked', 'session_active', 'paused')}
        frames = state.get('mouse_frames')
        result['mouse_frames_is_array'] = isinstance(frames, list)
        result['mouse_frame_count'] = len(frames) if isinstance(frames, list) else None
        result['frame_schema'] = validate_mouse_frame_schema(state)
        result['transport'] = reception.last_transport
    return result


def receive_one(port, expected_pid, timeout=5.):
    # No reuse flags: never share/steal another diagnostic's listener.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as receiver:
        try:
            receiver.bind(('127.0.0.1', port))
        except OSError as error:
            return {'status': 'bind_failed', 'errno': error.errno,
                    'packet_received': False, 'input_events_posted': False,
                    'head_lock_enabled': False}
        deadline = time.monotonic()+timeout
        reception = TelemetryReception()
        last = None
        for _ in range(256):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                break
            receiver.settimeout(remaining)
            try:
                data, address = receiver.recvfrom(65535)
            except socket.timeout:
                break
            if address[0] != '127.0.0.1':
                return {'status': 'unexpected_sender', 'packet_received': True,
                        'input_events_posted': False, 'head_lock_enabled': False}
            last = packet_summary(data, expected_pid, reception)
            if last['status'] != 'incomplete_diagnostic_batch':
                return last
        return last or {'status': 'no_packet_received', 'packet_received': False,
                        'timeout_seconds': timeout, 'input_events_posted': False,
                        'head_lock_enabled': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--pid', type=int, required=True, help='Current Unity process PID')
    parser.add_argument('--timeout', type=float, default=5.)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or args.pid <= 0 or not 0 < args.timeout <= 60:
        parser.error('Use a valid port, positive PID, and timeout between 0 and 60 seconds.')
    print(json.dumps(receive_one(args.port, args.pid, args.timeout), indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
