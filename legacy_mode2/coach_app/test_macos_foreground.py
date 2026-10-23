"""Read-only query tests; no real focus changes, posting or activation."""
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock

from .macos_foreground import ForegroundQuery
from .focus_switch_diagnostic import verified_sequence
from .quartz_matrix import precondition_snapshot
from .test_quartz_delivery import sample


def app(pid):
    return SimpleNamespace(processIdentifier=lambda: pid)


class ForegroundTests(unittest.TestCase):
    def test_stale_value_refreshed_only_after_pump(self):
        workspace = Mock()
        workspace.frontmostApplication.side_effect = [app(100), app(200)]
        pump = Mock()
        result = ForegroundQuery(workspace, pump).snapshot()
        pump.assert_called_once()
        self.assertEqual(result['nsworkspace_before_pump_pid'], 100)
        self.assertEqual(result['foreground_pid'], 200)

    def test_terminal_unity_terminal_transitions(self):
        workspace = Mock()
        workspace.frontmostApplication.side_effect = [app(100), app(100), app(100), app(200), app(200), app(100)]
        query = ForegroundQuery(workspace, Mock())
        rows = [query.snapshot() for _ in range(3)]
        self.assertEqual([r['foreground_pid'] for r in rows], [100, 200, 100])
        self.assertTrue(verified_sequence(rows, 100, 200))
        self.assertFalse(verified_sequence(rows[:2], 100, 200))
        self.assertFalse(verified_sequence([{'foreground_pid': 200}, {'foreground_pid': 100}], 100, 200))

    def test_missing_foreground_never_uses_cached_or_selected_pid(self):
        workspace = Mock()
        workspace.frontmostApplication.side_effect = [app(9900), None]
        result = ForegroundQuery(workspace, Mock()).snapshot()
        self.assertIsNone(result['foreground_pid'])
        backend = Mock(pid=9900)
        backend.snapshot.return_value = {**result, 'accessibility_trusted': True}
        backend.validate_destination.return_value = {}
        report = precondition_snapshot(backend, sample(), result['foreground_checked_monotonic'],
                                       result['foreground_checked_monotonic'])
        self.assertIn('foreground_pid_mismatch', report['rejected_preconditions'])

    def test_pump_error_is_not_replaced_with_cached_focus(self):
        workspace = Mock()
        workspace.frontmostApplication.return_value = app(9900)
        with self.assertRaises(RuntimeError):
            ForegroundQuery(workspace, Mock(side_effect=RuntimeError('pump failed'))).snapshot()

    def test_background_query_rejected(self):
        query = ForegroundQuery(Mock(), Mock())
        errors = []
        def run():
            try:
                query.snapshot()
            except RuntimeError as error:
                errors.append(str(error))
        thread = threading.Thread(target=run)
        thread.start(); thread.join()
        self.assertEqual(len(errors), 1)

    def test_telemetry_age_includes_notification_processing(self):
        backend = Mock(pid=9900)
        backend.snapshot.return_value = {'foreground_pid': 9900, 'accessibility_trusted': True,
                                         'foreground_checked_monotonic': 1.201}
        backend.validate_destination.return_value = {}
        report = precondition_snapshot(backend, sample(), 1., 1.199)
        self.assertIn('unity_telemetry_stale', report['rejected_preconditions'])


if __name__ == '__main__':
    unittest.main()
