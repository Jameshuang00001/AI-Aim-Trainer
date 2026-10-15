"""Launch the local coach UI with Python 3.10+."""

import argparse
import os
import tkinter as tk

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
    args = parser.parse_args()
    # Bind before creating a window: a second launcher cannot create a duplicate UI.
    try:
        server = CoachServer(int(os.environ.get("COACH_IPC_PORT", "8765")),
                             os.environ.get("COACH_IPC_TOKEN", ""))
    except OSError:
        print("[coach] IPC port already in use; not starting a duplicate Coach.", flush=True)
        return
    try:
        root = tk.Tk()
        CoachWindow(root, args.session_path, server.commands)
        if os.environ.get("COACH_START_HIDDEN") == "1":
            root.withdraw()
        server.start()
        root.mainloop()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
