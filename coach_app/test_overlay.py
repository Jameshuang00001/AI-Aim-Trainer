"""Opt-in real Tk tests: COACH_GUI_TESTS=1. No Unity or paid model requests."""

import json
import os
import sys
from pathlib import Path
import queue
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from coach_app.overlay import CoachWindow


@unittest.skipUnless(os.environ.get("COACH_GUI_TESTS") == "1", "Opt-in desktop GUI tests")
class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.errors = []
        self.root.report_callback_exception = lambda *error: self.errors.append(error)
        self.commands = queue.Queue()
        self.app = CoachWindow(self.root, commands=self.commands)
        self.root.update()
        self.directory = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.app.closed = True
        self.root.after_cancel(self.app.poll_id)
        self.root.destroy()
        self.directory.cleanup()
        self.assertEqual(self.errors, [])

    def pump_until(self, predicate):
        deadline = time.monotonic() + 4
        while not predicate() and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.assertTrue(predicate())

    def session(self, hits):
        path = Path(self.directory.name) / f"session-{hits}.json"
        path.write_text(json.dumps(dict(session_id=f"test-{hits}", started_at="start", ended_at="end",
                                       shots=10, hits=hits, misses=10-hits, accuracy=hits*10,
                                       avg_reaction_ms=1138.7, shots_detail=[])))
        return path

    def test_widget_panel_drag_and_layout(self):
        self.assertFalse(self.app.expanded)
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), (64, 64))
        self.app.widget.event_generate("<ButtonPress-1>", x=32, y=32)
        self.app.widget.event_generate("<ButtonRelease-1>", x=32, y=32)
        self.root.update()
        self.assertTrue(self.app.expanded)
        self.assertEqual((self.root.winfo_width(), self.root.winfo_height()), (480, 650))
        self.assertEqual(str(self.app.mode_menu.entrycget(1, "state")), "disabled")
        self.assertGreater(self.app.report.winfo_height(), 90)
        for control in (self.app.latest_button, self.app.open_button, self.app.mode_button, self.app.minimize_button):
            self.assertGreaterEqual(control.winfo_width(), control.winfo_reqwidth())
            self.assertLessEqual(control.winfo_rooty() + control.winfo_height(), self.root.winfo_y() + 650)
        self.app.minimize_button.invoke()
        self.root.update()
        self.assertFalse(self.app.expanded)
        self.app.start_drag(SimpleNamespace(x_root=100, y_root=100))
        self.app.move_drag(SimpleNamespace(x_root=60, y_root=140))
        self.app.end_drag(None)
        self.root.update()
        self.assertFalse(self.app.expanded)  # Drag release must not expand.
        position = self.app.widget_position
        self.app.show_window()
        self.app.close()
        self.root.update()
        self.assertEqual(self.app.widget_position, position)
        self.assertEqual((self.root.winfo_x(), self.root.winfo_y()), position)
        self.assertFalse(any(isinstance(child, tk.Toplevel) for child in self.root.winfo_children()))

    @unittest.skipUnless(sys.platform == "darwin", "macOS native window checks")
    def test_native_level_survives_expansion_and_minimize(self):
        import AppKit
        for expand in (False, True, False):
            self.app.show_window() if expand else self.app.collapse()
            self.root.update()
            window = self.app.floating_policy.window
            self.assertIsNotNone(window, "Tk root must resolve to its owned NSWindow")
            self.assertEqual(window.level(), AppKit.NSFloatingWindowLevel)
            self.assertFalse(window.hidesOnDeactivate())
            self.assertFalse(window.ignoresMouseEvents())
            self.assertTrue(int(window.collectionBehavior()) & AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces)

    @unittest.skipUnless(sys.platform == "darwin", "macOS Unity focus check")
    def test_native_widget_with_unity_editor_focused(self):
        import AppKit
        editors = [app for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
                   if app.bundleIdentifier() == "com.unity3d.UnityEditor"]
        if not editors:
            self.skipTest("Unity Editor is not running")
        editor = editors[0]
        self.assertTrue(editor.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps))
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertEqual(AppKit.NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier(),
                         editor.processIdentifier())
        window = self.app.floating_policy.window
        self.assertEqual(window.level(), AppKit.NSFloatingWindowLevel)
        self.assertFalse(window.hidesOnDeactivate())
        self.assertTrue(window.isVisible())
        self.assertFalse(self.app.expanded)

    @unittest.skipUnless(sys.platform == "darwin", "macOS native deactivation check")
    def test_native_level_when_other_app_is_active(self):
        import AppKit
        finder = [app for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
                  if app.bundleIdentifier() == "com.apple.finder"]
        if not finder:
            self.skipTest("Finder unavailable for deactivation test")
        for expanded in (False, True):
            self.app.show_window() if expanded else self.app.collapse()
            self.root.update()
            finder[0].activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
            deadline = time.monotonic() + 0.4
            while time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            window = self.app.floating_policy.window
            self.assertEqual(window.level(), AppKit.NSFloatingWindowLevel)
            self.assertTrue(window.isVisible())
            self.assertFalse(window.hidesOnDeactivate())
            self.assertEqual(AppKit.NSWorkspace.sharedWorkspace().frontmostApplication().processIdentifier(),
                             finder[0].processIdentifier())

    def test_ipc_analysis_updates_existing_panel_and_minimize_during_work(self):
        main_thread = threading.get_ident()
        release = threading.Event()
        entered = threading.Event()
        worker_threads = []

        def analyze(session):
            worker_threads.append(threading.get_ident())
            entered.set()
            release.wait(3)
            return "Session Summary:\n- Hits: " + str(session["hits"]) + "\nStrengths:\n- Evidence\nWeaknesses:\n- Evidence\nNext Drill:\n- Practice"

        original_show_report = self.app.show_report

        def checked_show_report(report):
            self.assertEqual(threading.get_ident(), main_thread)
            original_show_report(report)

        self.app.show_report = checked_show_report
        with patch("coach_app.overlay.analyze_session", side_effect=analyze):
            self.commands.put(self.session(7))
            self.pump_until(lambda: entered.is_set())
            self.assertTrue(self.app.expanded)
            self.assertEqual(self.app.status_name, "Analyzing")
            self.assertEqual(self.app.stat_values["Accuracy"].get(), "70.0%")
            self.app.close()
            release.set()
            self.pump_until(lambda: self.app.status_name == "Report Ready")
            self.assertFalse(self.app.expanded)  # Completion doesn't override user minimize.
            self.assertIn("Hits: 7", self.app.report.get("1.0", "end"))
            self.commands.put(self.session(9))
            self.pump_until(lambda: self.app.stat_values["Hits"].get() == "9" and not self.app.busy)
            self.assertTrue(self.app.expanded)
            self.assertIn("Hits: 9", self.app.report.get("1.0", "end"))
        self.assertTrue(all(thread != main_thread for thread in worker_threads))


if __name__ == "__main__":
    unittest.main()
