"""Read-only Quartz destination audit: no event creation, posting or capture."""
import argparse
import ctypes
import json
import os
from pathlib import Path


def executable_path(pid):
    library = ctypes.CDLL('/usr/lib/libproc.dylib')
    library.proc_pidpath.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
    library.proc_pidpath.restype = ctypes.c_int
    buffer = ctypes.create_string_buffer(4096)
    if library.proc_pidpath(pid, buffer, len(buffer)) <= 0:
        raise RuntimeError(f'Cannot resolve executable for window owner PID {pid}; process may have exited.')
    return str(Path(os.fsdecode(buffer.value)).resolve())


def resolve_destination(window_id, expected_pid=None, expected_executable=None, expected_app=None):
    import Quartz as q
    rows = q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionIncludingWindow, window_id) or []
    row = next((r for r in rows if int(r.get(q.kCGWindowNumber, -1)) == window_id), None)
    if row is None:
        raise RuntimeError(f'Selected window ID {window_id} is unavailable to this process '
                           '(stale window or restricted window metadata). Re-detect from an authorized host.')
    pid = int(row[q.kCGWindowOwnerPID])
    executable = executable_path(pid)
    bundle = next((p for p in Path(executable).parents if p.suffix == '.app'), None)
    if pid == os.getpid():
        raise RuntimeError('Selected window belongs to Coach itself; refusing it as an input destination.')
    if expected_pid is not None and pid != expected_pid:
        raise RuntimeError(f'Window {window_id} owner changed: expected PID {expected_pid}, actual PID {pid}.')
    if expected_executable is not None and executable != expected_executable:
        raise RuntimeError(f'Window {window_id} executable changed: {executable}')
    if expected_app is not None and (bundle is None or bundle.name != expected_app):
        raise RuntimeError(f'Expected {expected_app}; window {window_id} is owned by {executable}')
    return {'selected_window_id': window_id, 'resolved_owner_pid': pid,
            'CGEventPostToPid_destination_pid': pid, 'game_executable': executable,
            'game_bundle': str(bundle) if bundle else None,
            'owner_name': str(row.get(q.kCGWindowOwnerName, '')),
            'window_title': str(row.get(q.kCGWindowName, '')),
            'source': 'kCGWindowOwnerPID', 'input_events_posted': False}


def main():
    import AppKit
    import Quartz as q
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--window-id', type=int)
    parser.add_argument('--expect-app', default='AI-Aim-Trainer-Test.app')
    args = parser.parse_args()
    if args.window_id is None:
        # Bundle identity, not the display/owner name, identifies renamed test apps.
        games = [a for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
                 if a.bundleURL() and Path(str(a.bundleURL().path())).name == args.expect_app]
        pids = {int(a.processIdentifier()) for a in games}
        rows = q.CGWindowListCopyWindowInfo(q.kCGWindowListOptionOnScreenOnly, 0) or []
        windows = [{'id': int(r[q.kCGWindowNumber]), 'pid': int(r[q.kCGWindowOwnerPID])}
                   for r in rows if r.get(q.kCGWindowOwnerPID) in pids and r.get(q.kCGWindowLayer, 0) == 0]
        if len(windows) != 1:
            parser.error(f'Choose --window-id from current standalone windows: {windows}; '
                         f'running game PIDs: {sorted(pids)}; '
                         f'Screen Recording authorized for this diagnostic process: {bool(q.CGPreflightScreenCaptureAccess())}. '
                         'Run from an authorized host; a process match alone does not prove window ownership.')
        args.window_id = windows[0]['id']
    try:
        print(json.dumps(resolve_destination(args.window_id, expected_app=args.expect_app), indent=2))
    except RuntimeError as error:
        parser.error(str(error))


if __name__ == '__main__':
    main()
