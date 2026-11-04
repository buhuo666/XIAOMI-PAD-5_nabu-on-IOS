#!/usr/bin/env python3
"""Strict codec and prefix recovery for docs/NABU-PERSISTENT-LOG-FORMAT.md.

All device I/O lives in nabu_runtime_logs.py. This module reads a bounded,
seekable snapshot and emits only fully validated contiguous DATA records.
"""
import hashlib
import io
import struct
import zlib

BLOCK_BYTES = 4096
SLOT_BYTES = 64 * 1024 * 1024
SLOT_COUNT = 16
PARTITION_BYTES = 64424509440
RESERVED_OFFSET = 63350767616
RESERVED_BYTES = 1073741824
MAX_PAYLOAD = 65536
MANIFEST_MAGIC = b'NABULG01'
RECORD_MAGIC = b'NBLOGR01'
BEGIN, DATA, END = 1, 2, 3
EMPTY_SHA256 = hashlib.sha256(b'').digest()
ZERO_BLOCK = bytes(BLOCK_BYTES)


class LogFormatError(ValueError):
    """Untrusted bytes do not match the v1 contract."""


def require(condition, message):
    if not condition:
        raise LogFormatError(message)


def slot_offset(slot):
    require(type(slot) is int and 0 <= slot < SLOT_COUNT, 'slot index out of bounds')
    return RESERVED_OFFSET + slot * SLOT_BYTES


def extent_bytes(slot, span=1):
    slot_offset(slot)
    require(type(span) is int and 1 <= span <= SLOT_COUNT - slot, 'extent span out of bounds')
    return span * SLOT_BYTES


def _fixed_bytes(value, size, name):
    if isinstance(value, str):
        try:
            value = bytes.fromhex(value.replace('-', ''))
        except ValueError as error:
            raise LogFormatError(name + ' is not hex') from error
    require(isinstance(value, bytes) and len(value) == size, name + ' size mismatch')
    return value


def _crc(block):
    return zlib.crc32(block[:BLOCK_BYTES - 4]) & 0xffffffff


def seal_block(block):
    require(len(block) == BLOCK_BYTES, 'metadata block size mismatch')
    out = bytearray(block)
    struct.pack_into('<I', out, BLOCK_BYTES - 4, _crc(out))
    return bytes(out)


def _check_block(block, magic, reserved_at, versions=(1,)):
    require(len(block) == BLOCK_BYTES, 'short metadata block')
    require(block[:8] == magic, 'metadata magic mismatch')
    require(struct.unpack_from('<I', block, 8)[0] in versions, 'unsupported version')
    require(struct.unpack_from('<I', block, BLOCK_BYTES - 4)[0] == _crc(block),
            'metadata CRC32 mismatch')
    require(block[reserved_at:BLOCK_BYTES - 4] == bytes(BLOCK_BYTES - 4 - reserved_at),
            'nonzero reserved metadata bytes')


def make_manifest(slot, run_uuid, kernel_sha256, created_unix_seconds, span=1):
    size = extent_bytes(slot, span)
    require(type(created_unix_seconds) is int and 0 <= created_unix_seconds < 2**64,
            'invalid preparation timestamp')
    block = bytearray(BLOCK_BYTES)
    block[:8] = MANIFEST_MAGIC
    struct.pack_into('<IIQQQQII', block, 8, 1 if span == 1 else 2, slot, size, PARTITION_BYTES,
                     RESERVED_OFFSET, RESERVED_BYTES, BLOCK_BYTES, MAX_PAYLOAD)
    block[56:72] = _fixed_bytes(run_uuid, 16, 'run UUID')
    struct.pack_into('<Q', block, 72, created_unix_seconds)
    block[80:112] = _fixed_bytes(kernel_sha256, 32, 'kernel SHA-256')
    return seal_block(block)


