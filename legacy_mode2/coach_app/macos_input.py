"""Targeted relative-motion experiment for our Unity process, never firing."""

import math
import ctypes


def accessibility_trusted():
    # AX belongs to ApplicationServices, not the Quartz Python namespace.
    services = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    services.AXIsProcessTrusted.restype = ctypes.c_bool
    services.AXIsProcessTrusted.argtypes = []
    return bool(services.AXIsProcessTrusted())


class MacMouseBackend:
    def __init__(self, pid, window_id=None):
        import Quartz
        import AppKit
        self.q, self.appkit, self.pid = Quartz, AppKit, pid
        self.window_id = window_id
        self.destination_executable = None
        if window_id is not None:
            if __package__:
                from .audit_destination import resolve_destination
            else:
                from audit_destination import resolve_destination
            import json
            destination = resolve_destination(window_id, expected_pid=pid)
            self.destination_executable = destination['game_executable']
            print('[assist] Quartz destination: ' + json.dumps(destination), flush=True)
        if not accessibility_trusted():
            # Run inside the actual Unity-launched Coach, not a diagnostic child.
            # Never log environment variables, command arguments, or credentials.
            if __package__:
                from .diagnose_accessibility import diagnose, save_report
            else:
                from diagnose_accessibility import diagnose, save_report
            import json
            diagnostic_location = "Run .venv/bin/python -m coach_app.diagnose_accessibility for diagnostics."
            try:
                report = diagnose()
                print("[assist] Accessibility diagnostics: " + json.dumps(report), flush=True)
                path = save_report(report)
                diagnostic_location = f"Actual Coach diagnostic: {path}."
            except (OSError, RuntimeError):
                print("[assist] Could not collect extra Accessibility diagnostics.", flush=True)
            raise RuntimeError("Accessibility permission is required for Coach/Python's host in "
                               "System Settings > Privacy & Security > Accessibility. "
                               f"{diagnostic_location} Restart Coach after granting access.")

    def held(self):
        q = self.q
        return bool(q.CGEventSourceButtonState(q.kCGEventSourceStateHIDSystemState, q.kCGMouseButtonRight))

    def emergency(self):
        # F8 or Escape is an immediate latch-off, even if the Coach is collapsed.
        q = self.q
        return any(q.CGEventSourceKeyState(q.kCGEventSourceStateHIDSystemState, key) for key in (100, 53))

    def focused(self):
        app = self.appkit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return app is not None and app.processIdentifier() == self.pid

    def move(self, dx, dy):
        # Do not warp/relock the cursor or synthesize clicks. Unity may ignore these
        # deltas: measured camera-response calibration is mandatory before use.
        q = self.q
        if not self.held() or not self.focused() or self.emergency():
            return False
        if not all(math.isfinite(v) for v in (dx, dy)) or math.hypot(dx, dy) > 4.01:
            raise ValueError("Unsafe relative mouse delta")
        if getattr(self, 'window_id', None) is not None:
            if __package__:
                from .audit_destination import resolve_destination
            else:
                from audit_destination import resolve_destination
            destination = resolve_destination(self.window_id, self.pid, self.destination_executable)
            import json
            print('[assist] Quartz pre-post destination: ' + json.dumps(destination), flush=True)
            if not self.held() or not self.focused() or self.emergency():
                return False
        location = q.CGEventGetLocation(q.CGEventCreate(None))
        event = q.CGEventCreateMouseEvent(None, q.kCGEventMouseMoved, location, q.kCGMouseButtonRight)
        if event is None:
            raise RuntimeError("macOS could not create relative mouse event")
        q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaX, round(dx))
        q.CGEventSetIntegerValueField(event, q.kCGMouseEventDeltaY, round(dy))
        q.CGEventPostToPid(self.pid, event)
        return True
