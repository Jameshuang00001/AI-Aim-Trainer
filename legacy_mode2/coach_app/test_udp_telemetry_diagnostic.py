import json
import socket
import unittest
from unittest.mock import patch

from .test_quartz_delivery import sample
from .udp_telemetry_diagnostic import packet_summary, receive_one
from .quartz_matrix import TelemetryReception


class UdpDiagnosticTests(unittest.TestCase):
    def test_reception_counts_invalid_and_valid_packets_separately(self):
        reception = TelemetryReception()
        self.assertEqual(reception.packet_count, 0)
        reception.decode(b'not_json', 9900, 0.)
        reception.decode(json.dumps(sample()).encode(), 9900, 1.)
        self.assertEqual(reception.packet_count, 2)
        self.assertEqual(reception.valid_packet_count, 1)

    def test_valid_schema_and_sanitized_output(self):
        state = {**sample(), 'mouse_frame_version': 1, 'mouse_frames': [],
                 'private_string': 'DO_NOT_PRINT'}
        result = packet_summary(json.dumps(state).encode(), 9900)
        self.assertEqual(result['status'], 'valid_packet')
        self.assertTrue(result['frame_schema']['schema_valid'])
        self.assertNotIn('DO_NOT_PRINT', json.dumps(result))

    def test_invalid_json_and_schema_are_received_not_missing(self):
        for payload, reason in ((b'bad', 'malformed_json'),
                                (b'[]', 'telemetry_not_an_object'),
                                (b'{"pid":9900}', 'diagnostic_version_missing_or_unsupported')):
            result = packet_summary(payload, 9900)
            self.assertEqual(result['status'], 'invalid_packet')
            self.assertTrue(result['packet_received'])
            self.assertEqual(result['rejection'], reason)

    def test_wrong_pid_and_wrong_stream_are_distinct(self):
        result = packet_summary(json.dumps(sample()).encode(), 42)
        self.assertEqual(result['rejection'], 'telemetry_pid_mismatch')
        result = packet_summary(json.dumps({**sample(), 'mouse_frame_version': 0,
                                            'mouse_frames': []}).encode(), 9900)
        self.assertEqual(result['status'], 'valid_packet')
        self.assertFalse(result['frame_schema']['available'])

    def test_receive_timeout_conflict_and_success_never_send(self):
        for case in ('timeout', 'bound', 'success'):
            with self.subTest(case=case), patch('socket.socket') as factory:
                receiver = factory.return_value.__enter__.return_value
                if case == 'timeout': receiver.recvfrom.side_effect = socket.timeout()
                if case == 'bound': receiver.bind.side_effect = OSError(48, 'Address in use')
                if case == 'success':
                    receiver.recvfrom.return_value = (json.dumps(sample()).encode(), ('127.0.0.1', 12345))
                result = receive_one(8767, 9900)
                self.assertEqual(result['status'], {'timeout': 'no_packet_received',
                                 'bound': 'bind_failed', 'success': 'valid_packet'}[case])
                receiver.send.assert_not_called()
                receiver.sendto.assert_not_called()
                receiver.setsockopt.assert_not_called()
                receiver.bind.assert_called_once_with(('127.0.0.1', 8767))
