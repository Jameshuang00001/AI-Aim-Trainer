"""Local JSONL correction telemetry. No screenshots, secrets, or network uploads."""

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid


class CorrectionLog:
    def __init__(self, directory=None):
        directory = Path(directory or Path.home() / "Library/Logs/AI-Aim-Trainer/assist")
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"assist-{uuid.uuid4().hex}.jsonl"
        self.file = self.path.open("x", encoding="utf-8")

    def write(self, event):
        row = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
        self.file.write(json.dumps(row, allow_nan=False) + "\n")
        self.file.flush()

    def close(self):
        self.file.close()
