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

    def test_ui_cancel_does_not_save(self):
        from coach_app.overlay import CoachWindow
        window = MagicMock()
        with patch("coach_app.overlay.simpledialog.askstring", return_value=None), patch("coach_app.overlay.save_api_key") as save:
            CoachWindow.configure_api_key(window)
            save.assert_not_called()

    def test_ui_masks_and_saves_only_entered_key(self):
        from coach_app.overlay import CoachWindow
        window = MagicMock()
        with patch("coach_app.overlay.simpledialog.askstring", return_value="new-user-test-key") as prompt, patch("coach_app.overlay.save_api_key") as save, patch("coach_app.overlay.messagebox.showinfo") as info:
            CoachWindow.configure_api_key(window)
            self.assertEqual(prompt.call_args.kwargs["show"], "*")
            self.assertNotIn("initialvalue", prompt.call_args.kwargs)
            save.assert_called_once_with("new-user-test-key")
            self.assertNotIn("new-user-test-key", str(info.call_args))

    def test_other_platform_does_not_try_keychain(self):
        with patch.dict("os.environ", {}, clear=True), patch.object(credentials.sys, "platform", "linux"):
            with patch.object(credentials, "macos_backend") as backend:
                self.assertIsNone(credentials.get_api_key())
                backend.assert_not_called()


if __name__ == "__main__":
    unittest.main()
