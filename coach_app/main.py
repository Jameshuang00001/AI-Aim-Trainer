"""Launch the local coach UI with Python 3.10+."""

import argparse
import tkinter as tk

if __package__:
    from .overlay import CoachWindow
else:
    from overlay import CoachWindow


def main() -> None:
    parser = argparse.ArgumentParser(description="Local Unity session coach")
    parser.add_argument(
        "--session-path",
        help="Unity persistentDataPath directory, session_logs directory, or JSON file",
    )
    args = parser.parse_args()
    root = tk.Tk()
    CoachWindow(root, args.session_path)
    root.mainloop()


if __name__ == "__main__":
    main()
