"""Event-driven native window policy; no activation, global hooks, or polling."""

import sys
import threading


class FloatingWindowPolicy:
    def __init__(self, root) -> None:
        self.root = root
        self.pending = None
        self.warned = False
        self.window = None
        self.appkit = None
        if sys.platform != "darwin":
            return
        try:
            import AppKit
            self.appkit = AppKit
        except ImportError:
            print("[coach] Native floating level unavailable. Install coach_app/requirements.txt in .venv.", flush=True)
            return
        # Tk may recreate/reconfigure its NSWindow on map or reset its level when
        # deactivated. Reapply once after those events, never on a timer.
        root.bind("<Map>", self.schedule, add="+")
        root.bind("<Deactivate>", self.schedule, add="+")

    def schedule(self, event=None) -> None:
        if self.appkit is None or (event is not None and event.widget != self.root):
            return
        if self.pending is None:
            self.pending = self.root.after_idle(self.apply)

    def apply(self) -> None:
        self.pending = None
        if self.appkit is None or not self.root.winfo_exists():
            return
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("Native window policy must run on the main thread")
        kit = self.appkit
        # Tk winfo_id is a Tk drawable, not an NSWindow pointer. Match the owned
        # root title in this process only; never alter Unity or file-dialog windows.
        windows = kit.NSApplication.sharedApplication().windows()
        matches = [item for item in windows if str(item.title()) == self.root.title()]
        # Tk can retain closed NSWindows briefly when roots are destroyed (tests
        # or embedded use). Never configure a hidden retired window instead.
        window = next((item for item in matches if item.isVisible()), None)
        if window is None and self.window in matches:
            window = self.window
        if window is None:
            if not self.warned:
                print("[coach] Waiting for Tk's native window; floating policy will retry on the next map.", flush=True)
                self.warned = True
            return
        window.setLevel_(kit.NSFloatingWindowLevel)
        window.setHidesOnDeactivate_(False)
        window.setCanHide_(False)
        window.setIgnoresMouseEvents_(False)
        behavior = int(window.collectionBehavior())
        behavior &= ~(kit.NSWindowCollectionBehaviorMoveToActiveSpace | kit.NSWindowCollectionBehaviorManaged)
        behavior |= kit.NSWindowCollectionBehaviorCanJoinAllSpaces | kit.NSWindowCollectionBehaviorFullScreenAuxiliary
        window.setCollectionBehavior_(behavior)
        # No makeKeyAndOrderFront, activateIgnoringOtherApps, or focus_force.
        self.window = window

