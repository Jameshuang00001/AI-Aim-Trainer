"""Loopback-only commands. HTTP threads enqueue work; only Tk touches the UI."""

import hmac
import json
import queue
import threading
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
        self.token = token
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
        if self.path != "/health":
            self.reply(404, {"error": "Unknown command"})
            return
        available, error = credential_status()
        self.reply(200, {"app": "aim-trainer-coach", "protocol": 1,
                         "api_key_available": available, "credential_error": error})

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