def parse_manifest(block, expected_slot=None, expected_run_uuid=None,
                   expected_kernel_sha256=None, expected_manifest_sha256=None, expected_span=None):
    _check_block(block, MANIFEST_MAGIC, 112, (1, 2))
    version, slot, size, partition, reserved, reserve_size, block_size, payload = \
        struct.unpack_from('<IIQQQQII', block, 8)
    slot_offset(slot)
    require(size % SLOT_BYTES == 0, 'extent size is not a whole allocation unit')
    span = size // SLOT_BYTES
    require(size == extent_bytes(slot, span), 'extent size mismatch')
    require((version == 1 and span == 1) or (version == 2 and span > 1),
            'manifest version/span mismatch')
    require((partition, reserved, reserve_size, block_size, payload) ==
            (PARTITION_BYTES, RESERVED_OFFSET, RESERVED_BYTES,
             BLOCK_BYTES, MAX_PAYLOAD), 'manifest geometry mismatch')
    if expected_slot is not None:
        require(slot == expected_slot, 'manifest slot differs from selected slot')
    if expected_span is not None:
        require(span == expected_span, 'manifest span differs from receipt')
    if expected_run_uuid is not None:
        require(block[56:72] == _fixed_bytes(expected_run_uuid, 16, 'expected run UUID'),
                'manifest run UUID differs from receipt')
    if expected_kernel_sha256 is not None:
        require(block[80:112] == _fixed_bytes(expected_kernel_sha256, 32, 'expected kernel SHA-256'),
                'manifest kernel SHA-256 differs from receipt')
    if expected_manifest_sha256 is not None:
        require(hashlib.sha256(block).digest() ==
                _fixed_bytes(expected_manifest_sha256, 32, 'expected manifest SHA-256'),
                'manifest bytes differ from preparation receipt')
    return {'version': version, 'slot': slot, 'span': span, 'slot_bytes': size,
            'partition_bytes': partition, 'reserved_offset': reserved,
            'reserved_bytes': reserve_size, 'block_bytes': block_size,
            'maximum_payload_bytes': payload, 'run_uuid': block[56:72].hex(),
            'created_unix_seconds': struct.unpack_from('<Q', block, 72)[0],
            'kernel_sha256': block[80:112].hex(),
            'sha256': hashlib.sha256(block).hexdigest()}


