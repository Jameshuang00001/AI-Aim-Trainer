"""Passive Unity gameplay-state recorder. No keyboard handling or input posting."""
import argparse
from pathlib import Path
import socket
import time

from .audit_destination import resolve_destination
from .macos_foreground import ForegroundQuery
from .macos_input import accessibility_trusted
from .quartz_matrix import TelemetryReception, precondition_snapshot, print_preconditions
from .telemetry import CorrectionLog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-id', type=int, required=True)
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--duration', type=float, default=60.)
    parser.add_argument('--expect-app', default='AI-Aim-Trainer-Test2.app')
    args = parser.parse_args()
    if not 1 <= args.duration <= 300 or not 1 <= args.port <= 65535:
        parser.error('Use duration 1-300 seconds and port 1-65535')
    destination = resolve_destination(args.window_id, expected_app=args.expect_app)
    pid = destination['resolved_owner_pid']
    query = ForegroundQuery()

    class ReadOnlyBackend:
        def __init__(self):
            self.pid = pid

        def snapshot(self):
            return {**query.snapshot(), 'accessibility_trusted': accessibility_trusted()}

        def validate_destination(self):
            return resolve_destination(args.window_id, pid, destination['game_executable'], args.expect_app)

    backend = ReadOnlyBackend()  # Deliberately has no post/move method.
    reception = TelemetryReception()
    receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    log = None
    latest = None
    try:
        try:
            receiver.bind(('127.0.0.1', args.port))
        except OSError as error:
            parser.error(f'Cannot bind UDP {args.port}: {error}. Stop matrix/calibration receivers first.')
        receiver.setblocking(False)
        log = CorrectionLog(Path.home()/'Library/Logs/AI-Aim-Trainer/gameplay_diagnostics')
        print(f'READ ONLY: no synthetic input or app activation. Log: {log.path}\n'
              'Use Start Game, Settings/Continue and Summary/ESC physically. Control-C stops.', flush=True)
        started = time.perf_counter()
        state, received, previous, last_print = None, 0., None, 0.
        while time.perf_counter()-started < args.duration:
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
            now = time.perf_counter()
            latest = precondition_snapshot(backend, state, received, now, args.port, reception)
            signature = (tuple(latest['rejected_preconditions']), latest['foreground_pid'],
                         tuple(latest['unity_gameplay_blockers'] or []), latest['settings_panel_visible'],
                         latest['summary_panel_visible'], latest['start_menu_visible'])
            if signature != previous or now-last_print >= 1.:
                log.write({'event': 'gameplay_state', **latest, 'input_events_posted': False,
                           'head_lock_enabled': False})
                print_preconditions(latest)
                if latest['unity_telemetry_received'] and latest['unity_precondition_version'] != 2:
                    print('Detailed state unavailable: rebuild Unity with AssistStatePublisher precondition_version=2.', flush=True)
                previous, last_print = signature, now
            time.sleep(.02)
    except KeyboardInterrupt:
        pass
    finally:
        receiver.close()
        if log:
            log.write({'event': 'gameplay_summary', 'last_state': latest,
                       'input_events_posted': False, 'head_lock_enabled': False})
            log.close()


if __name__ == '__main__':
    main()
