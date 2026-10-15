"""Simple always-on-top Tkinter UI; reports display as plain Markdown text."""

import tkinter as tk
import queue
import threading
import os
import subprocess
import sys
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

if __package__:
    from .nebius_client import AnalysisError, analyze_session
    from .session_reader import find_latest_session, read_session, select_session_file
else:
    from nebius_client import AnalysisError, analyze_session
    from session_reader import find_latest_session, read_session, select_session_file


class CoachWindow:
    def __init__(self, root: tk.Tk, session_path: str | None = None, commands=None) -> None:
        self.root = root
        self.session_path = session_path
        self.results = queue.Queue()
        self.busy = False
        self.closed = False
        self.commands = commands
        self.pending_path = None
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.title("Aim Trainer Coach")
        root.geometry("580x460")
        root.minsize(400, 300)
        root.attributes("-topmost", True)
        controls = ttk.Frame(root, padding=12)
        controls.pack(fill="x")
        self.open_button = ttk.Button(controls, text="Open JSON", command=self.open_file)
        self.open_button.pack(side="left")
        self.latest_button = ttk.Button(
            controls, text="Load Latest", command=self.load_latest,
            state="normal" if session_path else "disabled",
        )
        self.latest_button.pack(side="left", padx=8)
        self.status = tk.StringVar(value="No session loaded")
        ttk.Label(root, textvariable=self.status, wraplength=550, padding=12).pack(fill="x")
        self.report = ScrolledText(root, wrap="word", padx=12, pady=12, state="disabled")
        self.report.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        if session_path:
            root.after_idle(self.load_latest)
        self.poll_id = root.after(100, self.poll_results)

    def open_file(self) -> None:
        path = select_session_file(self.root)
        if path is not None:
            self.load(path)

    def load_latest(self) -> None:
        try:
            self.load(find_latest_session(self.session_path))
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot load session", str(error), parent=self.root)

    def load(self, path) -> None:
        if self.busy or self.closed:
            return
        try:
            session = read_session(path)
        except (OSError, ValueError) as error:
            messagebox.showerror("Cannot load session", str(error), parent=self.root)
            return
        self.busy = True
        self.open_button.configure(state="disabled")
        self.latest_button.configure(state="disabled")
        self.status.set("Requesting Nebius analysis: " + str(path))
        self.show_report("Analyzing session...")
        # Workers never touch Tk widgets; the main thread polls a result queue.
        threading.Thread(target=self.analyze_worker, args=(session, path), daemon=True).start()

    def analyze_worker(self, session, path) -> None:
        try:
            self.results.put((path, analyze_session(session), None))
        except AnalysisError as error:
            self.results.put((path, None, str(error)))
        except Exception as error:
            print(f"[coach] Worker failure: {type(error).__name__} (details suppressed for privacy)", flush=True)
            self.results.put((path, None, f"Analysis failed ({type(error).__name__}). See Terminal diagnostics."))

    def poll_results(self) -> None:
        if self.closed:
            return
        if self.commands is not None:
            while True:
                try:
                    self.pending_path = self.commands.get_nowait()
                    self.show_window()
                except queue.Empty:
                    break
        try:
            path, report, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.open_button.configure(state="normal")
            self.latest_button.configure(state="normal" if self.session_path else "disabled")
            self.status.set(("Analysis failed: " if error else "Nebius report ready: ") + str(path))
            self.show_report(error if error else report)
        if not self.busy and self.pending_path is not None:
            path, self.pending_path = self.pending_path, None
            self.load(path)
        self.poll_id = self.root.after(100, self.poll_results)

    def show_report(self, report: str) -> None:
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        self.report.insert("1.0", report)
        self.report.configure(state="disabled")

    def close(self) -> None:
        # Keep IPC and in-flight analysis alive for the next Unity report.
        self.root.withdraw()

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        if sys.platform == "darwin":
            # Foreground this Coach process only, never manipulate the Unity window.
            script = ('tell application "System Events" to set frontmost of '
                      f'first application process whose unix id is {os.getpid()} to true')
            try:
                subprocess.Popen(["/usr/bin/osascript", "-e", script],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass  # Tk lift/focus still applies if macOS denies activation.
