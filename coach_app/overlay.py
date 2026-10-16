"""Single-root floating companion. Only the main thread touches Tk widgets."""

import queue
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk

if __package__:
    from .nebius_client import AnalysisError, analyze_session
    from .macos_window import FloatingWindowPolicy
    from .report_format import SECTIONS, prepare_session
    from .session_reader import find_latest_session, read_session, select_session_file
else:
    from nebius_client import AnalysisError, analyze_session
    from macos_window import FloatingWindowPolicy
    from report_format import SECTIONS, prepare_session
    from session_reader import find_latest_session, read_session, select_session_file

BG, SURFACE, TEXT, MUTED, ACCENT = "#111923", "#1a2633", "#ecf2f7", "#9aaec0", "#58d6ed"
STATUS_COLORS = {"Ready": ACCENT, "Analyzing": "#f3c568", "Report Ready": "#78dfaa", "Error": "#ff8c94"}


class CoachWindow:
    def __init__(self, root: tk.Tk, session_path: str | None = None, commands=None) -> None:
        self.root, self.session_path, self.commands = root, session_path, commands
        self.current_path = self.pending_path = None
        self.results = queue.Queue()
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
        tk.Label(self.panel, text="AI REPORT", bg=BG, fg=MUTED, font=("Helvetica", 10, "bold")).pack(anchor="w", pady=(16, 8))
        report_frame = tk.Frame(self.panel, bg=BG)
        report_frame.pack(fill="both", expand=True)
        self.report = tk.Text(report_frame, bg=BG, fg=TEXT, insertbackground=TEXT, wrap="word",
                              font=("Helvetica", 12), relief="flat", highlightthickness=0,
                              spacing3=6, state="disabled", height=8)
        self.report.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(report_frame, command=self.report.yview, style="Coach.Vertical.TScrollbar")
        scrollbar.pack(side="right", fill="y")
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.tag_configure("heading", foreground=ACCENT, font=("Helvetica", 12, "bold"), spacing1=10, spacing3=5)
        footer = tk.Frame(self.panel, bg=BG)
        footer.pack(fill="x", pady=(12, 0))
        tk.Label(footer, text="COACH MODE", bg=BG, fg=MUTED, font=("Helvetica", 9, "bold")).pack(anchor="w")
        self.mode_button = ttk.Menubutton(footer, text="Mode 1: Post-Session Review", style="Coach.TButton")
        self.mode_button.pack(fill="x", pady=(5, 8))
        self.mode_menu = tk.Menu(self.mode_button, tearoff=False)
        self.mode_menu.add_command(label="Mode 1: Post-Session Review", command=lambda: None)
        self.mode_menu.add_command(label="Mode 2: Guided Aim - Coming Soon", state="disabled")
        self.mode_button.configure(menu=self.mode_menu)
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
        self.widget.pack_forget()
        if sys.platform == "darwin":
            try:
                self.root.attributes("-transparent", False)
            except tk.TclError:
                pass
        self.root.configure(bg=BG)
        self.panel.pack(fill="both", expand=True)
        width = min(480, self.root.winfo_screenwidth())
        height = min(650, self.root.winfo_screenheight() - 40)
        position = self.panel_position or (self.widget_position[0] - width + 64, self.widget_position[1])
        x, y = self.clamp_position(*position, width, height)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.deiconify()
        self.root.lift()  # Native Tk only: no AppleScript or Accessibility access.
        self.floating_policy.schedule()

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
