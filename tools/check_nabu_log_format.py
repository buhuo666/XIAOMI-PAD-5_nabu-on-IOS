#!/usr/bin/env python3
"""Offline append-only log format, torn-write recovery and slot-selection checks."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest

from nabu_log_format import (BEGIN, DATA, END, BLOCK_BYTES, SLOT_BYTES, SLOT_COUNT,
                             RESERVED_OFFSET, PARTITION_BYTES, MAX_PAYLOAD,
                             LogFormatError, inspect_slot, make_manifest,
                             make_record_header, parse_manifest, seal_block, slot_offset)
from nabu_runtime_logs import choose_slot, new_output, zero_suffix_sha256
from stage_nabu_boot_chain import verify_prepared_log

ROOT = Path(__file__).resolve().parents[1]
RUN_UUID = bytes(range(1, 17))
KERNEL_SHA = hashlib.sha256(b'fixture kernel').digest()


class SparseSlot:
    """One bounded slot with zero pages by default; never allocates a GiB."""
    def __init__(self, size=SLOT_BYTES):
        self.size, self.position, self.pages = size, 0, {}

    def seek(self, offset, whence=0):
        self.position = offset + (0 if whence == 0 else self.position if whence == 1 else self.size)
        if self.position < 0:
            raise ValueError('negative seek')
        return self.position

    def tell(self):
        return self.position

    def read(self, count):
        count = max(0, min(count, self.size - self.position))
        output = bytearray(count)
        copied = 0
        while copied < count:
            page, within = divmod(self.position + copied, BLOCK_BYTES)
            take = min(count - copied, BLOCK_BYTES - within)
            if page in self.pages:
                output[copied:copied + take] = self.pages[page][within:within + take]
            copied += take
        self.position += count
        return bytes(output)

    def put(self, position, data):
        if not 0 <= position <= self.size or len(data) > self.size - position:
            raise ValueError('fixture write exceeds snapshot')
        copied = 0
        while copied < len(data):
            page, within = divmod(position + copied, BLOCK_BYTES)
            take = min(len(data) - copied, BLOCK_BYTES - within)
            target = self.pages.setdefault(page, bytearray(BLOCK_BYTES))
            target[within:within + take] = data[copied:copied + take]
            copied += take

    def block(self, position):
        self.seek(position)
        return self.read(BLOCK_BYTES)


def fixture(payloads=(b'first complete line\n', b'next line\n' * 600)):
    raw = SparseSlot()
    raw.put(0, make_manifest(0, RUN_UUID, KERNEL_SHA, 1234))
    raw.put(BLOCK_BYTES, make_record_header(BEGIN, 0, 0, RUN_UUID))
    position, sequence, stream_offset = 2 * BLOCK_BYTES, 1, 0
    starts = []
    stream = b''.join(payloads)
    for payload in payloads:
        for start in range(0, len(payload), MAX_PAYLOAD):
            chunk = payload[start:start + MAX_PAYLOAD]
            starts.append(position)
            raw.put(position, make_record_header(DATA, sequence, stream_offset, RUN_UUID, chunk))
            raw.put(position + BLOCK_BYTES, chunk)
            position += BLOCK_BYTES * (1 + (len(chunk) + BLOCK_BYTES - 1) // BLOCK_BYTES)
            sequence += 1
            stream_offset += len(chunk)
    end = position
    raw.put(end, make_record_header(END, sequence, stream_offset, RUN_UUID,
                                   flags=1, stream_sha256=hashlib.sha256(stream).digest()))
    return raw, starts, end, stream


def mutate_header(raw, position, offset, value, fmt='<I', recalc=True):
    header = bytearray(raw.block(position))
    struct.pack_into(fmt, header, offset, value)
    raw.put(position, seal_block(header) if recalc else header)


class FormatChecks(unittest.TestCase):
    def decode(self, raw, **expected):
        output = io.BytesIO()
        report = inspect_slot(raw, output, **expected)
        self.assertEqual(report['data_bytes'], len(output.getvalue()))
        self.assertEqual(report['data_sha256'], hashlib.sha256(output.getvalue()).hexdigest())
        return report, output.getvalue()

    def test_large_complete_stream_exceeds_old_ring(self):
        payload = bytes(range(256)) * 9000
        raw, starts, end, stream = fixture((payload, b'last partial block'))
        report, saved = self.decode(raw, expected_slot=0, expected_run_uuid=RUN_UUID,
                                    expected_kernel_sha256=KERNEL_SHA)
        self.assertTrue(report['complete'])
        self.assertGreater(len(saved), 2 * 1024 * 1024)
        self.assertEqual(saved, stream)
        self.assertEqual(len(report['records']), len(starts) + 2)
        self.assertEqual(report['accepted_slot_bytes'], end + BLOCK_BYTES)

    def test_manifest_roundtrip(self):
        raw = make_manifest(15, RUN_UUID, KERNEL_SHA, 987654321)
        parsed = parse_manifest(raw, 15, RUN_UUID, KERNEL_SHA)
        self.assertEqual(parsed['created_unix_seconds'], 987654321)
        self.assertEqual(parsed['run_uuid'], RUN_UUID.hex())
        self.assertEqual(slot_offset(15) + SLOT_BYTES, PARTITION_BYTES)

    def test_manifest_bad_crc_and_reserved(self):
        for offset, repair in ((72, False), (113, True)):
            with self.subTest(offset=offset):
                raw, _, _, _ = fixture()
                mutate_header(raw, 0, offset, 7, fmt='<B', recalc=repair)
                report, data = self.decode(raw)
                self.assertEqual(report['state'], 'invalid-manifest')
                self.assertFalse(data)

    def test_manifest_geometry_version_and_slot(self):
        for offset, value, fmt in ((8, 2, '<I'), (12, 16, '<I'), (16, 4096, '<Q'),
                                    (24, 0, '<Q'), (32, 0, '<Q'), (40, 0, '<Q'),
                                    (48, 512, '<I'), (52, 1 << 30, '<I')):
            with self.subTest(offset=offset):
                raw, _, _, _ = fixture()
                mutate_header(raw, 0, offset, value, fmt)
                report, _ = self.decode(raw)
                self.assertEqual(report['state'], 'invalid-manifest')

    def test_receipt_bindings(self):
        for expected in ({'expected_slot': 1}, {'expected_run_uuid': bytes(16)},
                         {'expected_kernel_sha256': bytes(32)},
                         {'expected_manifest_sha256': bytes(32)}):
            with self.subTest(expected=expected):
                raw, _, _, _ = fixture()
                report, data = self.decode(raw, **expected)
                self.assertEqual(report['state'], 'invalid-manifest')
                self.assertEqual(data, b'')

    def test_snapshot_wrong_size(self):
        for size in (0, BLOCK_BYTES, SLOT_BYTES - BLOCK_BYTES, SLOT_BYTES + 1):
            report, data = self.decode(SparseSlot(size))
            self.assertEqual(report['state'], 'invalid-snapshot-size')
            self.assertFalse(data)

    def test_zero_manifest_does_not_claim_free_slot(self):
        raw = SparseSlot()
        raw.put(BLOCK_BYTES * 100, b'old partial payload')
        report, data = self.decode(raw)
        self.assertEqual(report['state'], 'unprepared')
        self.assertIn('not established', report['reason'])
        self.assertFalse(data)

    def test_prepared_not_started(self):
        raw = SparseSlot()
        raw.put(0, make_manifest(0, RUN_UUID, KERNEL_SHA, 1))
        report, data = self.decode(raw)
        self.assertEqual(report['state'], 'prepared-not-started')
        self.assertFalse(report['complete'])
        self.assertFalse(data)

    def test_bad_later_header_preserves_prefix(self):
        for offset, value, fmt in ((8, 2, '<I'), (12, 99, '<I'),
                                   (16, 999, '<Q'), (24, 0, '<Q'),
                                   (24, 2**64 - 1, '<Q'), (32, 2**32 - 1, '<I'),
                                   (36, 2**32 - 1, '<I'), (88, 1, '<Q'),
                                   (96, 1, '<I'), (100, 1, '<I'), (104, 1, '<I')):
            with self.subTest(offset=offset, value=value):
                raw, starts, _, _ = fixture()
                mutate_header(raw, starts[1], offset, value, fmt)
                report, data = self.decode(raw)
                self.assertFalse(report['complete'])
                self.assertEqual(data, b'first complete line\n')
                self.assertEqual(report['stopped_at'], starts[1])

    def test_record_uuid_mismatch(self):
        raw, starts, _, _ = fixture()
        mutate_header(raw, starts[1], 40, 254, '<B')
        report, data = self.decode(raw)
        self.assertIn('UUID', report['reason'])
        self.assertEqual(data, b'first complete line\n')

    def test_torn_header_and_payload(self):
        for target in ('header', 'payload', 'padding'):
            with self.subTest(target=target):
                raw, starts, _, _ = fixture()
                position = starts[1]
                if target == 'header':
                    mutate_header(raw, position, 16, 100, '<Q', recalc=False)
                elif target == 'payload':
                    raw.put(position + BLOCK_BYTES + 10, b'!')
                else:
                    raw.put(position + BLOCK_BYTES + 6000, b'!')
                report, data = self.decode(raw)
                self.assertFalse(report['complete'])
                self.assertEqual(data, b'first complete line\n')

    def test_begin_rules(self):
        for target in ('missing', 'duplicate', 'bad_sha', 'bad_offset'):
            with self.subTest(target=target):
                raw, starts, _, _ = fixture()
                if target == 'missing':
                    raw.put(BLOCK_BYTES, make_record_header(DATA, 0, 0, RUN_UUID, b'abc'))
                    raw.put(2 * BLOCK_BYTES, b'abc')
                elif target == 'duplicate':
                    raw.put(starts[0], make_record_header(BEGIN, 0, 0, RUN_UUID))
                elif target == 'bad_sha':
                    mutate_header(raw, BLOCK_BYTES, 56, 1, '<B')
                else:
                    mutate_header(raw, BLOCK_BYTES, 24, 1, '<Q')
                report, data = self.decode(raw)
                self.assertFalse(report['complete'])
                self.assertFalse(data)

    def test_no_end_is_incomplete(self):
        raw, _, end, stream = fixture()
        raw.put(end, bytes(BLOCK_BYTES))
        report, data = self.decode(raw)
        self.assertEqual(report['state'], 'incomplete')
        self.assertEqual(data, stream)
        self.assertEqual(report['lost_bytes'], None)

    def test_end_hash_flags_loss_error_and_seal(self):
        scenarios = [('hash', 56, 1, '<B'), ('flags', 100, 4, '<I'),
                     ('loss_without_flag', 88, 1, '<Q'), ('flag_without_loss', 100, 3, '<I'),
                     ('error', 96, 5, '<I'), ('unsealed', 100, 0, '<I')]
        for name, offset, value, fmt in scenarios:
            with self.subTest(name=name):
                raw, _, end, stream = fixture()
                mutate_header(raw, end, offset, value, fmt)
                report, data = self.decode(raw)
                self.assertFalse(report['complete'])
                self.assertEqual(data, stream)
        raw, _, end, stream = fixture()
        header = bytearray(raw.block(end))
        struct.pack_into('<QII', header, 88, 7, 10, 3)
        raw.put(end, seal_block(header))
        report, data = self.decode(raw)
        self.assertFalse(report['complete'])
        self.assertEqual((report['lost_bytes'], report['end_status']), (7, 10))
        self.assertTrue(report['capture_sealed'])
        self.assertEqual(data, stream)

    def test_nonzero_after_end_is_incomplete(self):
        raw, _, end, stream = fixture()
        raw.put(end + BLOCK_BYTES * 2, b'uncommitted later bytes')
        report, data = self.decode(raw)
        self.assertFalse(report['complete'])
        self.assertEqual(report['reason'], 'nonzero data follows END')
        self.assertEqual(data, stream)

    def test_no_space_for_end_rejects_last_data(self):
        raw = SparseSlot()
        raw.put(0, make_manifest(0, RUN_UUID, KERNEL_SHA, 1))
        raw.put(BLOCK_BYTES, make_record_header(BEGIN, 0, 0, RUN_UUID))
        position, sequence, offset = 2 * BLOCK_BYTES, 1, 0
        payload = b'Q' * MAX_PAYLOAD
        while SLOT_BYTES - position > 17 * BLOCK_BYTES:
            raw.put(position, make_record_header(DATA, sequence, offset, RUN_UUID, payload))
            raw.put(position + BLOCK_BYTES, payload)
            position += 17 * BLOCK_BYTES
            sequence += 1
            offset += len(payload)
        blocks = (SLOT_BYTES - position) // BLOCK_BYTES
        self.assertGreater(blocks, 1)
        final = b'Z' * ((blocks - 1) * BLOCK_BYTES)
        raw.put(position, make_record_header(DATA, sequence, offset, RUN_UUID, final))
        raw.put(position + BLOCK_BYTES, final)
        report = inspect_slot(raw)
        self.assertFalse(report['complete'])
        self.assertEqual(report['data_bytes'], offset)
        self.assertIn('no space for END', report['reason'])

    def test_never_select_occupied_header_or_payload(self):
        calls = []
        def read(offset, size):
            self.assertGreaterEqual(offset, RESERVED_OFFSET)
            self.assertLessEqual(offset + size, PARTITION_BYTES)
            self.assertLessEqual(size, 8 * 1024 * 1024)
            slot, relative = divmod(offset - RESERVED_OFFSET, SLOT_BYTES)
            calls.append((slot, relative, size))
            if slot == 0:
                return b'X' + bytes(size - 1)
            if slot == 1 and size > BLOCK_BYTES and relative == 0:
                return bytes(BLOCK_BYTES) + b'Y' + bytes(size - BLOCK_BYTES - 1)
            return bytes(size)
        slot, digest, scanned = choose_slot(read)
        self.assertEqual(slot, 2)
        self.assertEqual([entry['state'] for entry in scanned],
                         ['occupied-manifest', 'occupied-payload', 'zero'])
        self.assertEqual(digest, zero_suffix_sha256(b'', SLOT_BYTES))
        with self.assertRaises(RuntimeError):
            choose_slot(read, 1)
        for bad in (-1, SLOT_COUNT, True):
            with self.assertRaises(LogFormatError):
                slot_offset(bad)

    def test_output_reuse_refused(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'fresh'
            self.assertEqual(new_output(path), path.resolve())
            (path / 'old.log').write_bytes(b'keep')
            with self.assertRaises(LogFormatError):
                new_output(path)
            self.assertEqual((path / 'old.log').read_bytes(), b'keep')

    def test_deployment_preflight_binds_fresh_slot(self):
        manifest = make_manifest(1, RUN_UUID, KERNEL_SHA, 1234)
        prepared = {'slot': 1, 'run_uuid': RUN_UUID.hex(),
                    'kernel_sha256': KERNEL_SHA.hex(),
                    'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
                    'device_serial_sha256': '11' * 32}
        offset = slot_offset(1)
        calls = []
        def shell(command):
            calls.append(command)
            self.assertNotIn('of=', command)
            if command == 'readlink -f /dev/block/by-name/nabu_system':
                return b'/dev/block/sda36\n'
            if command == 'blockdev --getsize64 /dev/block/sda36':
                return str(PARTITION_BYTES).encode() + b'\n'
            if command == f'dd if=/dev/block/sda36 bs={BLOCK_BYTES} skip={offset // BLOCK_BYTES} count=1 status=none':
                return manifest
            if command == (f'dd if=/dev/block/sda36 bs={BLOCK_BYTES} skip={offset // BLOCK_BYTES} '
                           f'count={SLOT_BYTES // BLOCK_BYTES} status=none | sha256sum'):
                return zero_suffix_sha256(manifest, SLOT_BYTES).encode() + b'  -\n'
            self.fail('unexpected preflight command: ' + command)
        result = verify_prepared_log(shell, prepared, KERNEL_SHA.hex(), '11' * 32)
        self.assertEqual(result['slot'], 1)
        self.assertEqual(result['run_uuid'], RUN_UUID.hex())
        self.assertEqual(len(calls), 4)

    def test_deployment_preflight_rejects_changed_or_used_slot(self):
        manifest = make_manifest(1, RUN_UUID, KERNEL_SHA, 1234)
        baseline = {'slot': 1, 'run_uuid': RUN_UUID.hex(),
                    'kernel_sha256': KERNEL_SHA.hex(),
                    'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
                    'device_serial_sha256': '11' * 32}
        scenarios = ('used-slot', 'wrong-device', 'wrong-kernel', 'wrong-uuid',
                     'wrong-manifest', 'wrong-slot', 'wrong-link', 'wrong-size', 'short-header')
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                prepared = dict(baseline)
                if scenario == 'wrong-device': prepared['device_serial_sha256'] = '22' * 32
                if scenario == 'wrong-kernel': prepared['kernel_sha256'] = '22' * 32
                if scenario == 'wrong-uuid': prepared['run_uuid'] = '22' * 16
                if scenario == 'wrong-manifest': prepared['manifest_sha256'] = '22' * 32
                if scenario == 'wrong-slot': prepared['slot'] = 2
                calls = []
                def shell(command):
                    calls.append(command)
                    self.assertNotIn('of=', command)
                    if command.startswith('readlink '):
                        return b'/dev/block/sda35\n' if scenario == 'wrong-link' else b'/dev/block/sda36\n'
                    if command.startswith('blockdev '):
                        return b'4096\n' if scenario == 'wrong-size' else str(PARTITION_BYTES).encode()
                    if '| sha256sum' in command:
                        return (('ff' * 32 if scenario == 'used-slot' else
                                 zero_suffix_sha256(manifest, SLOT_BYTES)) + '  -\n').encode()
                    return manifest[:100] if scenario == 'short-header' else manifest
                with self.assertRaises((AssertionError, LogFormatError)):
                    verify_prepared_log(shell, prepared, KERNEL_SHA.hex(), '11' * 32)
                if scenario in ('wrong-device', 'wrong-kernel'):
                    self.assertFalse(calls)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'log/host/nabu-log-format-v1')
    parser.add_argument('--native-fixture', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(FormatChecks)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {'passed': result.wasSuccessful(), 'tests_run': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors),
              'scope': 'Offline format/recovery and bounded zero-slot selection; no device I/O'}
    if args.native_fixture:
        output = io.BytesIO()
        with args.native_fixture.open('rb') as stream:
            decoded = inspect_slot(stream, output)
        expected = bytes([1, 2, 3, 4, 5]) + bytes((i * 29) % 256 for i in range(65536))
        matched = decoded['complete'] and output.getvalue() == expected and len(decoded['records']) == 4
        report['native_fixture'] = {'path': str(args.native_fixture.resolve()), 'matched': matched,
                                    'data_bytes': decoded['data_bytes'], 'data_sha256': decoded['data_sha256']}
        report['passed'] = report['passed'] and matched
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
