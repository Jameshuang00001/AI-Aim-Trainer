"""Provenance unit tests use fake Quartz events and never post native input."""
import unittest
import json
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

import coach_app.quartz_provenance as provenance
from coach_app.diagnostic_udp import DiagnosticAssembler
from coach_app.quartz_matrix import TelemetryReception
from coach_app.quartz_provenance import (analyze_trial, correlate_tap_events, create_tagged_event,
                                         new_event_tag, tap_event_record)
from coach_app.test_camera_calibration import state, advance
from coach_app.telemetry import CorrectionLog


class FakeQuartz:
    kCGEventMouseMoved = 5
    kCGMouseButtonRight = 1
    kCGMouseEventDeltaX = 4
    kCGMouseEventDeltaY = 5
    kCGEventSourceUserData = 42
    kCGEventSourceUnixProcessID = 41

    def __init__(self):
        self.fields = {}
        self.event = object()
        self.CGEventPostToPid = Mock()

    def CGEventCreate(self, _source):
        return object()

    def CGEventGetLocation(self, _event):
        return SimpleNamespace(x=200., y=100.)

    def CGEventCreateMouseEvent(self, *_args):
        return self.event

    def CGEventSetIntegerValueField(self, event, field, value):
        self.fields[(event, field)] = value

    def CGEventGetIntegerValueField(self, event, field):
        if field == self.kCGEventSourceUnixProcessID:
            return 777
        return self.fields.get((event, field), 0)

    def CGEventGetType(self, _event):
        return self.kCGEventMouseMoved

    def CGEventGetTimestamp(self, _event):
        return 123456


