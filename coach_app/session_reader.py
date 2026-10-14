"""Read exported files only; no screen or live gameplay capture."""

import json
from pathlib import Path
from typing import Any


def find_latest_session(path: str | Path) -> Path:
    location = Path(path).expanduser()
    if location.is_file():
        if location.suffix.lower() != ".json":
            raise ValueError("Please select a JSON file.")
        return location
    # Accept either Unity's persistentDataPath or its session_logs subdirectory.
    folder = location / "session_logs" if (location / "session_logs").is_dir() else location
    if not folder.is_dir():
        raise FileNotFoundError(f"Session folder does not exist: {folder}")
    files = [candidate for candidate in folder.glob("*.json") if candidate.is_file()]
    if not files:
        raise FileNotFoundError(f"No session JSON files found in {folder}")
    return max(files, key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.name))


def select_session_file(parent: Any = None) -> Path | None:
    from tkinter import filedialog

    selected = filedialog.askopenfilename(
        parent=parent,
        title="Select Unity session JSON",
        filetypes=[("Session JSON", "*.json")],
    )
    return Path(selected) if selected else None


def read_session(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8-sig") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError("Session JSON must contain an object.")
    required = {
        "session_id", "started_at", "ended_at", "shots", "hits", "misses",
        "accuracy", "avg_reaction_ms", "shots_detail",
    }
    missing = required - data.keys()
    if missing:
        raise ValueError("Missing session fields: " + ", ".join(sorted(missing)))
    if not isinstance(data["shots_detail"], list):
        raise ValueError("shots_detail must be an array.")
    return data
