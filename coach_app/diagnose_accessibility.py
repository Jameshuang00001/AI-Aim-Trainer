"""Read-only macOS AX diagnostics. No input events, prompts, or TCC changes.

Run: .venv/bin/python -m coach_app.diagnose_accessibility
Run the same command with base Python to compare launch contexts.
"""

import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys

if __package__:
    from .macos_input import accessibility_trusted
else:
    from macos_input import accessibility_trusted

LIBRARY = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"


def process_ancestry():
    """Only executable names and PIDs; never argv, environment or credentials."""
    rows = []
    pid = os.getpid()
    for _ in range(8):
        try:
            result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "ppid=", "-o", "comm="],
                                    capture_output=True, text=True, timeout=2, check=False)
            fields = result.stdout.strip().split(maxsplit=1)
            if result.returncode or len(fields) != 2:
                break
            parent = int(fields[0])
            rows.append({"pid": pid, "parent_pid": parent, "executable": fields[1]})
            if parent <= 0 or parent == pid:
                break
            pid = parent
        except (OSError, ValueError, subprocess.TimeoutExpired):
            break
    return rows


def diagnose():
    if sys.platform != "darwin":
        raise RuntimeError("Accessibility diagnostics require macOS")
    # The primary answer is the EXACT function used by MacMouseBackend.
    trusted = accessibility_trusted()
    # Boolean in AXUIElement.h is an unsigned byte. Independently check the ABI
    # interpretation without changing Coach's permission policy or prompting.
    services = ctypes.CDLL(LIBRARY)
    services.AXIsProcessTrusted.restype = ctypes.c_ubyte
    services.AXIsProcessTrusted.argtypes = []
    raw = services.AXIsProcessTrusted()
    from Foundation import NSBundle
    return {
        "bundle_identifier": NSBundle.mainBundle().bundleIdentifier(),
        "frozen": bool(getattr(sys, 'frozen', False)),
        "api": "ApplicationServices.AXIsProcessTrusted()",
        "library": LIBRARY,
        "coach_accessibility_trusted": trusted,
        "raw_boolean": raw,
        "boolean_interpretations_agree": trusted == bool(raw),
        "sys_executable": sys.executable,
        "resolved_executable": str(Path(sys.executable).resolve()),
        "base_executable": getattr(sys, "_base_executable", None),
        "python_version": sys.version.split()[0],
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "process_ancestry": process_ancestry(),
        "authorization_result": "authorized_for_this_process" if trusted else "not_authorized_for_this_process",
        "limitation": "AX reports only this process's trust, not which TCC entry or responsible host caused denial. "
                      "Terminal/Codex results alone do not establish Unity-launched Coach authorization.",
        "input_events_posted": False,
        "permission_prompt_requested": False,
    }


def save_report(report, directory=None):
    """Keep the actual Coach's report readable even when Unity discards stdout."""
    directory = Path(directory or Path.home() / "Library/Logs/AI-Aim-Trainer")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "accessibility-diagnostic.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return path


def main():
    try:
        print(json.dumps(diagnose(), indent=2))
    except (OSError, RuntimeError) as error:
        print(f"Accessibility diagnostic failed: {error}", file=sys.stderr)
        return 2
    return 0  # A denied trust result is diagnostic data, not a failed command.


if __name__ == "__main__":
    raise SystemExit(main())
