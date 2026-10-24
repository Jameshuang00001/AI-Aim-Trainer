"""Minimal Coach: session reports and Unity-owned Mode 2 control."""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from coach_app.nebius_client import analyze_session
from coach_app.report_format import prepare_session
from coach_app.macos_window import FloatingWindowPolicy
from coach_app.session_reader import read_session, select_session_file, find_latest_session

class CoachWindow:
    def __init__(self, root, session_path=None, commands=None, server=None):
        self.root, self.session_path, self.commands, self.server = root, session_path, commands, server
        self.closed = self.busy = False
        self.results = queue.Queue()
        root.title("AI Coach")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.geometry(f"64x64+{max(0, root.winfo_screenwidth()-100)}+120")
        self.panel = tk.Toplevel(root)
        self.panel.title("AI Aim Trainer Coach")
        self.panel.geometry("480x760")
        self.panel.attributes("-topmost", True)
        self.panel.protocol("WM_DELETE_WINDOW", self.close)
        self.panel.configure(bg="#111923")
        style = ttk.Style(root); style.theme_use("clam")
        style.configure("TFrame", background="#111923")
        style.configure("TLabel", background="#111923", foreground="#9aaec0", font=("Helvetica", 11))
        style.configure("TButton", background="#1a2633", foreground="#ecf2f7", padding=(10,8), borderwidth=0)
        style.map("TButton", background=[("active", "#294455")])
        style.configure("TMenubutton", background="#1a2633", foreground="#58d6ed", padding=(10,8))
        style.configure("Horizontal.TScale", background="#111923", troughcolor="#1a2633")
        tk.Label(self.panel, text="AI AIM TRAINER", font=("Helvetica", 18, "bold"),
                 bg="#111923", fg="#ecf2f7").pack(anchor="w", padx=16, pady=(18,2))
        tk.Label(self.panel, text="AI Performance Coach", font=("Helvetica",11),
                 bg="#111923", fg="#58d6ed").pack(anchor="w", padx=16, pady=(0,10))
        self.panel.withdraw()
        self.floating_policies = [FloatingWindowPolicy(root), FloatingWindowPolicy(self.panel)]
        self.bubble = tk.Canvas(root, width=64, height=64, bg="#111923", highlightthickness=0, cursor="hand2")
        self.bubble.create_oval(3,3,61,61, fill="#1a2633", outline="#58d6ed", width=2)
        self.bubble.create_text(32,32,text="AI",fill="#58d6ed",font=("Helvetica",19,"bold"))
        self.bubble.pack(fill="both", expand=True)
        self.bubble.bind("<ButtonPress-1>", self.drag_start)
        self.bubble.bind("<B1-Motion>", self.drag_move)
        self.bubble.bind("<ButtonRelease-1>", self.drag_end)
        root.after_idle(self.show_companion)
        self.mode = tk.StringVar(value="Mode 1 Coach")
        ttk.OptionMenu(self.panel, self.mode, self.mode.get(), "Mode 1 Coach", "Mode 2 Unity Assist", command=self.change_mode).pack(fill="x", padx=12, pady=8)
        row = ttk.Frame(self.panel); row.pack(fill="x", padx=12)
        ttk.Button(row, text="Open session", command=self.open_file).pack(side="left")
        ttk.Button(row, text="Latest session", command=self.load_latest).pack(side="left")
        stats = ttk.Frame(self.panel); stats.pack(fill="x", padx=16, pady=8)
        self.stat_values = {}
        for index, name in enumerate(("Shots", "Hits", "Accuracy", "Avg reaction")):
            cell = tk.Frame(stats, bg="#1a2633", padx=10, pady=8)
            cell.grid(row=index//2,column=index%2,sticky="ew",padx=3,pady=3)
            stats.columnconfigure(index%2,weight=1)
            tk.Label(cell,text=name,bg="#1a2633",fg="#9aaec0",font=("Helvetica",10)).pack(anchor="w")
            value=tk.StringVar(value="—");self.stat_values[name]=value
            tk.Label(cell,textvariable=value,bg="#1a2633",fg="#ecf2f7",font=("Helvetica",15,"bold")).pack(anchor="w")
        self.controls = ttk.Frame(self.panel)
        self.assist_kind = tk.StringVar(value="Hold RMB")
        ttk.OptionMenu(self.controls, self.assist_kind, self.assist_kind.get(), "Hold RMB", "Proximity magnet", command=lambda _: self.stop_mode2()).pack(fill="x")
        self.radius = tk.DoubleVar(value=3.0)
        self.radius_text = tk.StringVar(value="Assist zone: 3.0 deg")
        ttk.Label(self.controls, textvariable=self.radius_text).pack(anchor="w")
        ttk.Scale(self.controls, from_=0.5, to=10, variable=self.radius, command=self.radius_changed).pack(fill="x")
        self.speed = tk.DoubleVar(value=65)
        self.speed_text = tk.StringVar(value="Assist speed: 65 deg/s")
        ttk.Label(self.controls, textvariable=self.speed_text).pack(anchor="w")
        ttk.Scale(self.controls, from_=5, to=180, variable=self.speed, command=self.speed_changed).pack(fill="x")
        ttk.Label(self.controls, text="F8 / ESC stops · Manual firing only").pack()
        ttk.Button(self.controls, text="Start Assist", command=self.start_assist).pack(side="left")
        ttk.Button(self.controls, text="Stop", command=self.stop_mode2).pack(side="left")
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self.panel, textvariable=self.status, wraplength=450).pack(fill="x", padx=12, pady=8)
        self.calibration = tk.StringVar(value="No corrections yet")
        ttk.Label(self.panel, textvariable=self.calibration, wraplength=440).pack(fill="x", padx=16, pady=6)
        self.report_frame = ttk.Frame(self.panel)
        self.report_frame.pack(fill="both", expand=True, padx=12, pady=8)
        self.report = tk.Text(self.report_frame, wrap="word", state="disabled", bg="#1a2633", fg="#ecf2f7",
                              font=("Helvetica", 12), padx=14, pady=14, relief="flat")
        scrollbar = ttk.Scrollbar(self.report_frame, orient="vertical", command=self.report.yview)
        scrollbar.pack(side="right", fill="y")
        self.report.configure(yscrollcommand=scrollbar.set)
        self.report.pack(side="left", fill="both", expand=True)
        self.panel.bind("<Escape>", lambda e: self.stop_mode2())
        self.panel.bind("<F8>", lambda e: self.stop_mode2())
        self.poll_id = root.after(100, self.poll_results)
    def speed_changed(self, value):
        self.speed_text.set(f"Assist speed: {float(value):.0f} deg/s")
        if self.server: self.server.assist_speed = float(value)
    def radius_changed(self, value):
        self.radius_text.set(f"Assist zone: {float(value):.1f} deg")
        self.stop_mode2()
    def change_mode(self, value):
        self.stop_mode2()
        if value == "Mode 2 Unity Assist": self.controls.pack(fill="x", padx=12, before=self.report_frame)
        else: self.controls.pack_forget()
    def start_assist(self):
        if self.server:
            self.server.assist_mode = "proximity" if self.assist_kind.get() == "Proximity magnet" else "hold"
            self.server.assist_radius = float(self.radius.get())
            self.server.assist_speed = float(self.speed.get())
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
        data = prepare_session(session)
        for label,key in (("Shots","shots"),("Hits","hits"),("Accuracy","accuracy"),("Avg reaction","avg_reaction_ms")):
            self.stat_values[label].set(str(data[key]))
        self.session_path = str(Path(path).parent)
        self.busy = True
        self.show_window()
        self.status.set("Analyzing session...")
        def worker():
            try: result = analyze_session(session)
            except Exception as error: result = str(error)
            self.results.put(result)
        threading.Thread(target=worker, daemon=True).start()
    def poll_results(self):
        if self.closed: return
        if self.server:
            native = self.floating_policies[0].window
            self.server.companion_visible = bool(self.root.winfo_viewable() and (native is None or native.isVisible()))
            self.server.companion_floating = bool(native is not None and native.level() >= self.floating_policies[0].appkit.NSFloatingWindowLevel)
        if self.server and self.server.show_requested.is_set():
            self.server.show_requested.clear()
            self.show_companion()
        if self.server and self.mode.get() == "Mode 2 Unity Assist":
            fresh = time.monotonic() - self.server.assist_seen < 1
            self.status.set(self.server.assist_status if fresh else "Unity disconnected")
            self.calibration.set(self.server.assist_feedback if fresh else "")
            if not fresh and self.server.assist_enabled: self.stop_mode2()
        try:
            self.show_report(self.results.get_nowait()); self.busy = False
            self.status.set("Report ready")
        except queue.Empty: pass
        if self.commands is not None and not self.busy:
            try: self.load(self.commands.get_nowait())
            except queue.Empty: pass
        self.poll_id = self.root.after(100, self.poll_results)
    def show_companion(self):
        self.root.deiconify(); self.root.lift()
        self.floating_policies[0].schedule()
    def show_window(self):
        self.panel.deiconify(); self.panel.lift()
        self.floating_policies[1].schedule()
    def drag_start(self, event):
        self.drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())
        self.dragged = False
    def drag_move(self, event):
        x, y, left, top = self.drag_origin
        dx, dy = event.x_root-x, event.y_root-y
        if abs(dx)+abs(dy) > 5: self.dragged = True
        if self.dragged: self.root.geometry(f"+{max(0,left+dx)}+{max(0,top+dy)}")
    def drag_end(self, event):
        if not self.dragged: self.show_window()
    def close(self):
        self.stop_mode2(); self.panel.withdraw(); self.show_companion()
    def shutdown(self):
        self.stop_mode2(); self.closed = True
