"""Read-only foreground state for command-line tools without a Cocoa event loop."""
from datetime import datetime, timezone
import threading
import time


class ForegroundQuery:
    def __init__(self, workspace=None, pump=None):
        if workspace is None:
            import AppKit
            workspace = AppKit.NSWorkspace.sharedWorkspace()
        if pump is None:
            import Foundation

            def pump():
                # Service workspace notifications, never activate/raise a window.
                Foundation.NSRunLoop.mainRunLoop().runUntilDate_(
                    Foundation.NSDate.dateWithTimeIntervalSinceNow_(.001))
        self.workspace, self.pump = workspace, pump

    def snapshot(self):
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError('ForegroundQuery must service Cocoa on the main thread')
        before = self.workspace.frontmostApplication()
        before_pid = int(before.processIdentifier()) if before is not None else None
        self.pump()
        after = self.workspace.frontmostApplication()
        after_pid = int(after.processIdentifier()) if after is not None else None
        return {'foreground_pid': after_pid,
                'nsworkspace_before_pump_pid': before_pid,
                'nsworkspace_after_pump_pid': after_pid,
                'foreground_query': 'NSWorkspace_after_main_runloop',
                'foreground_checked_at': datetime.now(timezone.utc).isoformat(),
                'foreground_checked_monotonic': time.perf_counter()}
