"""Credential tests use mocks only, never the user's real Keychain."""

import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

from coach_app import credentials
from coach_app import nebius_client


class CredentialTests(unittest.TestCase):
    def test_environment_takes_precedence(self):
        with patch.dict("os.environ", {"NEBIUS_API_KEY": "env-test-value"}, clear=True):
            with patch.object(credentials, "macos_backend") as backend:
                self.assertEqual(credentials.get_api_key(), "env-test-value")
                backend.assert_not_called()

    def test_keychain_used_when_environment_absent_or_blank(self):
        for value in ("", "   "):
            with patch.dict("os.environ", {"NEBIUS_API_KEY": value}, clear=True):
                with patch.object(credentials.sys, "platform", "darwin"), patch.object(credentials, "macos_backend") as backend:
                    backend.return_value.get_password.return_value = "keychain-test-value"
                    self.assertEqual(credentials.get_api_key(), "keychain-test-value")
                    backend.return_value.get_password.assert_called_once_with(credentials.SERVICE, credentials.ACCOUNT)

    def test_missing_key_returns_none(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(credentials.sys, "platform", "darwin"):
            with patch.object(credentials, "macos_backend") as backend:
                backend.return_value.get_password.return_value = None
                self.assertIsNone(credentials.get_api_key())

    def test_denied_keychain_access_safe_status(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(credentials.sys, "platform", "darwin"):
            with patch.object(credentials, "macos_backend") as backend:
                backend.return_value.get_password.side_effect = RuntimeError("sensitive-backend-detail")
                available, message = credentials.credential_status()
                self.assertFalse(available)
                self.assertIn("Unlock", message)
                self.assertNotIn("sensitive-backend-detail", message)

    def test_setup_writes_only_to_keychain_and_never_echoes_key(self):
        output = io.StringIO()
        with patch.object(credentials.sys, "argv", ["credentials", "setup"]), patch.object(credentials.sys.stdin, "isatty", return_value=True):
            with patch.object(credentials.getpass, "getpass", return_value="setup-test-value"), patch.object(credentials, "macos_backend") as backend:
                with contextlib.redirect_stdout(output):
                    self.assertEqual(credentials.main(), 0)
                backend.return_value.set_password.assert_called_once_with(credentials.SERVICE, credentials.ACCOUNT, "setup-test-value")
        self.assertNotIn("setup-test-value", output.getvalue())

    def test_keychain_access_failure_is_analysis_error(self):
        with patch.object(nebius_client, "get_api_key", side_effect=credentials.CredentialError("Unlock Keychain")):
            with self.assertRaisesRegex(nebius_client.AnalysisError, "Unlock Keychain"):
                nebius_client.analyze_session({})

    def test_other_platform_does_not_try_keychain(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(credentials.sys, "platform", "linux"):
            with patch.object(credentials, "macos_backend") as backend:
                self.assertIsNone(credentials.get_api_key())
                backend.assert_not_called()


if __name__ == "__main__":
    unittest.main()
