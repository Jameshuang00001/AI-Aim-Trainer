import ctypes
import json
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from coach_app import diagnose_accessibility as diagnostic
from coach_app.macos_input import accessibility_trusted


class AccessibilityDiagnosticsTests(unittest.TestCase):
    def test_report_save_to_explicit_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            report = {'coach_accessibility_trusted': False, 'input_events_posted': False}
            path = diagnostic.save_report(report, directory)
            self.assertEqual(json.loads(path.read_text()), report)

    def test_coach_uses_exact_ax_signature_without_prompt(self):
        library = MagicMock()
        library.AXIsProcessTrusted.return_value = False
        with patch('coach_app.macos_input.ctypes.CDLL', return_value=library):
            self.assertFalse(accessibility_trusted())
        self.assertIs(library.AXIsProcessTrusted.restype, ctypes.c_bool)
        self.assertEqual(library.AXIsProcessTrusted.argtypes, [])
        library.AXIsProcessTrusted.assert_called_once_with()
        self.assertEqual([call[0] for call in library.mock_calls], ['AXIsProcessTrusted'])

    def test_diagnostic_reuses_coach_check_and_agrees_with_raw_boolean(self):
        for trusted in (True, False):
            library = MagicMock()
            library.AXIsProcessTrusted.return_value = int(trusted)
            with patch.object(diagnostic.sys, 'platform', 'darwin'), \
                    patch.object(diagnostic, 'accessibility_trusted', return_value=trusted) as same_check, \
                    patch.object(diagnostic.ctypes, 'CDLL', return_value=library), \
                    patch.object(diagnostic, 'process_ancestry', return_value=[]):
                report = diagnostic.diagnose()
            same_check.assert_called_once_with()
            self.assertEqual(report['coach_accessibility_trusted'], trusted)
            self.assertTrue(report['boolean_interpretations_agree'])
            self.assertFalse(report['input_events_posted'])
            self.assertFalse(report['permission_prompt_requested'])
            self.assertNotIn('environment', report)


if __name__ == '__main__':
    unittest.main()
