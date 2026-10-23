"""All datagrams are in-memory fixtures. No Quartz or OS input is used."""
import base64
import hashlib
import json
from pathlib import Path
import unittest

from .diagnostic_udp import DiagnosticAssembler, CHUNK_BYTES, MAX_DATAGRAM_BYTES
from .quartz_matrix import TelemetryReception, evaluate
from . import test_quartz_matrix as fixtures
from .udp_telemetry_diagnostic import packet_summary


def encode_chunks(state, batch=1, stream='a'*32):
    payload = json.dumps(state, separators=(',', ':'), allow_nan=False).encode()
    count = (len(payload)+CHUNK_BYTES-1)//CHUNK_BYTES
    packets = [json.dumps({'diagnostic_chunk_version': 1, 'pid': state['pid'],
                           'frame': state['frame'], 'batch_id': batch, 'chunk_index': i,
                           'chunk_count': count, 'payload_bytes': len(payload),
                           'stream_id': stream, 'sha256': hashlib.sha256(payload).hexdigest(),
                           'data': base64.b64encode(payload[i*CHUNK_BYTES:(i+1)*CHUNK_BYTES]).decode()},
                          separators=(',', ':')).encode() for i in range(count)]
    return payload, packets


def history_fixture():
    before, state = fixtures.MatrixTests().frame_trial([(.05, 0)]*32)
    return before, state


class ReassemblyTests(unittest.TestCase):
    def test_oversized_history_uses_safe_sized_datagrams_without_frame_loss(self):
        before, state = history_fixture()
        payload, packets = encode_chunks(state)
        self.assertGreater(len(payload), 9216)
        self.assertGreater(len(packets), 1)
        self.assertTrue(all(len(p) < MAX_DATAGRAM_BYTES < 9216 for p in packets))
        reception = TelemetryReception()
        decoded = None
        for packet in reversed(packets):
            value = reception.decode(packet, 9900, 1.)
            if value is not None: decoded = value
        self.assertEqual(decoded, state)
        self.assertEqual(len(decoded['mouse_frames']), 32)
        self.assertFalse(evaluate(before, decoded, (2, 0))['frame_count_valid'])
        self.assertEqual(reception.last_transport['payload_bytes'], len(payload))

    def test_duplicate_chunks_and_complete_batch_replay_do_not_duplicate_state(self):
        _, state = history_fixture()
        _, packets = encode_chunks(state)
        assembler = DiagnosticAssembler()
        emitted = []
        for packet in packets+packets:
            for _ in range(2):
                result = assembler.feed(packet, 9900, 1.)
                if result is not None: emitted.append(result)
        self.assertEqual(emitted, [state])

    def test_missing_chunks_do_not_emit_and_history_recovers_next_batch(self):
        _, state = history_fixture()
        _, packets = encode_chunks(state)
        assembler = DiagnosticAssembler()
        for p in packets[:-1]: self.assertIsNone(assembler.feed(p, 9900, 0.))
        later = {**state, 'frame': state['frame']+10}
        _, retry = encode_chunks(later, batch=2)
        recovered = None
        for p in retry: recovered = assembler.feed(p, 9900, .3)
        self.assertEqual(recovered['mouse_frames'], state['mouse_frames'])
        self.assertEqual(assembler.expired_batches, 1)

    def test_expired_batch_cannot_be_completed_by_late_final_chunk(self):
        _, state = history_fixture()
        _, packets = encode_chunks(state)
        assembler = DiagnosticAssembler()
        for p in packets[:-1]: assembler.feed(p, 9900, 0.)
        self.assertIsNone(assembler.feed(packets[-1], 9900, .21))
        self.assertEqual(assembler.expired_batches, 1)
        for packet in packets:
            self.assertIsNone(assembler.feed(packet, 9900, .22))

    def test_conflicting_duplicate_and_checksum_fail_closed(self):
        _, state = history_fixture()
        _, packets = encode_chunks(state)
        assembler = DiagnosticAssembler()
        assembler.feed(packets[0], 9900, 0.)
        changed = json.loads(packets[0])
        part = bytearray(base64.b64decode(changed['data'])); part[0] ^= 1
        changed['data'] = base64.b64encode(part).decode()
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            assembler.feed(json.dumps(changed).encode(), 9900, .01)
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            assembler.feed(packets[0], 9900, .02)
        assembler = DiagnosticAssembler()
        for p in packets:
            altered = json.loads(p); altered['sha256'] = '0'*64
            if p != packets[-1]: assembler.feed(json.dumps(altered).encode(), 9900, 0.)
            else:
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    assembler.feed(json.dumps(altered).encode(), 9900, 0.)

    def test_old_batch_does_not_rewind_state_and_freshness_uses_first_fragment(self):
        _, state = history_fixture()
        _, packets = encode_chunks(state)
        later = {**state, 'frame': state['frame']+1}
        _, newer = encode_chunks(later, batch=2)
        assembler = DiagnosticAssembler()
        assembler.feed(packets[0], 9900, 0.)
        for p in newer: assembler.feed(p, 9900, .02)
        for p in packets[1:]: self.assertIsNone(assembler.feed(p, 9900, .03))
        assembler = DiagnosticAssembler()
        for i, p in enumerate(packets): assembler.feed(p, 9900, i*.02)
        self.assertEqual(assembler.received_at, 0.)
        self.assertGreater(assembler.transport['assembly_ms'], 0)

    def test_oversized_or_malformed_envelopes_rejected(self):
        _, state = history_fixture()
        _, packets = encode_chunks(state)
        for key, value in (('payload_bytes', 65537), ('chunk_count', 100000),
                           ('chunk_index', -1), ('pid', 42), ('data', 'not base64!')):
            p = json.loads(packets[0]); p[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                DiagnosticAssembler().feed(json.dumps(p).encode(), 9900, 0.)
        p = json.loads(packets[0]); p['padding'] = 'x'*6000
        with self.assertRaisesRegex(ValueError, 'oversized'):
            DiagnosticAssembler().feed(json.dumps(p).encode(), 9900, 0.)

    def test_read_only_receiver_summary_handles_complete_batch(self):
        _, state = history_fixture()
        _, packets = encode_chunks(state)
        reception = TelemetryReception()
        for p in packets: summary = packet_summary(p, 9900, reception)
        self.assertEqual(summary['status'], 'valid_packet')
        self.assertEqual(summary['mouse_frame_count'], 32)
        self.assertEqual(summary['transport']['chunk_count'], len(packets))

    def test_partial_next_batch_does_not_invalidate_or_refresh_complete_state(self):
        _, state = history_fixture()
        _, packets = encode_chunks(state)
        reception = TelemetryReception()
        for p in packets: reception.decode(p, 9900, 1.)
        _, later = encode_chunks({**state, 'frame': state['frame']+1}, batch=2)
        self.assertIsNone(reception.decode(later[0], 9900, 1.05))
        self.assertIsNone(reception.last_packet_rejection)
        self.assertEqual(reception.last_state_received_at, 1.)
        reception.decode(b'bad', 9900, 1.06)
        reception.decode(later[1], 9900, 1.07)
        self.assertEqual(reception.last_packet_rejection, 'malformed_json')

    def test_csharp_protocol_constants_match_receiver(self):
        source = (Path(__file__).resolve().parents[1]/'Assets/Scripts/System/AssistStatePublisher.cs').read_text()
        self.assertIn(f'ChunkPayloadBytes = {CHUNK_BYTES};', source)
        self.assertIn(f'MaxDiagnosticDatagramBytes = {MAX_DATAGRAM_BYTES};', source)
        self.assertIn('diagnostic_chunk_version = 1;', source)
