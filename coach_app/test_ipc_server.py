"""Loopback integration tests; no GUI or Nebius calls."""

import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from coach_app.ipc_server import CoachServer


class IPCTests(unittest.TestCase):
    def setUp(self):
        self.keychain = patch("coach_app.credentials.macos_backend")
        self.keychain.start().return_value.get_password.return_value = None
        self.addCleanup(self.keychain.stop)
        self.server = CoachServer(0, "test-token")
        self.server.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "session.json"
        self.path.write_text("{}")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.directory.cleanup()

    def request(self, token="test-token", origin=None, path=None):
        headers = {"Content-Type": "application/json", "X-Coach-Token": token}
        if origin:
            headers["Origin"] = origin
        return urlopen(Request(self.url + "/analyze", method="POST", headers=headers,
                               data=json.dumps({"path": str(path or self.path)}).encode()), timeout=3)

    def test_health_and_delivery(self):
        with urlopen(self.url + "/health", timeout=3) as response:
            self.assertEqual(json.load(response)["app"], "aim-trainer-coach")
        with self.request() as response:
            self.assertEqual(response.status, 202)
        self.assertEqual(self.server.commands.get_nowait(), self.path)

    def test_shutdown_requires_owned_launch_and_matching_token(self):
        def shutdown(token):
            return urlopen(Request(self.url + '/shutdown', method='POST', data=b'',
                                   headers={'X-Coach-Token': token}), timeout=3)
        with self.assertRaises(HTTPError) as error:
            shutdown('test-token')
        self.assertEqual(error.exception.code, 403)
        self.server.launch_id = 'unit-test-owned-launch'
        with self.assertRaises(HTTPError) as error:
            shutdown('wrong-token')
        self.assertEqual(error.exception.code, 403)
        self.assertFalse(self.server.shutdown_requested.is_set())
        with shutdown('test-token') as response:
            self.assertEqual(response.status, 200)
        self.assertTrue(self.server.shutdown_requested.is_set())

    def test_reject_wrong_token_and_browser_origin(self):
        for kwargs in ({"token": "wrong"}, {"origin": "https://example.com"}):
            with self.assertRaises(HTTPError) as error:
                self.request(**kwargs)
            self.assertEqual(error.exception.code, 403)
        self.assertTrue(self.server.commands.empty())

    def test_reject_missing_path(self):
        with self.assertRaises(HTTPError) as error:
            self.request(path=self.path.parent / "missing.json")
        self.assertEqual(error.exception.code, 400)

    def test_second_instance_cannot_bind(self):
        with self.assertRaises(OSError):
            CoachServer(self.server.server_port)

    def test_health_reports_key_availability_without_key(self):
        for key, expected in (("", False), ("test-secret-not-for-output", True)):
            with patch.dict("os.environ", {"NEBIUS_API_KEY": key}):
                with urlopen(self.url + "/health", timeout=3) as response:
                    data = json.load(response)
            self.assertIs(data["api_key_available"], expected)
            self.assertNotIn("test-secret-not-for-output", json.dumps(data))


if __name__ == "__main__":
    unittest.main()