def make_record_header(kind, sequence, stream_offset, run_uuid, payload=b'',
                       lost_bytes=0, status=0, flags=0, stream_sha256=None):
    """Encode a header, principally for independent fixtures and recovery tests."""
    require(kind in (BEGIN, DATA, END), 'invalid record kind')
    require(isinstance(payload, bytes) and len(payload) <= MAX_PAYLOAD, 'payload too large')
    require((kind == DATA and payload) or (kind != DATA and not payload), 'invalid payload for kind')
    for name, value, limit in [('sequence', sequence, 2**64),
                              ('stream offset', stream_offset, 2**64),
                              ('lost bytes', lost_bytes, 2**64),
                              ('status', status, 2**32), ('flags', flags, 2**32)]:
        require(type(value) is int and 0 <= value < limit, 'invalid ' + name)
    digest = hashlib.sha256(payload).digest()
    if kind == END:
        digest = _fixed_bytes(stream_sha256, 32, 'stream SHA-256')
    block = bytearray(BLOCK_BYTES)
    block[:8] = RECORD_MAGIC
    struct.pack_into('<IIQQII', block, 8, 1, kind, sequence, stream_offset,
                     len(payload), 1 + (len(payload) + BLOCK_BYTES - 1) // BLOCK_BYTES)
    block[40:56] = _fixed_bytes(run_uuid, 16, 'run UUID')
    block[56:88] = digest
    struct.pack_into('<QII', block, 88, lost_bytes, status, flags)
    # Decoder validates semantic relationships too; do not let this helper
    # silently construct records that the kernel and reader disagree about.
    result = seal_block(block)
    parse_record_header(result)
    return result


def parse_record_header(block):
    _check_block(block, RECORD_MAGIC, 104)
    version, kind, sequence, offset, size, blocks = struct.unpack_from('<IIQQII', block, 8)
    lost, status, flags = struct.unpack_from('<QII', block, 88)
    require(kind in (BEGIN, DATA, END), 'unknown record kind')
    require(blocks == 1 + (size + BLOCK_BYTES - 1) // BLOCK_BYTES, 'record block count mismatch')
    require(size <= MAX_PAYLOAD, 'record payload exceeds maximum')
    require((kind == DATA and size > 0) or (kind != DATA and size == 0), 'payload size invalid for kind')
    if kind != END:
        require(lost == status == flags == 0, 'non-END status fields must be zero')
    else:
        require(flags & ~3 == 0, 'unknown END flags')
        require(bool(flags & 2) == bool(lost), 'END capture-loss flag/count mismatch')
    if kind == BEGIN:
        require(sequence == offset == 0 and block[56:88] == EMPTY_SHA256, 'invalid BEGIN record')
    return {'version': version, 'kind': kind, 'sequence': sequence,
            'stream_offset': offset, 'payload_bytes': size, 'record_blocks': blocks,
            'run_uuid': block[40:56].hex(), 'sha256': block[56:88].hex(),
            'lost_bytes': lost, 'status': status, 'flags': flags}


def inspect_slot(source, output=None, expected_slot=None, expected_run_uuid=None,
                 expected_kernel_sha256=None, expected_manifest_sha256=None, expected_span=None):
    """Recover the strict valid prefix from one exact manifest-bounded snapshot.

    Metadata and payload are read in bounded chunks. Any bad record stops
    recovery; later records are never scanned for a way around corruption.
    `output`, if supplied, receives the raw bytes of accepted DATA records.
    """
    if isinstance(source, (bytes, bytearray)):
        source = io.BytesIO(source)
    source.seek(0, 2)
    snapshot_bytes = source.tell()
    source.seek(0)
    result = {'format': 'nabu-append-log-v1', 'snapshot_bytes': snapshot_bytes,
              'complete': False, 'state': 'invalid-manifest', 'reason': None,
              'manifest': None, 'records': [], 'data_bytes': 0,
              'data_sha256': EMPTY_SHA256.hex(), 'accepted_slot_bytes': 0,
              'lost_bytes': None, 'end_status': None, 'capture_sealed': False,
              'scope': 'Validated contiguous captured stream only; return-stub messages after sealing are outside it'}
    if not SLOT_BYTES <= snapshot_bytes <= RESERVED_BYTES or snapshot_bytes % SLOT_BYTES:
        result['state'] = 'invalid-snapshot-size'
        result['reason'] = f'expected whole 64 MiB units within reserved area, got {snapshot_bytes}'
        return result
    block = source.read(BLOCK_BYTES)
    if block == ZERO_BLOCK:
        # Do not call a zero header a free slot: preparation separately checks
        # every byte. An abandoned payload may exist beyond this header.
        result.update(state='unprepared', reason='manifest block is zero; whole-slot emptiness not established')
        return result
    try:
        manifest = parse_manifest(block, expected_slot, expected_run_uuid,
                                  expected_kernel_sha256, expected_manifest_sha256, expected_span)
    except LogFormatError as error:
        result['reason'] = str(error)
        return result
    result['manifest'] = manifest
    if snapshot_bytes != manifest['slot_bytes']:
        result.update(state='invalid-snapshot-size', reason='snapshot size differs from manifest extent')
        return result
    slot_bytes = manifest['slot_bytes']
    result['format'] = 'nabu-append-log-v' + str(manifest['version'])
    result['accepted_slot_bytes'] = BLOCK_BYTES
    position, next_sequence, stream_bytes = BLOCK_BYTES, 0, 0
    stream_hash = hashlib.sha256()
    begun = False
    while position + BLOCK_BYTES <= slot_bytes:
        source.seek(position)
        block = source.read(BLOCK_BYTES)
        if block == ZERO_BLOCK:
            result.update(state='incomplete' if begun else 'prepared-not-started',
                          reason='no committed record header', stopped_at=position)
            break
        try:
            record = parse_record_header(block)
            require(record['run_uuid'] == manifest['run_uuid'], 'record run UUID mismatch')
            require(record['sequence'] == next_sequence, 'record sequence is not contiguous')
            require(record['stream_offset'] == stream_bytes, 'record stream offset is not contiguous')
            kind = record['kind']
            require(kind == BEGIN if not begun else kind != BEGIN, 'BEGIN must occur exactly once at the start')
            record_bytes = record['record_blocks'] * BLOCK_BYTES
            require(record_bytes <= slot_bytes - position, 'record exceeds slot boundary')
            if kind == DATA:
                require(record_bytes + BLOCK_BYTES <= slot_bytes - position,
                        'DATA record leaves no space for END')
                padded = source.read(record_bytes - BLOCK_BYTES)
                require(len(padded) == record_bytes - BLOCK_BYTES, 'short payload read')
                payload = padded[:record['payload_bytes']]
                require(padded[len(payload):] == bytes(len(padded) - len(payload)), 'nonzero payload padding')
                require(hashlib.sha256(payload).hexdigest() == record['sha256'], 'DATA payload SHA-256 mismatch')
            elif kind == END:
                require(record['sha256'] == stream_hash.hexdigest(), 'END stream SHA-256 mismatch')
        except LogFormatError as error:
            result.update(state='incomplete', reason=str(error), stopped_at=position)
            break
        record['slot_offset'] = position
        result['records'].append(record)
        next_sequence += 1
        position += record_bytes
        result['accepted_slot_bytes'] = position
        if kind == BEGIN:
            begun = True
        elif kind == DATA:
            stream_bytes += len(payload)
            stream_hash.update(payload)
            if output is not None:
                output.write(payload)
        else:
            result.update(lost_bytes=record['lost_bytes'], end_status=record['status'],
                          capture_sealed=bool(record['flags'] & 1), state='incomplete',
                          reason='END reports capture loss, error, or missing seal')
            tail_is_zero = True
            while position < slot_bytes:
                size = min(MAX_PAYLOAD, slot_bytes - position)
                if source.read(size) != bytes(size):
                    tail_is_zero = False
                    break
                position += size
            if not tail_is_zero:
                result.update(reason='nonzero data follows END', stopped_at=position)
            elif record['status'] == 0 and record['lost_bytes'] == 0 and record['flags'] == 1:
                result.update(complete=True, state='complete', reason=None)
            break
    else:
        result.update(state='incomplete', reason='slot ended without END', stopped_at=position)
    result.update(data_bytes=stream_bytes, data_sha256=stream_hash.hexdigest())
    return result
