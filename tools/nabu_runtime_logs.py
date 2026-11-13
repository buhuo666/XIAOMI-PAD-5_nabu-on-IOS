#!/usr/bin/env python3
"""Prepare a new append-only log slot, or recover its verified prefix in Android.

Preparation writes one manifest block in a verified all-zero slot. Collection
retains the full snapshot and recovered prefix, then clears its exact extent
after the device bytes match the saved backup. Offline inspection is read-only.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid
from nabu_storage_layout import (geometry, receipt_geometry, default_layout, LEGACY,
                                 require_kernel_capacity)

from install_ipados_windows import root_header, validate_layout
from nabu_log_format import (BLOCK_BYTES, SLOT_BYTES, SLOT_COUNT, PARTITION_BYTES,
                             RESERVED_OFFSET, RESERVED_BYTES, MAX_PAYLOAD,
                             inspect_slot, make_manifest, parse_manifest, MANIFEST_MAGIC,
                             require, slot_offset, extent_bytes)

ROOT = Path(__file__).resolve().parents[1]
TARGET = '/dev/block/sda36'
READ_CHUNK = 8 * 1024 * 1024
TIMEZONE = datetime.timezone(datetime.timedelta(hours=8))


def now():
    return datetime.datetime.now(TIMEZONE).isoformat()


def file_sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(READ_CHUNK):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, report):
    path.write_text(json.dumps(report, indent=2, ensure_ascii=True) + '\n', encoding='utf-8')


def new_output(path):
    require(not path.is_symlink(), 'output directory must not be a symlink')
    path = path.resolve()
    if path.exists():
        require(path.is_dir() and not any(path.iterdir()), 'use a new or empty output directory')
    else:
        path.mkdir(parents=True)
    return path


def zero_suffix_sha256(prefix, size):
    require(0 <= len(prefix) <= size, 'invalid zero suffix size')
    h = hashlib.sha256(prefix)
    zero = bytes(MAX_PAYLOAD)
    remaining = size - len(prefix)
    while remaining:
        count = min(remaining, len(zero))
        h.update(zero[:count])
        remaining -= count
    return h.hexdigest()


def checked_receipt(path):
    receipt = json.loads(path.read_text(encoding='utf-8'))
    require(receipt.get('status') == 'prepared-and-readback-verified', 'receipt does not describe verified preparation')
    storage=receipt_geometry(receipt)
    slot_offset(receipt.get('slot'),storage)
    require(re.fullmatch(r'[0-9a-f]{32}', receipt.get('run_uuid', '')) is not None, 'receipt UUID invalid')
    require(re.fullmatch(r'[0-9a-f]{64}', receipt.get('kernel_sha256', '')) is not None, 'receipt kernel hash invalid')
    require(re.fullmatch(r'[0-9a-f]{64}', receipt.get('manifest_sha256', '')) is not None, 'receipt manifest hash invalid')
    require(receipt.get('slot_offset') == slot_offset(receipt['slot'],storage) and
            receipt.get('slot_bytes') == extent_bytes(receipt['slot'], receipt.get('span', 1)),
            'receipt geometry differs')
    span = receipt.get('span', 1)
    require(receipt.get('format_version', 1 if span == 1 else 2) == storage.manifest_version(span),
            'receipt version/span differs')
    return receipt


class Device:
    def __init__(self, args):
        inventory = args.inventory
        if inventory.is_dir():
            inventory = inventory / 'inventory.json'
        self.inventory = json.loads(inventory.read_text(encoding='utf-8'))
        self.gpt = json.loads((args.gpt_backup / 'gpt-report.json').read_text(encoding='utf-8'))
        self.layout_path = args.layout
        self.layout = json.loads(self.layout_path.read_text(encoding='utf-8'))
        validate_layout(self.layout)
        self.geometry=geometry(self.layout)
        permitted = json.loads((ROOT / 'device/reclaimed-region.json').read_text(encoding='utf-8'))
        lun = next(unit for unit in self.gpt['luns'] if unit['name'] == 'sda')
        parts = [part for part in lun['partitions'] if part['number'] in (35, 36)]
        require(parts == permitted['partitions'], 'authorized partition geometry differs')
        self.partition = next(part for part in parts if part['number'] == 36)
        require(self.partition['name'] == 'nabu_system' and
                self.partition['bytes'] == self.geometry.partition_bytes and
                lun['logical_block_bytes'] == BLOCK_BYTES,
                'wrong native log partition')
        require((self.partition['last_lba'] - self.partition['first_lba'] + 1) * BLOCK_BYTES == self.geometry.partition_bytes,
                'partition sector range differs')
        installed = json.loads(args.installation_receipt.read_text(encoding='utf-8'))
        require(installed['status'] in ('installed-and-readback-verified',
                                       'existing-installation-verified-data-preserved') and
                installed['device_serial_sha256'] == self.inventory['device_serial_sha256'] and
                installed['partition'] == self.partition and
                installed['layout_sha256'] == file_sha256(self.layout_path),
                'installation receipt differs from selected device/layout')
        found = subprocess.run([args.adb, 'devices'], capture_output=True, text=True, timeout=30)
        require(found.returncode == 0, 'ADB device listing failed')
        ready = [line.split()[0] for line in found.stdout.splitlines()[1:] if line.endswith('\tdevice')]
        require(len(ready) == 1, 'exactly one ready Android device is required')
        self.serial = ready[0]
        self.serial_hash = hashlib.sha256(self.serial.encode()).hexdigest()
        require(self.serial_hash == self.inventory['device_serial_sha256'], 'device identity differs')
        self.adb = [args.adb, '-s', self.serial]
        require(self.shell('getprop ro.product.device').strip() == b'nabu', 'device is not nabu')
        require(self.shell('getprop ro.boot.slot_suffix').strip() == b'_a', 'active slot differs from A')
        require(b'uid=0' in self.shell('id'), 'root ADB shell is required')
        dev = self.shell('cat /sys/class/block/sda36/dev').decode().strip()
        require(re.fullmatch(r'[0-9]+:[0-9]+', dev) is not None, 'invalid block device identity')
        self.guard = (
            'set -e; set -o pipefail; '
            'test "$(getprop ro.product.device)" = nabu; '
            'test "$(getprop ro.boot.slot_suffix)" = _a; '
            'test "$(readlink -f /dev/block/by-name/nabu_system)" = /dev/block/sda36; '
            f'test "$(blockdev --getsize64 {TARGET})" = {self.geometry.partition_bytes}; '
            f'test "$(blockdev --getss {TARGET})" = {BLOCK_BYTES}; '
            f'test "$(cat /sys/class/block/sda36/start)" = {self.partition["first_lba"] * 8}; '
            f'test "$(cat /sys/class/block/sda36/size)" = {self.geometry.partition_bytes // 512}; '
            f'test "$(cat /sys/class/block/sda36/dev)" = {dev}; '
            'test -z "$(ls -A /sys/class/block/sda36/holders)"; '
            'for mi in /proc/self/mountinfo /proc/1/mountinfo; do '
            f'if grep -qE "^[0-9]+ [0-9]+ {dev} " "$mi"; then exit 71; '
            'else nabu_mount_status=$?; test "$nabu_mount_status" -eq 1 || exit 72; fi; done; ')
        self.shell(self.guard + 'true')
        self.gpt_before = self.verify_gpt()
        expected_root = root_header(self.layout)
        require(self.read_range(0, BLOCK_BYTES) == expected_root, 'installed SHNGROOT header differs')
        probe = json.loads((ROOT / 'configs/nabu-storage-probe.json').read_text(encoding='utf-8'))
        self.superblocks = []
        for window in self.layout['system_windows']:
            expected = next(item for item in probe['windows'] if item['name'] == window['name'])
            require((expected['offset'], expected['bytes'], expected['image_sha256']) ==
                    (window['offset'], window['bytes'], window['sha256']), 'system window contract differs')
            digest = hashlib.sha256(self.read_range(window['offset'], BLOCK_BYTES)).hexdigest()
            require(digest == expected['superblock_sha256'], 'system superblock hash differs')
            self.superblocks.append({'name': window['name'], 'sha256': digest})
        self.root_header_sha256 = hashlib.sha256(expected_root).hexdigest()

    def command(self, arguments, timeout=120):
        try:
            result = subprocess.run(arguments, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError('device command timed out') from None
        if result.returncode:
            detail = result.stderr.decode(errors='replace').replace(self.serial, '<device>')[-1000:]
            raise RuntimeError('device command failed: ' + detail)
        return result.stdout

    def shell(self, command, timeout=120):
        return self.command(self.adb + ['exec-out', 'su', '-c', command], timeout)

    def read_range(self, offset, size):
        require(type(offset) is int and type(size) is int and offset >= 0 and
                0 < size <= READ_CHUNK and size <= self.geometry.partition_bytes - offset and
                offset % BLOCK_BYTES == size % BLOCK_BYTES == 0, 'invalid bounded partition read')
        raw = self.shell(f'dd if={TARGET} bs={BLOCK_BYTES} skip={offset // BLOCK_BYTES} '
                         f'count={size // BLOCK_BYTES} status=none')
        require(len(raw) == size, 'short partition read')
        return raw

    def verify_gpt(self):
        records = []
        for lun in self.gpt['luns']:
            require(re.fullmatch(r'sd[a-z]', lun['name']) is not None and
                    lun['logical_block_bytes'] == BLOCK_BYTES, 'invalid GPT backup device')
            for item in lun['files']:
                start, count = item['lba'], item['block_count']
                require(type(start) is int and type(count) is int and start >= 0 and
                        0 < count * BLOCK_BYTES <= 16 * 1024 * 1024 and
                        (start + count) * BLOCK_BYTES <= lun['bytes'], 'invalid GPT read bounds')
                raw = self.shell(f'dd if=/dev/block/{lun["name"]} bs={BLOCK_BYTES} '
                                 f'skip={start} count={count} status=none')
                require(len(raw) == count * BLOCK_BYTES, 'short GPT read')
                digest = hashlib.sha256(raw).hexdigest()
                require(digest == item['sha256'], 'GPT differs: ' + item['file'])
                records.append({'file': item['file'], 'sha256': digest})
        return records

    def range_sha256(self, offset, size):
        require(offset >= 0 and size > 0 and offset % BLOCK_BYTES == size % BLOCK_BYTES == 0 and
                size <= self.geometry.partition_bytes - offset, 'invalid partition hash range')
        raw = self.shell(self.guard + f'dd if={TARGET} bs={BLOCK_BYTES} skip={offset // BLOCK_BYTES} '
                         f'count={size // BLOCK_BYTES} status=none | sha256sum', 180)
        token = raw.decode('ascii').split()[0]
        require(re.fullmatch(r'[0-9a-f]{64}', token) is not None, 'invalid hash response')
        return token


def choose_slot(read_range, requested=None, span=1, storage=LEGACY):
    """Find an entirely zero extent; v2 reservations also own their zero tail."""
    extent_bytes(0 if requested is None else requested, span)
    headers = [read_range(slot_offset(slot,storage), BLOCK_BYTES) for slot in range(SLOT_COUNT)]
    reserved = []
    for slot, header in enumerate(headers):
        require(len(header) == BLOCK_BYTES, 'short allocation-unit header read')
        if any(first <= slot < end for first, end in reserved):
            continue  # Internal unit boundaries hold payload, not new manifests.
        if header[:8] == MANIFEST_MAGIC:
            # Unknown/corrupt declarations must not make their still-zero tail
            # look available to a later preparation. Legacy foreign slot zero
            # is simply occupied and never grants write permission.
            manifest = parse_manifest(header, expected_slot=slot,expected_geometry=storage)
            reserved.append((slot, slot + manifest['span']))
    scanned = []
    choices = range(SLOT_COUNT - span + 1) if requested is None else (requested,)
    for slot in choices:
        offset, size = slot_offset(slot,storage), extent_bytes(slot, span)
        if headers[slot] != bytes(BLOCK_BYTES):
            scanned.append({'slot': slot, 'state': 'occupied-manifest'})
            continue
        if any(slot < end and first < slot + span for first, end in reserved):
            scanned.append({'slot': slot, 'state': 'reserved-extent-overlap'})
            continue
        h = hashlib.sha256()
        empty = True
        for relative in range(0, size, READ_CHUNK):
            take = min(READ_CHUNK, size - relative)
            raw = read_range(offset + relative, take)
            require(len(raw) == take, 'short extent scan')
            h.update(raw)
            if raw != bytes(take):
                empty = False
                break
        scanned.append({'slot': slot, 'span': span, 'state': 'zero' if empty else 'occupied-payload',
                        'checked_bytes': relative + take})
        if empty:
            return slot, h.hexdigest(), scanned
    raise RuntimeError('no selected all-zero log extent is available; existing extents were preserved')


def prepare(args, output):
    require(args.kernel is not None and args.kernel.is_file() and not args.kernel.is_symlink(),
            'prepare requires a regular selected kernel file')
    with args.kernel.open('rb') as stream:
        require(stream.read(4) == bytes.fromhex('cffaedfe'), 'selected kernel is not a thin little-endian Mach-O')
    report = {'timestamp': now(), 'status': 'preflight', 'mode': 'prepare',
              'tool_sha256': file_sha256(Path(__file__)), 'operations': [],
              'existing_slots_reused': False}
    receipt_path = output / 'preparation.json'
    write_json(receipt_path, report)
    try:
        device = Device(args)
        require_kernel_capacity(args.kernel,device.geometry)
        report.update(device_serial_sha256=device.serial_hash,
                      partition=device.partition, gpt_before_verified=device.gpt_before,
                      root_header_sha256=device.root_header_sha256,
                      system_superblocks=device.superblocks)
        span = 1 if args.span is None else args.span
        slot, empty_digest, scanned = choose_slot(device.read_range, args.slot, span,device.geometry)
        size = extent_bytes(slot, span)
        run_uuid = uuid.uuid4().bytes
        kernel_hash = file_sha256(args.kernel)
        manifest = make_manifest(slot, run_uuid, kernel_hash, int(time.time()), span,device.geometry)
        local = output / 'manifest.bin'
        local.write_bytes(manifest)
        manifest_hash = hashlib.sha256(manifest).hexdigest()
        offset = slot_offset(slot,device.geometry)
        report.update(status='zero-slot-verified', slot=slot, run_uuid=run_uuid.hex(),
                      kernel_sha256=kernel_hash, kernel_path=str(args.kernel.resolve()),
                      manifest_sha256=manifest_hash, slot_offset=offset, slot_bytes=size, span=span,
                      format_version=device.geometry.manifest_version(span),storage_geometry=device.geometry.record(),
                      zero_slot_sha256=empty_digest, scanned_slots=scanned,
                      boot_arg=f'nabu-log-slot={slot}' + (f' nabu-log-span={span}' if span > 1 else ''))
        write_json(receipt_path, report)
        remote_dir = '/data/local/tmp/nabu16-log-' + run_uuid.hex()
        remote = remote_dir + '/manifest.bin'
        device.shell(f'set -e; test ! -e {remote_dir}; test ! -L {remote_dir}')
        # adb push runs as the adbd shell identity, not the later su process.
        # Create its private staging directory with that same identity.
        device.command(device.adb + ['shell', 'mkdir', '-m', '0700', remote_dir])
        device.command(device.adb + ['push', str(local), remote])
        device.shell(f'set -e; test ! -L {remote}; test "$(stat -c %s {remote})" = {BLOCK_BYTES}; '
                     f'nabu_manifest_hash=$(sha256sum {remote}); '
                     f'test "${{nabu_manifest_hash%% *}}" = {manifest_hash}')
        # Recheck the entire extent under the same guarded shell immediately before
        # the one-block write. The previously collected scan is not reused as
        # authority after an intervening upload or process interruption.
        zero_digest = zero_suffix_sha256(b'', size)
        require(empty_digest == zero_digest, 'zero-slot scan digest differs')
        report['status'] = 'manifest-write-about-to-start'
        write_json(receipt_path, report)
        device.shell(device.guard +
            f'nabu_slot_hash=$(dd if={TARGET} bs={BLOCK_BYTES} skip={offset // BLOCK_BYTES} '
            f'count={size // BLOCK_BYTES} status=none | sha256sum); '
            f'test "${{nabu_slot_hash%% *}}" = {zero_digest}; '
            f'test ! -L {remote}; test "$(stat -c %s {remote})" = {BLOCK_BYTES}; '
            f'nabu_manifest_hash=$(sha256sum {remote}); '
            f'test "${{nabu_manifest_hash%% *}}" = {manifest_hash}; '
            f'dd if={remote} of={TARGET} bs={BLOCK_BYTES} seek={offset // BLOCK_BYTES} '
            'count=1 conv=notrunc,fsync status=none; sync', 180)
        report['operations'].append({'kind': 'write-manifest', 'partition_offset': offset,
                                     'bytes': BLOCK_BYTES, 'sha256': manifest_hash})
        write_json(receipt_path, report)
        require(device.read_range(offset, BLOCK_BYTES) == manifest, 'manifest readback differs')
        whole_slot_digest = device.range_sha256(offset, size)
        require(whole_slot_digest == zero_suffix_sha256(manifest, size),
                'prepared slot contains unexpected bytes beyond its manifest')
        report.update(prepared_slot_sha256=whole_slot_digest,
                      gpt_after_verified=device.verify_gpt(), status='prepared-and-readback-verified')
        require(device.shell('getprop ro.boot.slot_suffix').strip() == b'_a', 'active slot changed')
        write_json(receipt_path, report)
    except Exception as error:
        report.update(status='failed', error=str(error))
        write_json(receipt_path, report)
        raise
    return {'status': report['status'], 'slot': slot, 'span': span, 'run_uuid': run_uuid.hex(),
            'boot_arg': report['boot_arg'], 'receipt': str(receipt_path)}


def recover(raw_path, output, slot=None, receipt=None, span=None):
    expected = {'expected_slot': slot, 'expected_span': span}
    if receipt is not None:
        require(slot is None or slot == receipt['slot'], 'selected slot differs from receipt')
        require(span is None or span == receipt.get('span', 1), 'selected span differs from receipt')
        expected.update(expected_slot=receipt['slot'], expected_run_uuid=receipt['run_uuid'],
                        expected_kernel_sha256=receipt['kernel_sha256'],
                        expected_manifest_sha256=receipt['manifest_sha256'], expected_span=receipt.get('span', 1),
                        expected_geometry=receipt_geometry(receipt))
    with raw_path.open('rb') as stream, (output / 'runtime.log').open('wb') as recovered:
        result = inspect_slot(stream, recovered, **expected)
    result.update(raw_snapshot_path=str(raw_path.resolve()),
                  raw_snapshot_sha256=file_sha256(raw_path),
                  runtime_log_path=str((output / 'runtime.log').resolve()),
                  reader_sha256=file_sha256(Path(__file__).with_name('nabu_log_format.py')))
    return result


def clear_collected(device, collection, output):
    """Recycle only an exact, fully backed-up extent (user policy: 2026-11-05)."""
    captured=json.loads((collection/'collection.json').read_text())
    recovered=json.loads((collection/'report.json').read_text())
    slot,span=captured['slot'],captured.get('span',1)
    offset,size=slot_offset(slot,device.geometry),extent_bytes(slot,span)
    raw=collection/f'slot-{slot:02d}.bin'
    require(captured['status']=='snapshot-collected' and captured['bytes_read']==size and
        captured['slot_offset']==offset and captured['slot_bytes']==size and
        captured['device_serial_sha256']==device.serial_hash and captured['partition']==device.partition,
        'collection is not a complete backup of this device extent')
    require(raw.is_file() and not raw.is_symlink() and raw.stat().st_size==size,'missing complete raw backup')
    digest=file_sha256(raw)
    require(digest==recovered['raw_snapshot_sha256'],'raw backup changed since collection')
    with raw.open('rb') as stream:
        manifest=parse_manifest(stream.read(BLOCK_BYTES),expected_slot=slot,expected_span=span,expected_geometry=device.geometry)
    require(manifest==recovered['manifest'],'saved manifest differs from recovery report')
    require(device.range_sha256(offset,size)==digest,'device log changed after collection; not cleared')
    report={'timestamp':now(),'status':'backup-verified','slot':slot,'span':span,'offset':offset,'bytes':size,
        'backup':str(raw.resolve()),'backup_sha256':digest,'device_serial_sha256':device.serial_hash,
        'device_writes':False}
    path=output/'clearing.json';write_json(path,report)
    # Recompare in the same guarded operation immediately before zeroing.
    device.shell(device.guard+
        f'nabu_saved_hash=$(dd if={TARGET} bs={BLOCK_BYTES} skip={offset//BLOCK_BYTES} count={size//BLOCK_BYTES} status=none | sha256sum); '
        f'test "${{nabu_saved_hash%% *}}" = {digest}; '
        f'dd if=/dev/zero of={TARGET} bs={BLOCK_BYTES} seek={offset//BLOCK_BYTES} count={size//BLOCK_BYTES} conv=notrunc,fsync status=none; sync',180)
    report.update(status='cleared-readback-pending',device_writes=True);write_json(path,report)
    zero=zero_suffix_sha256(b'',size)
    require(device.range_sha256(offset,size)==zero,'cleared extent is not all zero')
    report.update(status='cleared-and-readback-verified',zero_sha256=zero,gpt_after_verified=device.verify_gpt())
    write_json(path,report)
    return report


def collect(args, output, receipt):
    slot = args.slot if args.slot is not None else receipt['slot'] if receipt is not None else None
    require(slot is not None, 'collect requires --slot or --receipt')
    device = Device(args)
    offset = slot_offset(slot,device.geometry)
    if receipt is not None:
        require(receipt_geometry(receipt)==device.geometry,'receipt geometry differs from installed layout')
        require(receipt.get('device_serial_sha256') == device.serial_hash, 'receipt device differs')
    if receipt is not None:
        span = receipt.get('span', 1)
        require(args.span is None or args.span == span, 'selected span differs from receipt')
    elif args.span is not None:
        span = args.span
    else:
        span = parse_manifest(device.read_range(offset, BLOCK_BYTES), expected_slot=slot,expected_geometry=device.geometry)['span']
    # A receipt or explicit extent keeps even a damaged manifest recoverable as
    # a raw bounded snapshot. With no geometry supplied, a valid header is needed.
    size = extent_bytes(slot, span)
    raw = output / f'slot-{slot:02d}.bin'
    capture = {'timestamp': now(), 'mode': 'collect', 'status': 'reading', 'slot': slot,
               'device_serial_sha256': device.serial_hash, 'partition': device.partition,
               'slot_offset': offset, 'slot_bytes': size, 'span': span,
               'gpt_before_verified': device.gpt_before, 'device_writes': False,
               'bytes_read': 0}
    capture_path = output / 'collection.json'
    write_json(capture_path, capture)
    try:
        with raw.open('wb') as destination:
            for relative in range(0, size, READ_CHUNK):
                chunk = device.read_range(offset + relative, min(READ_CHUNK, size - relative))
                destination.write(chunk)
                capture['bytes_read'] += len(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        capture.update(status='snapshot-collected', gpt_after_verified=device.verify_gpt())
        write_json(capture_path, capture)
        report = recover(raw, output, slot, receipt, span)
        report.update(device_serial_sha256=device.serial_hash, collection_receipt=str(capture_path))
        write_json(output / 'report.json', report)
        cleared=clear_collected(device,output,output)
        capture.update(device_writes=True,extent_cleared=True,clearing_receipt=str(output/'clearing.json'))
        write_json(capture_path,capture)
        return {'state': report['state'], 'complete': report['complete'], 'slot': slot,
                'data_bytes': report['data_bytes'], 'reason': report['reason'],
                'clearing_status':cleared['status'],
                'report': str(output / 'report.json'), 'runtime_log': str(output / 'runtime.log')}
    except Exception as error:
        capture.update(status='failed', error=str(error))
        write_json(capture_path, capture)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare', action='store_true')
    action.add_argument('--collect', action='store_true')
    action.add_argument('--inspect', type=Path, metavar='RAW_SLOT')
    action.add_argument('--clear-collected',type=Path,metavar='COLLECTION_DIR',help='Clear a previously collected extent after exact backup/device verification')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--layout',type=Path,default=default_layout(ROOT))
    parser.add_argument('--slot', type=int)
    parser.add_argument('--span', type=int, help='Explicit count of adjacent 64 MiB allocation units')
    parser.add_argument('--kernel', type=Path)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--gpt-backup', type=Path)
    parser.add_argument('--adb', default='D:/platform-tools/adb.exe')
    parser.add_argument('--inventory', type=Path,
                        default=ROOT / 'device/inventory-20261103-235705/inventory.json')
    parser.add_argument('--installation-receipt', type=Path,
                        default=ROOT / 'log/device/install-20F66-20261104/installation-receipt.json')
    args = parser.parse_args()
    if args.slot is not None:
        slot_offset(args.slot)
    if args.span is not None:
        extent_bytes(0 if args.slot is None else args.slot, args.span)
    require(args.inspect is not None or args.gpt_backup is not None,
            'device prepare/collect requires --gpt-backup')
    require(not args.prepare or args.receipt is None, '--receipt binds recovery, not new preparation')
    receipt = checked_receipt(args.receipt) if args.receipt else None
    output = new_output(args.output)
    if args.prepare:
        result = prepare(args, output)
    elif args.collect:
        result = collect(args, output, receipt)
    elif args.clear_collected:
        result = clear_collected(Device(args),args.clear_collected,output)
    else:
        require(args.inspect.is_file(), 'raw snapshot is not a file')
        result = recover(args.inspect, output, args.slot, receipt, args.span)
        write_json(output / 'report.json', result)
        result = {key: result[key] for key in ('state', 'complete', 'data_bytes', 'reason')}
        result['report'] = str(output / 'report.json')
    print(json.dumps(result, indent=2, ensure_ascii=True))


if __name__ == '__main__':
    main()
