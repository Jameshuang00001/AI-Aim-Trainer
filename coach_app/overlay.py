"""Minimal Coach: session reports and Unity-owned Mode 2 control."""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from coach_app.nebius_client import analyze_session
from coach_app.session_reader import read_session, select_session_file, find_latest_session

class CoachWindow:
    def __init__(self, root, session_path=None, commands=None, server=None):
        self.root, self.session_path, self.commands, self.server = root, session_path, commands, server
        self.closed = self.busy = False
        self.results = queue.Queue()
        root.title("AI Aim Trainer Coach")
        root.geometry("480x600")
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.mode = tk.StringVar(value="Mode 1 Coach")
        ttk.OptionMenu(root, self.mode, self.mode.get(), "Mode 1 Coach", "Mode 2 Unity Assist", command=self.change_mode).pack(fill="x", padx=12, pady=8)
        row = ttk.Frame(root); row.pack(fill="x", padx=12)
        ttk.Button(row, text="Open session", command=self.open_file).pack(side="left")
        ttk.Button(row, text="Latest session", command=self.load_latest).pack(side="left")
        self.controls = ttk.Frame(root)
        ttk.Label(self.controls, text="Unity data · Hold RMB · F8 / ESC stops · No auto fire").pack()
        ttk.Button(self.controls, text="Start Assist", command=self.start_assist).pack(side="left")
        ttk.Button(self.controls, text="Stop", command=self.stop_mode2).pack(side="left")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(root, textvariable=self.status, wraplength=450).pack(fill="x", padx=12, pady=8)
        self.report = tk.Text(root, wrap="word", state="disabled")
        self.report.pack(fill="both", expand=True, padx=12, pady=8)
        root.bind("<Escape>", lambda e: self.stop_mode2())
        root.bind("<F8>", lambda e: self.stop_mode2())
        self.poll_id = root.after(100, self.poll_results)
    def change_mode(self, value):
        self.stop_mode2()
        if value == "Mode 2 Unity Assist": self.controls.pack(fill="x", padx=12, before=self.report)
        else: self.controls.pack_forget()
    def start_assist(self):
        if self.server:
            self.server.assist_sequence += 1
            self.server.assist_enabled = True
    def stop_mode2(self):
        if self.server:
            self.server.assist_enabled = False
            self.server.assist_sequence += 1
    def open_file(self):
        path = select_session_file(self.root)
        if path: self.load(path)
    def load_latest(self):
        if not self.session_path: self.open_file(); return
        try: self.load(find_latest_session(self.session_path))
        except (OSError, ValueError) as error: self.show_report(str(error))
    def show_report(self, text):
        self.report.configure(state="normal"); self.report.delete("1.0", "end")
        self.report.insert("end", text); self.report.configure(state="disabled")
    def load(self, path):
        if self.busy: return
        try: session = read_session(path)
        except (OSError, ValueError) as error: self.show_report(str(error)); return
        self.session_path = str(Path(path).parent)
        self.busy = True
        self.root.deiconify()
        self.status.set("Analyzing session...")
        def worker():
            try: result = analyze_session(session)
            except Exception as error: result = str(error)
            self.results.put(result)
        threading.Thread(target=worker, daemon=True).start()
    def poll_results(self):
        if self.closed: return
        if self.server and self.mode.get() == "Mode 2 Unity Assist":
            fresh = time.monotonic() - self.server.assist_seen < 1
            self.status.set(self.server.assist_status if fresh else "Unity disconnected")
            if not fresh and self.server.assist_enabled: self.stop_mode2()
        try:
            self.show_report(self.results.get_nowait()); self.busy = False
            self.status.set("Report ready")
        except queue.Empty: pass
        if self.commands is not None and not self.busy:
            try: self.load(self.commands.get_nowait())
            except queue.Empty: pass
        self.poll_id = self.root.after(100, self.poll_results)
    def close(self):
        self.stop_mode2(); self.root.iconify()
    def shutdown(self):
        self.stop_mode2(); self.closed = True
