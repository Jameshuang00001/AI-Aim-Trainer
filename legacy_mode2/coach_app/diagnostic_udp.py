"""Bounded diagnostic datagram reassembly. No input or network sending."""
import base64
import binascii
import hashlib
import json
import re

MAX_DATAGRAM_BYTES = 6000
MAX_PAYLOAD_BYTES = 65536
CHUNK_BYTES = 3072
MAX_BATCHES = 8
ASSEMBLY_TIMEOUT = .2  # Never extend the existing 200 ms telemetry freshness gate.


class DiagnosticAssembler:
    def __init__(self):
        self.batches = {}
        self.retired_batches = {}
        self.received_at = None
        self.transport = None
        self.pending = False
        self.expired_batches = 0
        self.last_frames = {}

    def retire(self, key):
        stream = key[:2]
        self.retired_batches[stream] = max(key[2], self.retired_batches.get(stream, 0))
        if len(self.retired_batches) > MAX_BATCHES:
            old = next(iter(self.retired_batches))
            del self.retired_batches[old]
            self.last_frames.pop(old, None)

    def feed(self, data, expected_pid, now):
        self.pending = False
        self.received_at = now
        self.transport = None
        for key, batch in list(self.batches.items()):
            if now-batch['first_received'] >= ASSEMBLY_TIMEOUT:
                del self.batches[key]
                self.retire(key)
                self.expired_batches += 1
        try:
            packet = json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise ValueError('malformed_json') from error
        if not isinstance(packet, dict) or 'diagnostic_chunk_version' not in packet:
            return packet  # Legacy unchunked state is checked by existing callers.
        if len(data) >= MAX_DATAGRAM_BYTES:
            raise ValueError('diagnostic_datagram_oversized')
        integer_fields = ('pid', 'frame', 'batch_id', 'chunk_index', 'chunk_count', 'payload_bytes')
        if (type(packet.get('diagnostic_chunk_version')) is not int or
                packet['diagnostic_chunk_version'] != 1 or
                any(type(packet.get(k)) is not int for k in integer_fields) or
                packet['pid'] != expected_pid or packet['frame'] < 0 or packet['batch_id'] < 1 or
                not 1 <= packet['payload_bytes'] <= MAX_PAYLOAD_BYTES or
                not isinstance(packet.get('stream_id'), str) or
                re.fullmatch('[0-9a-f]{32}', packet['stream_id']) is None or
                not isinstance(packet.get('sha256'), str) or
                re.fullmatch('[0-9a-f]{64}', packet['sha256']) is None):
            raise ValueError('invalid_diagnostic_chunk_header')
        count = (packet['payload_bytes']+CHUNK_BYTES-1)//CHUNK_BYTES
        index = packet['chunk_index']
        if packet['chunk_count'] != count or not 0 <= index < count:
            raise ValueError('invalid_diagnostic_chunk_range')
        try:
            if not isinstance(packet.get('data'), str):
                raise ValueError('missing_chunk_data')
            part = base64.b64decode(packet['data'], validate=True)
        except (ValueError, binascii.Error) as error:
            raise ValueError('invalid_diagnostic_chunk_base64') from error
        if len(part) != min(CHUNK_BYTES, packet['payload_bytes']-index*CHUNK_BYTES):
            raise ValueError('invalid_diagnostic_chunk_length')
        key = (packet['pid'], packet['stream_id'], packet['batch_id'])
        stream = key[:2]
        if packet['batch_id'] <= self.retired_batches.get(stream, 0):
            self.pending = True
            return None  # Expired/replayed batches cannot later masquerade as fresh.
        if packet['frame'] <= self.last_frames.get(stream, -1):
            self.pending = True
            return None  # A late old batch must not rewind state or freshness.
        header = (packet['frame'], packet['payload_bytes'], count, packet['sha256'])
        batch = self.batches.get(key)
        if batch is None:
            if len(self.batches) >= MAX_BATCHES:
                raise ValueError('diagnostic_reassembly_capacity_exceeded')
            batch = self.batches[key] = {'header': header, 'parts': {}, 'first_received': now,
                                         'sizes': {}}
        if batch['header'] != header or (index in batch['parts'] and batch['parts'][index] != part):
            # Keep a poisoned batch until expiry so later fragments cannot rescue it.
            batch['invalid'] = True
        if batch.get('invalid'):
            raise ValueError('conflicting_diagnostic_chunks')
        batch['parts'][index] = part  # Identical duplicates do not add frames.
        batch['sizes'][index] = len(data)
        if len(batch['parts']) != count:
            self.pending = True
            return None
        payload = b''.join(batch['parts'][i] for i in range(count))
        if hashlib.sha256(payload).hexdigest() != packet['sha256']:
            batch['invalid'] = True
            raise ValueError('diagnostic_payload_checksum_failed')
        try:
            state = json.loads(payload)
        except (ValueError, UnicodeError) as error:
            raise ValueError('malformed_diagnostic_payload_json') from error
        if (not isinstance(state, dict) or state.get('pid') != expected_pid or
                state.get('frame') != packet['frame'] or
                type(state.get('mouse_frame_version')) is not int or state['mouse_frame_version'] != 1 or
                not isinstance(state.get('mouse_frames'), list)):
            raise ValueError('diagnostic_payload_header_mismatch')
        self.received_at = batch['first_received']
        self.transport = {'format': 'chunked_v1', 'batch_id': packet['batch_id'],
                          'chunk_count': count, 'payload_bytes': len(payload),
                          'datagram_bytes': [batch['sizes'][i] for i in range(count)],
                          'assembly_ms': (now-self.received_at)*1000,
                          'expired_incomplete_batches': self.expired_batches}
        self.retire(key)
        self.last_frames[stream] = packet['frame']
        if len(self.last_frames) > MAX_BATCHES:
            del self.last_frames[next(iter(self.last_frames))]
        del self.batches[key]
        return state
