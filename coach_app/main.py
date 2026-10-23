"""Launch the local coach UI with Python 3.10+."""

import argparse
import os
import sys
from pathlib import Path
import tkinter as tk

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __package__:
    from .overlay import CoachWindow
    from .ipc_server import CoachServer
else:
    from overlay import CoachWindow
    from ipc_server import CoachServer


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Unity session coach")
    parser.add_argument(
        "--session-path",
        help="Unity persistentDataPath directory, session_logs directory, or JSON file",
    )
    parser.add_argument("--ipc-port", type=int)
    parser.add_argument("--ipc-token")
    parser.add_argument("--launch-id")
    parser.add_argument("--project-root")
    args = parser.parse_args()
    for name, value in (("COACH_IPC_PORT", args.ipc_port), ("COACH_IPC_TOKEN", args.ipc_token),
                        ("COACH_LAUNCH_ID", args.launch_id), ("COACH_APP_ROOT", args.project_root)):
        if value is not None:
            os.environ[name] = str(value)
    if getattr(sys, "frozen", False):
        directory = Path.home() / "Library/Logs/AI-Aim-Trainer"
        directory.mkdir(parents=True, exist_ok=True)
        stream = (directory / "coach-app.log").open("a", buffering=1, encoding="utf-8")
        sys.stdout = sys.stderr = stream
    # Bind before creating a window: a second launcher cannot create a duplicate UI.
    try:
        server = CoachServer(int(os.environ.get("COACH_IPC_PORT", "8765")),
                             os.environ.get("COACH_IPC_TOKEN", ""))
    except OSError:
        print("[coach] IPC port already in use; not starting a duplicate Coach.", flush=True)
        return
    app = None
    try:
        root = tk.Tk()
        app = CoachWindow(root, args.session_path, server.commands, server=server)
        # Unity's background launch now shows the collapsed companion, not a hidden window.
        server.start()
        def check_shutdown():
            if server.shutdown_requested.is_set():
                app.shutdown()
                root.destroy()
                return
            root.after(100, check_shutdown)
        root.after(100, check_shutdown)
        root.mainloop()
    finally:
        if app is not None:
            app.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
