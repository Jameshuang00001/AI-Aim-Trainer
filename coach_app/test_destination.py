import unittest
from unittest.mock import patch
from types import SimpleNamespace
from coach_app.audit_destination import resolve_destination


class DestinationTests(unittest.TestCase):
    def quartz(self, pid=9900):
        return SimpleNamespace(kCGWindowListOptionIncludingWindow=1,
            kCGWindowNumber='number', kCGWindowOwnerPID='pid', kCGWindowOwnerName='owner', kCGWindowName='title',
            CGWindowListCopyWindowInfo=lambda option, window:[{'number':4101, 'pid':pid, 'owner':'AI-Aim-Trainer'}])

    def test_owner_pid_not_window_id_is_destination(self):
        with patch.dict('sys.modules', {'Quartz':self.quartz()}), \
             patch('coach_app.audit_destination.executable_path', return_value='/game/AI-Aim-Trainer-Test.app/Contents/MacOS/AI-Aim-Trainer'):
            result = resolve_destination(4101, expected_app='AI-Aim-Trainer-Test.app')
        self.assertEqual(result['selected_window_id'],4101)
        self.assertEqual(result['CGEventPostToPid_destination_pid'],9900)
        self.assertFalse(result['input_events_posted'])

    def test_changed_owner_is_rejected(self):
        with patch.dict('sys.modules', {'Quartz':self.quartz(9999)}), \
             patch('coach_app.audit_destination.executable_path', return_value='/game/AI-Aim-Trainer-Test.app/Contents/MacOS/AI-Aim-Trainer'):
            with self.assertRaisesRegex(RuntimeError, 'owner changed'):
                resolve_destination(4101, expected_pid=9900)

    def test_coach_bundle_does_not_match_expected_game(self):
        with patch.dict('sys.modules', {'Quartz':self.quartz()}), \
             patch('coach_app.audit_destination.executable_path', return_value='/app/Coach.app/Contents/MacOS/Coach'):
            with self.assertRaisesRegex(RuntimeError, 'Expected AI-Aim-Trainer-Test.app'):
                resolve_destination(4101, expected_app='AI-Aim-Trainer-Test.app')
