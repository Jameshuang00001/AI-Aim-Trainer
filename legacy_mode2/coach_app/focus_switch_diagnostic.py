"""Passive Terminal -> Unity -> Terminal observation. No input posting imports."""
import argparse
import json
from pathlib import Path
import time

from .audit_destination import resolve_destination, executable_path
from .macos_foreground import ForegroundQuery
from .telemetry import CorrectionLog


def verified_sequence(rows, terminal_pid, game_pid):
    # Transitions must include all three phases, not merely one sighting of each app.
    expected = (terminal_pid, game_pid, terminal_pid)
    index = 0
    for row in rows:
        if index < len(expected) and row['foreground_pid'] == expected[index]:
            index += 1
    return index == len(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-id', type=int, required=True)
    parser.add_argument('--terminal-pid', type=int)
    parser.add_argument('--duration', type=float, default=60.)
    parser.add_argument('--expect-app', default='AI-Aim-Trainer-Test2.app')
    args = parser.parse_args()
    if not 1 <= args.duration <= 300:
        parser.error('--duration must be between 1 and 300 seconds')
    import AppKit
    if args.terminal_pid is None:
        apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_('com.apple.Terminal')
        if len(apps) != 1:
            parser.error('Choose the actual Terminal PID with --terminal-pid')
        args.terminal_pid = int(apps[0].processIdentifier())
    terminal_path = Path(executable_path(args.terminal_pid))
    if terminal_path.name != 'Terminal' or 'Terminal.app' not in terminal_path.parts:
        parser.error('--terminal-pid does not resolve to Terminal.app')
    destination = resolve_destination(args.window_id, expected_app=args.expect_app)
    game_pid = destination['resolved_owner_pid']
    query = ForegroundQuery()
    rows = []
    with_log = CorrectionLog(Path.home()/'Library/Logs/AI-Aim-Trainer/focus_diagnostics')
    print(f'PASSIVE ONLY: no activation, clicks, mouse events, or UDP receiver.\n'
          f'Observe Terminal ({args.terminal_pid}) -> Unity ({game_pid}) -> Terminal.\n'
          f'Physically focus each app for at least 3 seconds. Duration: {args.duration}s.\n'
          f'Log: {with_log.path}', flush=True)
    previous = None
    started = time.perf_counter()
    error = None
    try:
        while time.perf_counter()-started < args.duration:
            # Ownership only validates the selected window; it never supplies foreground PID.
            resolve_destination(args.window_id, game_pid, destination['game_executable'], args.expect_app)
            row = query.snapshot()
            signature = (row['nsworkspace_before_pump_pid'], row['foreground_pid'])
            if signature != previous:
                row.update(event='focus_observation', selected_game_pid=game_pid,
                           selected_window_id=args.window_id, input_events_posted=False)
                rows.append(row)
                with_log.write(row)
                print(json.dumps(row), flush=True)
                previous = signature
            time.sleep(.05)
    except KeyboardInterrupt:
        pass
    except Exception as exception:
        error = str(exception)
    finally:
        result = {'event': 'focus_summary', 'sequence_verified': error is None and verified_sequence(rows, args.terminal_pid, game_pid),
                  'stale_value_observed': any(r['nsworkspace_before_pump_pid'] != r['foreground_pid'] for r in rows),
                  'error': error,
                  'terminal_pid': args.terminal_pid, 'game_pid': game_pid,
                  'transitions': [r['foreground_pid'] for r in rows],
                  'input_events_posted': False, 'head_lock_enabled': False}
        with_log.write(result)
        print(json.dumps(result), flush=True)
        with_log.close()


if __name__ == '__main__':
    main()
