"""Single-root floating companion. Only the main thread touches Tk widgets."""

import queue
import json
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from coach_app.camera_calibration import CameraCalibration, format_calibration_report

if __package__:
    from .controlled_assist import ControlledAssistController as AssistController
    from .nebius_client import AnalysisError, analyze_session
    from .macos_window import FloatingWindowPolicy
    from .report_format import SECTIONS, prepare_session
    from .session_reader import find_latest_session, read_session, select_session_file
else:
    from coach_app.controlled_assist import ControlledAssistController as AssistController
    from nebius_client import AnalysisError, analyze_session
    from macos_window import FloatingWindowPolicy
    from report_format import SECTIONS, prepare_session
    from session_reader import find_latest_session, read_session, select_session_file

BG, SURFACE, TEXT, MUTED, ACCENT = "#111923", "#1a2633", "#ecf2f7", "#9aaec0", "#58d6ed"
STATUS_COLORS = {"Ready": ACCENT, "Analyzing": "#f3c568", "Report Ready": "#78dfaa", "Error": "#ff8c94"}


class CoachWindow:
    def __init__(self, root: tk.Tk, session_path: str | None = None, commands=None) -> None:
        self.root, self.session_path, self.commands = root, session_path, commands
        self.assist = AssistController()
        self.calibration = CameraCalibration()
        self.last_calibration_report = None
        self.last_assist_completion = None
        self.coach_mode = 1
        self.current_path = self.pending_path = None
        self.results = queue.Queue()
        self.window_results = queue.Queue()
        self.window_choices = {}
        self.finding_windows = False
        self.busy = self.closed = self.expanded = False
        self.widget_position = (max(0, root.winfo_screenwidth() - 100), 120)
        self.panel_position = self.drag_start = None
        self.dragged = False
        self.status_name = "Ready"
        self.status = tk.StringVar(value="Ready")
        self.session_label = tk.StringVar(value="No session loaded")
        root.title("AI Aim Trainer Coach")
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.overrideredirect(True)
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.configure(bg=BG)
        self.floating_policy = FloatingWindowPolicy(root)
        self.build_widget()
        self.build_panel()
        root.bind("<Escape>", lambda _event: self.close())
        self.collapse()
        self.poll_id = root.after(100, self.poll_results)

    def build_widget(self) -> None:
        self.widget = tk.Canvas(self.root, width=64, height=64, bg=BG, highlightthickness=0, cursor="hand2")
        self.widget.create_oval(2, 2, 62, 62, fill=SURFACE, outline=ACCENT, width=2)
        self.widget.create_text(32, 29, text="AI", fill=TEXT, font=("Helvetica", 18, "bold"))
        self.indicator = self.widget.create_oval(43, 45, 55, 57, fill=ACCENT, outline=SURFACE, width=2)
        self.bind_drag(self.widget)

    def build_panel(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Coach.TButton", background=SURFACE, foreground=TEXT, padding=(10, 9), borderwidth=0)
        style.map("Coach.TButton", background=[("active", "#294455")], foreground=[("disabled", MUTED)])
        style.configure("Primary.Coach.TButton", background=ACCENT, foreground=BG)
        style.map("Primary.Coach.TButton", background=[("active", "#8ce6f5"), ("disabled", SURFACE)])
        style.configure("Coach.Vertical.TScrollbar", background=SURFACE, troughcolor=BG, borderwidth=0, arrowsize=12)
        self.panel = tk.Frame(self.root, bg=BG, padx=22, pady=18)
        header = tk.Frame(self.panel, bg=BG)
        header.pack(fill="x")
        title = tk.Label(header, text="AI AIM TRAINER", bg=BG, fg=TEXT, font=("Helvetica", 17, "bold"))
        title.pack(side="left")
        self.minimize_button = ttk.Button(header, text="Minimize", command=self.close, style="Coach.TButton")
        self.minimize_button.pack(side="right")
        self.bind_drag(header)
        self.bind_drag(title)
        tk.Label(self.panel, text="AI Performance Coach", bg=BG, fg=MUTED, font=("Helvetica", 11)).pack(anchor="w", pady=(2, 12))
        self.status_label = tk.Label(self.panel, textvariable=self.status, bg=BG, fg=ACCENT, font=("Helvetica", 11, "bold"))
        self.status_label.pack(anchor="w")
        tk.Label(self.panel, textvariable=self.session_label, bg=BG, fg=MUTED, font=("Helvetica", 10),
                 anchor="w", wraplength=432).pack(fill="x", pady=(3, 12))
        stats = tk.Frame(self.panel, bg=SURFACE, padx=12, pady=12)
        self.stats_frame = stats
        stats.pack(fill="x")
        self.stat_values = {}
        for index, name in enumerate(("Shots", "Hits", "Accuracy", "Average Reaction")):
            cell = tk.Frame(stats, bg=SURFACE)
            cell.grid(row=index // 2, column=index % 2, sticky="ew", padx=5, pady=5)
            stats.columnconfigure(index % 2, weight=1, uniform="stats")
            tk.Label(cell, text=name, bg=SURFACE, fg=MUTED, font=("Helvetica", 10)).pack(anchor="w")
            value = tk.StringVar(value="--")
            self.stat_values[name] = value
            tk.Label(cell, textvariable=value, bg=SURFACE, fg=TEXT, font=("Helvetica", 19, "bold")).pack(anchor="w")
        self.report_heading = tk.Label(self.panel, text="AI REPORT", bg=BG, fg=MUTED, font=("Helvetica", 10, "bold"))
        self.report_heading.pack(anchor="w", pady=(16, 8))
        report_frame = tk.Frame(self.panel, bg=BG)
        report_frame.pack(fill="both", expand=True)
        self.report = tk.Text(report_frame, bg=BG, fg=TEXT, insertbackground=TEXT, wrap="word",
                              font=("Helvetica", 12), relief="flat", highlightthickness=0,
                              spacing3=6, state="disabled", height=1)
        self.report.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(report_frame, command=self.report.yview, style="Coach.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.tag_configure("heading", foreground=ACCENT, font=("Helvetica", 12, "bold"), spacing1=10, spacing3=5)
        footer = tk.Frame(self.panel, bg=BG)
        # Reserve controls first; only the scrollable report yields vertical space.
        footer.pack(side="bottom", fill="x", pady=(12, 0), before=report_frame)
        tk.Label(footer, text="COACH MODE", bg=BG, fg=MUTED, font=("Helvetica", 9, "bold")).pack(anchor="w")
        self.mode_button = ttk.Menubutton(footer, text="Mode 1: Post-Session Review", style="Coach.TButton")
        self.mode_button.pack(fill="x", pady=(5, 8))
        self.mode_menu = tk.Menu(self.mode_button, tearoff=False)
        self.mode_menu.add_command(label="Mode 1: Post-Session Review", command=lambda: self.select_mode(1))
        self.mode_menu.add_command(label="Mode 2: Head Lock", command=lambda: self.select_mode(2))
        self.mode_button.configure(menu=self.mode_menu)
        self.assist_controls = tk.Frame(footer, bg=BG)
        self.assist_status = tk.StringVar(value="Assist: OFF")
        tk.Label(self.assist_controls, textvariable=self.assist_status, bg=BG, fg=ACCENT,
                 wraplength=430, height=5, anchor="nw", justify="left", font=("Helvetica", 10)).pack(fill="x")
        window_row = tk.Frame(self.assist_controls, bg=BG)
        window_row.pack(fill="x", pady=(2, 4))
        self.window_selection = tk.StringVar(value="Auto-detect Unity window")
        self.window_combo = ttk.Combobox(window_row, textvariable=self.window_selection,
                                         state="readonly", width=28, takefocus=True)
        self.window_combo.pack(side="left", fill="x", expand=True)
        self.window_combo.bind("<Button-1>", lambda event: self.focus_input(self.window_combo), add="+")
        self.window_combo.bind("<<ComboboxSelected>>", lambda event: self.assist_window_id.set(""))
        self.detect_windows_button = ttk.Button(window_row, text="Detect", command=self.detect_windows,
                                                style="Coach.TButton")
        self.detect_windows_button.pack(side="right", padx=(6, 0))
        row = tk.Frame(self.assist_controls, bg=BG)
        row.pack(fill="x", pady=4)
        tk.Label(row, text="Manual window ID:", bg=BG, fg=MUTED).pack(side="left")
        self.assist_window_id = tk.StringVar()
        validation = (self.root.register(lambda value: not value or value.isascii() and value.isdecimal()), "%P")
        self.window_id_entry = ttk.Entry(row, textvariable=self.assist_window_id, width=14,
                                         state="normal", takefocus=True, validate="key", validatecommand=validation)
        self.window_id_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.window_id_entry.bind("<Button-1>", lambda event: self.focus_input(self.window_id_entry), add="+")
        self.window_id_entry.bind("<Command-a>", self.select_window_id_text)
        self.window_id_entry.bind("<Control-a>", self.select_window_id_text)
        safety_row = tk.Frame(self.assist_controls, bg=BG)
        safety_row.pack(fill="x", pady=3)
        self.assist_dry_run = tk.BooleanVar(value=True)
        ttk.Checkbutton(safety_row, text="Dry run", variable=self.assist_dry_run,
                        command=self.confirm_live_assist).pack(side="left")
        tk.Label(safety_row, text="Deadzone px", bg=BG, fg=MUTED).pack(side="left", padx=(16, 4))
        self.assist_deadzone = tk.StringVar(value="8")
        deadzone = ttk.Spinbox(safety_row, from_=4, to=32, width=4, textvariable=self.assist_deadzone)
        deadzone.pack(side="left")
        deadzone.bind("<Button-1>", lambda event: self.focus_input(deadzone), add="+")
        buttons = tk.Frame(self.assist_controls, bg=BG)
        buttons.pack(fill="x", pady=6)
        self.start_assist_button = ttk.Button(buttons, text="Start Assist", command=self.start_assist, style="Coach.TButton")
        self.start_assist_button.pack(side="left", fill="x", expand=True)
        self.stop_assist_button = ttk.Button(buttons, text="Stop", command=self.stop_mode2, style="Coach.TButton")
        self.stop_assist_button.pack(side="right", fill="x", expand=True, padx=(8, 0))
        diagnostic_row = tk.Frame(self.assist_controls, bg=BG)
        diagnostic_row.pack(fill="x", pady=(0, 8))
        self.verify_camera_button = ttk.Button(diagnostic_row, text="Check Calibration",
                                               command=self.assist.verify, style="Coach.TButton")
        self.verify_camera_button.pack(side="left", fill="x", expand=True, ipady=3)
        self.calibrate_camera_button = ttk.Button(diagnostic_row, text="Calibrate Camera",
                                                  command=self.start_calibration, style="Coach.TButton")
        self.calibrate_camera_button.pack(side="right", fill="x", expand=True, padx=(8, 0), ipady=3)
        actions = tk.Frame(footer, bg=BG)
        actions.pack(fill="x")
        self.latest_button = ttk.Button(actions, text="Analyze Latest", command=self.load_latest, style="Primary.Coach.TButton")
        self.latest_button.pack(side="left", fill="x", expand=True)
        self.open_button = ttk.Button(actions, text="Open JSON", command=self.open_file, style="Coach.TButton")
        self.open_button.pack(side="right", padx=(8, 0))
        self.show_report("\n\n".join(section + ":\n--" for section in SECTIONS))

    def bind_drag(self, widget) -> None:
        widget.bind("<ButtonPress-1>", self.start_drag)
        widget.bind("<B1-Motion>", self.move_drag)
        widget.bind("<ButtonRelease-1>", self.end_drag)

    def select_mode(self, mode):
        self.stop_mode2()
        self.coach_mode = mode
        self.mode_button.configure(text="Mode 2: Head Lock" if mode == 2 else "Mode 1: Post-Session Review")
        if mode == 2:
            self.stats_frame.pack_forget()
            self.assist_controls.pack(fill="x", before=self.latest_button.master)
        else:
            self.assist_controls.pack_forget()
            self.stats_frame.pack(fill="x", before=self.report_heading)
        if self.expanded:
            self.size_panel()
        if mode == 2:
            self.detect_windows()

    def focus_input(self, widget):
        if self.expanded:
            self.floating_policy.focus_for_input(widget)

    def select_window_id_text(self, event):
        self.window_id_entry.selection_range(0, "end")
        self.window_id_entry.icursor("end")
        return "break"

    def detect_windows(self):
        if self.finding_windows or self.closed:
            return
        self.finding_windows = True
        self.detect_windows_button.configure(state="disabled")
        def find():
            try:
                from yolo_dev.capture_unity import unity_windows
                self.window_results.put((unity_windows(), None))
            except Exception as error:
                self.window_results.put(([], str(error)))
        threading.Thread(target=find, daemon=True).start()

    def update_windows(self):
        try:
            windows, error = self.window_results.get_nowait()
        except queue.Empty:
            return
        self.finding_windows = False
        self.detect_windows_button.configure(state="normal")
        previous = self.window_selection.get()
        self.window_choices = {f"{w['id']} | {w['app']} | {w['title'] or 'Untitled'}": w['id'] for w in windows}
        choices = list(self.window_choices)
        self.window_combo.configure(values=choices)
        if previous in self.window_choices:
            self.window_selection.set(previous)
        elif len(choices) == 1:
            self.window_selection.set(choices[0])
        else:
            self.window_selection.set("Choose Unity window" if choices else "No visible Unity window")
        if error:
            self.window_selection.set("Detection failed; use manual ID")
            print(f"[coach] Unity window inventory failed: {error}", flush=True)

    def start_assist(self):
        if self.coach_mode != 2:
            return
        if self.calibration.thread and self.calibration.thread.is_alive():
            return
        self.calibration.status = 'Calibration idle'
        try:
            value = self.assist_window_id.get().strip()
            window_id = int(value) if value else self.window_choices.get(self.window_selection.get())
            if not value and len(self.window_choices) > 1 and window_id is None:
                self.assist_status.set("Assist: OFF | Choose a detected Unity window or enter a manual ID.")
                return
            if window_id is not None and window_id <= 0:
                raise ValueError()
            if not self.assist.start(window_id, dry_run=self.assist_dry_run.get(),
                                     deadzone=float(self.assist_deadzone.get())):
                self.assist_status.set("Assist: OFF | Stop workers and confirm live separately after a dry run.")
        except ValueError:
            self.assist_status.set("Assist: OFF | Select Test3 and a deadzone from 4 to 32 pixels.")

    def confirm_live_assist(self):
        self.assist.stop()
        if self.assist_dry_run.get():
            return
        if self.assist.dry_proof is None:
            self.assist_dry_run.set(True)
            self.assist.detail = 'Complete a live-game dry run first. No input sent.'
            return
        approved = messagebox.askyesno('Enable bounded live correction?',
            'The next Start can send up to five small camera corrections in Test3 while RMB is held. '
            'F8 or Stop cancels. There is no automatic firing. Enable live mode?', parent=self.root)
        if not approved or not self.assist.confirm_live(): self.assist_dry_run.set(True)

    def stop_mode2(self):
        self.calibration.stop()
        self.assist.stop()
        if hasattr(self, 'assist_dry_run'): self.assist_dry_run.set(True)

    def start_calibration(self):
        if self.coach_mode != 2:
            return
        self.assist.stop()
        self.assist_dry_run.set(True)
        if any(worker and worker.is_alive() for worker in (self.assist.thread, self.assist.detector)):
            self.calibration.status = 'Wait for detector to stop, then click Calibrate Camera again.'
            return
        try:
            value = self.assist_window_id.get().strip()
            window_id = int(value) if value else self.window_choices.get(self.window_selection.get())
            if not window_id or window_id <= 0:
                raise ValueError()
            self.calibration.start(window_id)
        except ValueError:
            self.calibration.status = 'Select the standalone Test3 game window first.'

    def start_drag(self, event) -> None:
        self.drag_start = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self.dragged = False

    def move_drag(self, event) -> None:
        if self.drag_start is None:
            return
        x, y, window_x, window_y = self.drag_start
        dx, dy = event.x_root - x, event.y_root - y
        if abs(dx) + abs(dy) > 5:
            self.dragged = True
        if self.dragged:
            position = self.clamp_position(window_x + dx, window_y + dy, self.root.winfo_width(), self.root.winfo_height())
            self.root.geometry(f"+{position[0]}+{position[1]}")
            if self.expanded:
                self.panel_position = position
            else:
                self.widget_position = position

    def end_drag(self, _event) -> None:
        if not self.dragged and not self.expanded:
            self.show_window()
        self.drag_start = None

    def clamp_position(self, x, y, width, height):
        return (max(0, min(int(x), self.root.winfo_screenwidth() - width)),
                max(0, min(int(y), self.root.winfo_screenheight() - height)))

    def collapse(self) -> None:
        self.expanded = False
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.panel.pack_forget()
        self.widget.pack()
        x, y = self.clamp_position(*self.widget_position, 64, 64)
        self.root.geometry(f"64x64+{x}+{y}")
        if sys.platform == "darwin":
            try:
                self.root.configure(bg="systemTransparent")
                self.widget.configure(bg="systemTransparent")
                self.root.attributes("-transparent", True)
            except tk.TclError:
                pass
        self.root.deiconify()  # Never force focus while collapsed.
        self.floating_policy.schedule()

    def show_window(self) -> None:
        if self.expanded:
            self.root.deiconify()
            self.root.lift()
            self.floating_policy.schedule()
            return
        self.expanded = True
        # A native titled window can become key on macOS; the small widget stays borderless.
        self.root.withdraw()
        self.root.overrideredirect(False)
        self.widget.pack_forget()
        if sys.platform == "darwin":
            try:
                self.root.attributes("-transparent", False)
            except tk.TclError:
                pass
        self.root.configure(bg=BG)
        self.panel.pack(fill="both", expand=True)
        self.size_panel()
        self.root.deiconify()
        self.root.lift()
        self.floating_policy.schedule()

    def size_panel(self):
        width = min(480, self.root.winfo_screenwidth())
        height = min(760 if self.coach_mode == 2 else 650, self.root.winfo_screenheight() - 80)
        position = self.panel_position or (self.widget_position[0] - width + 64, self.widget_position[1])
        x, y = self.clamp_position(*position, width, height)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    def set_status(self, value: str) -> None:
        self.status_name = value
        self.status.set("Analyzing session..." if value == "Analyzing" else value)
        color = STATUS_COLORS[value]
        self.widget.itemconfigure(self.indicator, fill=color)
        self.status_label.configure(fg=color)

    def open_file(self) -> None:
        path = select_session_file(self.root)
        if path is not None:
            self.load(path)

    def load_latest(self) -> None:
        location = self.session_path or (self.current_path.parent if self.current_path else None)
        if location is None:
            self.open_file()
            return
        try:
            self.load(find_latest_session(location))
        except (OSError, ValueError) as error:
            self.set_status("Error")
            self.show_report(str(error))

    def load(self, path) -> None:
        if self.closed:
            return
        if self.busy:
            self.pending_path = Path(path)
            return
        self.show_window()
        try:
            session = read_session(path)
        except (OSError, ValueError) as error:
            self.set_status("Error")
            self.show_report(str(error))
            return
        self.current_path = Path(path)
        self.busy = True
        data = prepare_session(session)
        for label, key in (("Shots", "shots"), ("Hits", "hits"), ("Accuracy", "accuracy"), ("Average Reaction", "avg_reaction_ms")):
            self.stat_values[label].set(str(data[key]))
        self.session_label.set("Session " + str(session["session_id"])[:12])
        self.open_button.configure(state="disabled")
        self.latest_button.configure(state="disabled")
        self.set_status("Analyzing")
        self.show_report("Analyzing session...")
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
        self.update_windows()
        if self.calibration.thread and self.calibration.thread.is_alive():
            try:
                self.calibration.refresh_foreground()
            except Exception:
                # A failed main-thread observation must block posting, not retain stale focus.
                self.calibration.foreground_snapshot = {}
        if self.assist.thread and self.assist.thread.is_alive():
            try:
                self.assist.refresh_foreground()
            except Exception:
                self.assist.foreground_snapshot = {}
        assist_state, detail = self.assist.snapshot()
        if assist_state == 'OFF' and not self.assist.live_authorized and not self.assist.live_run:
            self.assist_dry_run.set(True)
        self.assist_status.set(self.calibration.status if self.calibration.status != 'Calibration idle'
                               else f"Assist: {assist_state} | {detail}")
        loop = self.assist.loop
        if self.coach_mode == 2 and loop and loop.done and loop is not self.last_assist_completion:
            self.last_assist_completion = loop
            self.show_report('Controlled Head Lock\n' + loop.text() + f'\nTelemetry: {self.assist.log_path}')
        calibration_report = self.calibration.report
        if calibration_report is not None and calibration_report is not self.last_calibration_report:
            self.last_calibration_report = calibration_report
            self.show_report(format_calibration_report(calibration_report))
        if self.commands is not None:
            while True:
                try:
                    self.pending_path = self.commands.get_nowait()
                    self.show_window()
                except queue.Empty:
                    break
        try:
            _path, report, error = self.results.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.open_button.configure(state="normal")
            self.latest_button.configure(state="normal")
            self.set_status("Error" if error else "Report Ready")
            self.show_report(error if error else report)
        if not self.busy and self.pending_path is not None:
            path, self.pending_path = self.pending_path, None
            self.load(path)
        self.poll_id = self.root.after(100, self.poll_results)

    def show_report(self, report: str) -> None:
        self.report.configure(state="normal")
        self.report.delete("1.0", "end")
        for line in report.splitlines():
            heading = line.strip().rstrip(":") in SECTIONS
            self.report.insert("end", line + "\n", "heading" if heading else "body")
        self.report.configure(state="disabled")
        self.report.yview_moveto(0)

    def close(self) -> None:
        self.collapse()  # IPC and workers remain alive in the same root/process.

    def shutdown(self):
        self.stop_mode2()
        self.closed = True