class ProvenanceTests(unittest.TestCase):
    def test_run_initializes_reassembly_and_stops_without_posting(self):
        class FakeReceiver:
            def bind(self, _address):
                pass

            def setblocking(self, _enabled):
                pass

            def close(self):
                pass

        class FakeLog:
            def __init__(self, _path):
                self.rows = []

            def write(self, row):
                self.rows.append(row)

            def close(self):
                pass

        fake_q = SimpleNamespace(
            CGPreflightListenEventAccess=lambda: True,
            kCGEventSourceStateHIDSystemState=1,
            CGEventSourceKeyState=lambda _source, key: key == provenance.F8_KEYCODE,
            CGEventPostToPid=Mock(),
        )
        fake_tap = Mock()
        fake_tap.errors = provenance.queue.Queue()
        fake_foreground = Mock()
        receiver = FakeReceiver()
        log = FakeLog(None)
        receptions = []

        def make_reception():
            result = TelemetryReception()
            receptions.append(result)
            return result

        with patch.dict(sys.modules, {'Quartz': fake_q, 'CoreFoundation': SimpleNamespace()}), \
             patch.object(sys, 'argv', ['quartz_provenance', '--window-id', '80188',
                                        '--axis', 'horizontal', '--direction', 'positive']), \
             patch.object(provenance, 'accessibility_trusted', return_value=True), \
             patch.object(provenance, 'resolve_destination', return_value={
                 'resolved_owner_pid': 456, 'window_id': 80188}), \
             patch.object(provenance, 'CorrectionLog', return_value=log), \
             patch.object(provenance, 'ProcessMouseEventTap', return_value=fake_tap), \
             patch.object(provenance, 'ForegroundQuery', return_value=fake_foreground), \
             patch.object(provenance.socket, 'socket', return_value=receiver), \
             patch.object(provenance, 'TelemetryReception', side_effect=make_reception):
            provenance.main()

        self.assertEqual(len(receptions), 1)
        self.assertIsInstance(receptions[0].assembler, DiagnosticAssembler)
        fake_tap.start.assert_called_once_with()
        fake_tap.stop.assert_called_once_with()
        fake_q.CGEventPostToPid.assert_not_called()
        self.assertIn('provenance_started', [row['event'] for row in log.rows])
        self.assertIn('provenance_stopped', [row['event'] for row in log.rows])

    def test_tagged_event_is_built_and_read_back_without_posting(self):
        q = FakeQuartz()
        tag = new_event_tag(lambda bits: (1 << 62) + 9)
        event, record = create_tagged_event(q, 2, 0, tag, 456)
        self.assertIs(event, q.event)
        self.assertEqual(record['user_data_readback'], tag)
        self.assertEqual(record['delta_x'], 2)
        self.assertEqual(record['delta_y'], 0)
        q.CGEventPostToPid.assert_not_called()

    def test_tag_validation_and_pulse_bounds(self):
        self.assertRaises(ValueError, new_event_tag, lambda _bits: 0)
        q = FakeQuartz()
        for delta in ((3, 0), (2, 2), (0, 0)):
            with self.subTest(delta=delta):
                self.assertRaises(ValueError, create_tagged_event, q, *delta, 99, 456)
        q.CGEventPostToPid.assert_not_called()

    def test_tap_records_tagged_and_untagged_events_separately(self):
        q = FakeQuartz()
        event = q.event
        q.fields[(event, q.kCGEventSourceUserData)] = 987654
        q.fields[(event, q.kCGMouseEventDeltaX)] = -2
        q.fields[(event, q.kCGMouseEventDeltaY)] = 0
        tagged = tap_event_record(q, event, 456, 987654, monotonic=10.)
        self.assertEqual(tagged['classification'], 'tagged_current_pulse')
        self.assertEqual(tagged['source_pid'], 777)
        q.fields[(event, q.kCGEventSourceUserData)] = 0
        untagged = tap_event_record(q, event, 456, 987654, monotonic=11.)
        self.assertEqual(untagged['classification'], 'untagged')

    def test_tag_and_tap_rows_round_trip_to_jsonl_without_native_post(self):
        q = FakeQuartz()
        tag = new_event_tag(lambda _bits: 123)
        event, posted = create_tagged_event(q, 0, -2, tag, 456)
        tapped = tap_event_record(q, event, 456, tag, monotonic=3.)
        with tempfile.TemporaryDirectory() as directory:
            log = CorrectionLog(directory)
            log.write({'event': 'tagged_pulse_posted', **posted})
            log.write(tapped)
            path = log.path
            log.close()
            rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual(rows[0]['event_tag'], 123)
        self.assertEqual(rows[1]['classification'], 'tagged_current_pulse')
        q.CGEventPostToPid.assert_not_called()

    def test_one_tagged_event_correlates_to_one_or_two_frames_without_relaxing_verdict(self):
        before = state()
        after_one = advance(before, (2, 0))
        frame = after_one['mouse_frames'][-1]
        event = {'classification': 'tagged_current_pulse', 'event_tag': 123,
                 'event_timestamp_ns': 99, 'delta_x': 2, 'delta_y': 0}
        one = analyze_trial(before, after_one, (2, 0), [frame], [event], 123)
        self.assertEqual(one['provenance_interpretation'], 'event_and_Unity_frame_counts_differ')
        self.assertTrue(one['strict_matrix_verdict']['success'])

        twice = advance(after_one, (2, 0), realtime=2.)
        two = analyze_trial(before, twice, (2, 0), twice['mouse_frames'], [event], 123)
        self.assertEqual(two['provenance_interpretation'], 'one_tagged_tap_event_two_Unity_input_frames')
        self.assertFalse(two['strict_matrix_verdict']['success'])
        self.assertFalse(two['strict_matrix_verdict']['frame_count_valid'])

    def test_untagged_and_multiple_tagged_events_are_reported_as_mixed_or_duplicate(self):
        before = state(); after = advance(before, (2, 0))
        frame = after['mouse_frames'][-1]
        tagged = {'classification': 'tagged_current_pulse', 'event_tag': 123}
        untagged = {'classification': 'untagged', 'event_tag': 0}
        mixed = analyze_trial(before, after, (2, 0), [frame], [tagged, untagged], 123)
        self.assertEqual(mixed['provenance_interpretation'], 'tagged_event_plus_untagged_movement_possible')
        duplicate = analyze_trial(before, after, (2, 0), [frame], [tagged, tagged], 123)
        self.assertEqual(duplicate['provenance_interpretation'], 'same_tag_observed_on_multiple_tap_callbacks')

    def test_tap_event_is_paired_to_nearest_unity_frame_timestamp(self):
        event = {'event_tag': 123, 'classification': 'tagged_current_pulse',
                 'event_timestamp_ns': 2_000_000_000,
                 'observed_at': '2026-10-23T15:00:00.000+00:00'}
        frames = [{'frame': 8, 'input_sequence': 4,
                   'timestamp': '2026-10-23T15:00:00.016+00:00', 'realtime': .5}]
        row = correlate_tap_events([event], frames)[0]
        self.assertEqual(row['unity_frame'], 8)
        self.assertAlmostEqual(row['frame_minus_tap_observed_ms'], 16.)
        self.assertAlmostEqual(row['event_uptime_minus_unity_realtime_seconds'], 1.5)


if __name__ == '__main__':
    unittest.main()
