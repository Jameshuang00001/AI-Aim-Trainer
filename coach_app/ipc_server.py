"""Loopback-only commands. HTTP threads enqueue work; only Tk touches the UI."""

import hmac
import json
import queue
import threading
import os
import time
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

if __package__:
    from .credentials import credential_status
else:
    from credentials import credential_status


class CoachServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port: int, token: str = "") -> None:
        self.commands = queue.Queue()
        self.assist_enabled = False
        self.assist_sequence = 0
        self.assist_mode = "hold"
        self.show_requested = threading.Event()
        self.companion_visible = False
        self.companion_floating = False
        self.assist_status = "Unity disconnected"
        self.assist_seen = 0.0
        self.token = token
        self.launch_id = os.environ.get("COACH_LAUNCH_ID", "")
        self.shutdown_requested = threading.Event()
        super().__init__(("127.0.0.1", port), Handler)

    def start(self) -> None:
        threading.Thread(target=self.serve_forever, daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass  # Never log authentication headers or session data.

    def reply(self, status: int, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/assist":
            if self.headers.get("Origin") or self.headers.get("Sec-Fetch-Site") or not hmac.compare_digest(
                self.headers.get("X-Coach-Token", "").encode(), self.server.token.encode()):
                self.reply(403, {"error": "Forbidden"})
                return
            self.server.assist_status = parse_qs(urlparse(self.path).query).get("status", ["OFF"])[0][:64]
            self.server.assist_seen = time.monotonic()
            self.reply(200, {"enabled": self.server.assist_enabled, "sequence": self.server.assist_sequence, "mode": self.server.assist_mode})
            return
        if urlparse(self.path).path != "/health":
            self.reply(404, {"error": "Unknown command"})
            return
        startup = parse_qs(urlparse(self.path).query).get("startup") == ["1"]
        available, error = (False, "") if startup else credential_status()
        self.reply(200, {"app": "aim-trainer-coach", "protocol": 1,
                         "process_id": os.getpid(), "launch_id": self.server.launch_id,
                         "companion_visible": self.server.companion_visible,
                         "companion_floating": self.server.companion_floating,
                         "api_key_checked": not startup, "api_key_available": available, "credential_error": error})

    def do_POST(self) -> None:
        self.connection.settimeout(3)
        # No browser-origin requests, CORS, or external interfaces.
        if self.headers.get("Origin") or self.headers.get("Sec-Fetch-Site"):
            self.reply(403, {"error": "Browser requests are not allowed"})
            return
        token = self.headers.get("X-Coach-Token", "")
        if not hmac.compare_digest(token.encode(), self.server.token.encode()):
            self.reply(403, {"error": "Coach IPC token mismatch"})
            return
        if self.path == "/show":
            self.server.show_requested.set()
            self.reply(200, {"shown": True})
            return
        if self.path == "/shutdown":
            # Only a Unity-owned launch may accept its authenticated shutdown.
            if not self.server.launch_id or not self.server.token:
                self.reply(403, {"error": "Not an owned launch"})
                return
            self.server.shutdown_requested.set()
            self.reply(200, {"stopping": True})
            return
        if self.path != "/analyze":
            self.reply(404, {"error": "Unknown command"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 16384:
                raise ValueError("Invalid request size")
            data = json.loads(self.rfile.read(size))
            path = Path(data["path"]).expanduser()
            if not path.is_absolute() or path.suffix.lower() != ".json" or not path.is_file():
                raise ValueError("An existing absolute JSON path is required")
            self.server.commands.put(path)
        except (OSError, ValueError, KeyError, TypeError):
            self.reply(400, {"error": "Invalid session JSON path or request"})
            return
        self.reply(202, {"accepted": True})
