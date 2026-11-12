#!/usr/bin/env python3
"""Install verified system/Data windows inside the authorized nabu_system partition.

No GPT, ESP, boot partition, slot or boot command is written by this tool.
An existing committed installation is never reinitialized: --apply verifies it.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
from nabu_storage_layout import geometry, default_layout, extension

ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/data/local/tmp/nabu16/20F66'
TARGET = '/dev/block/sda36'
MIB = 1024 * 1024


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while b := f.read(8 * MIB):
            h.update(b)
    return h.hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def validate_layout(cfg):
    geometry(cfg)
    require([w['name'] for w in cfg['system_windows']] == ['OS', 'SystemOS'], 'Unexpected root windows')
    ranges = [(0, MIB, 'metadata')]
    for w in cfg['system_windows']:
        require(re.fullmatch(r'20F66-[A-Za-z0-9_.-]+', w['filename']), 'Invalid system filename')
        require(re.fullmatch(r'[0-9a-f]{64}', w['sha256']), 'Invalid system hash')
        require(w['offset'] + w['bytes'] <= cfg['root_image_bytes'], 'System window exceeds root area')
        ranges.append((w['offset'], w['bytes'], w['name']))
    ranges += [(cfg[k]['offset'], cfg[k]['bytes'], k) for k in ('data', 'reserved')]
    require(cfg['data']['offset'] == cfg['root_image_bytes'], 'Data overlaps root area')
    end = 0
    for start, size, name in sorted(ranges):
        require(isinstance(start, int) and isinstance(size, int) and start % 4096 == 0 and
                size > 0 and size % 4096 == 0 and start >= end and
                size <= cfg['partition_bytes'] - start, 'Invalid/overlapping range: ' + name)
        end = start + size
    return ranges


def root_header(cfg):
    b = bytearray(4096)
    b[:8] = b'SHNGROOT'
    struct.pack_into('<IIQ', b, 8, 1, len(cfg['system_windows']), cfg['root_image_bytes'])
    for i, w in enumerate(cfg['system_windows']):
        at = 24 + i*128
        b[at:at+len(w['name'])] = w['name'].encode('ascii')
        struct.pack_into('<QQII', b, at+32, w['offset'], w['bytes'], 512, 1)
        b[at+56:at+88] = bytes.fromhex(w['sha256'])
    # A checksummed description for this project's future Data integration.
    # Existing SHNGROOT readers only consume the two read-only system entries.
    extension = json.dumps({'layout': cfg['id'], 'data': cfg['data'], 'reserved': cfg['reserved']},
                           separators=(',', ':')).encode()
    require(len(extension) < 3000, 'Layout extension too large')
    b[1024:1024+len(extension)] = extension
    from nabu_storage_layout import extension as layout_extension
    b[512:560] = layout_extension(cfg)
    b[4064:] = hashlib.sha256(b[:4064]).digest()
    return bytes(b)


def validate_data(bundle, folder, cfg, layout_hash):
    require(bundle['layout_sha256'] == layout_hash and bundle['formatter_commit'] == cfg['formatter']['commit'],
            'Data bundle has different inputs')
    require(bundle['image_bytes'] == cfg['data']['bytes'] and bundle['host_apfsck_passed'] is True,
            'Data image size or host check differs')
    require(re.fullmatch(r'[0-9a-f]{64}', bundle['image_sha256']), 'Invalid Data image hash')
    require(bundle['volume_uuid'] == cfg['data']['volume_uuid'] and
            bundle['container_uuid'] == cfg['data']['container_uuid'] and bundle['case_sensitive'] is True,
            'Data filesystem identity differs')
    end = total = 0
    require(bundle['extents'] and bundle['extents'][0]['offset'] == 0, 'Missing Data superblock')
    for e in bundle['extents']:
        require(re.fullmatch(r'data-extent-[0-9]{3}\.bin', e['filename']), 'Invalid extent filename')
        require(e['offset'] >= end and e['offset'] % 4096 == 0 and e['bytes'] > 0 and
                e['bytes'] % 4096 == 0 and e['bytes'] <= bundle['image_bytes'] - e['offset'],
                'Invalid Data extent')
        p = folder/e['filename']
        require(p.is_file() and not p.is_symlink() and p.stat().st_size == e['bytes'] and
                digest(p) == e['sha256'], 'Data extent bytes differ')
        total += e['bytes']
        end = e['offset'] + e['bytes']
    require(total == bundle['extent_bytes'] and total <= 64*MIB, 'Unexpected Data extent total')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--gpt-backup', type=Path, required=True)
    p.add_argument('--data-bundle', type=Path, required=True)
    p.add_argument('--staging-receipt', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--layout',type=Path,default=default_layout(ROOT))
    p.add_argument('--adb', default=str(ROOT/'host/platform-tools/adb.exe'))
    p.add_argument('--apply', action='store_true')
    a = p.parse_args()
    layout_path = a.layout
    cfg = json.loads(layout_path.read_text())
    layout_hash = digest(layout_path)
    validate_layout(cfg)
    bundle = json.loads((a.data_bundle/'data-image.json').read_text())
    validate_data(bundle, a.data_bundle, cfg, layout_hash)
    inv = json.loads((a.inventory/'inventory.json').read_text())
    permitted = json.loads((ROOT/'device/reclaimed-region.json').read_text())
    gpt = json.loads((a.gpt_backup/'gpt-report.json').read_text())
    lun = next(x for x in gpt['luns'] if x['name'] == 'sda')
    selected = [x for x in lun['partitions'] if x['number'] in (35, 36)]
    require(selected == permitted['partitions'], 'Authorized GPT geometry differs')
    part = selected[1]
    require((part['name'], part['bytes'], lun['logical_block_bytes']) ==
            ('nabu_system', cfg['partition_bytes'], 4096), 'Wrong target partition')
    stage = json.loads(a.staging_receipt.read_text())
    require(stage['status'] == 'all-files-staged-and-verified' and
            stage['device_serial_sha256'] == inv['device_serial_sha256'], 'Staging not complete for this device')
    for w in cfg['system_windows']:
        s = next(x for x in stage['files'] if x['filename'] == w['filename'])
        require((s['bytes'], s['sha256'], s['remote']) == (w['bytes'], w['sha256'], REMOTE+'/'+w['filename']),
                'Staging receipt differs from layout')
    ready = [l.split()[0] for l in subprocess.check_output([a.adb, 'devices'], text=True).splitlines()[1:]
             if l.strip().endswith('\tdevice')]
    require(len(ready) == 1, 'Exactly one ready device is required')
    serial = ready[0]
    require(hashlib.sha256(serial.encode()).hexdigest() == inv['device_serial_sha256'], 'Device identity differs')
    adb = [a.adb, '-s', serial]
    a.output.mkdir(parents=True, exist_ok=True)
    report = {'timestamp': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
              'installer_sha256': digest(Path(__file__)),
              'layout_sha256': layout_hash, 'data_bundle_sha256': digest(a.data_bundle/'data-image.json'),
              'device_serial_sha256': inv['device_serial_sha256'], 'partition': part,
              'mode': 'apply' if a.apply else 'plan', 'status': 'preflight', 'operations': [],
              'gpt_written': False, 'boot_partitions_written': False, 'esp_written': False,
              'device_boot_tested': False, 'kernel_persistence_validated': False}
    receipt = a.output/'installation-receipt.json'

    def save():
        receipt.write_text(json.dumps(report, indent=2)+'\n')

    def shell(command, timeout=60):
        r = subprocess.run(adb+['exec-out', 'su', '-c', command], capture_output=True, timeout=timeout)
        require(r.returncode == 0, 'Device command failed: '+r.stderr.decode(errors='replace')[-1000:])
        return r.stdout

    def read_range(path, start, size):
        require(start >= 0 and size > 0 and size <= 16*MIB, 'Invalid bounded metadata read')
        b = shell(f'dd if={path} bs=1048576 skip={start} count={size} iflag=skip_bytes,count_bytes status=none')
        require(len(b) == size, 'Short device metadata read')
        return b

    def check_gpt():
        records = []
        for unit in gpt['luns']:
            require(re.fullmatch(r'sd[a-z]', unit['name']), 'Invalid LUN in backup')
            for f in unit['files']:
                b = read_range('/dev/block/'+unit['name'], f['lba']*unit['logical_block_bytes'],
                               f['block_count']*unit['logical_block_bytes'])
                require(hashlib.sha256(b).hexdigest() == f['sha256'], 'GPT changed: '+f['file'])
                records.append(f['file'])
        return records

    require(shell('getprop ro.product.device').strip() == b'nabu' and b'uid=0' in shell('id'), 'Expected nabu root')
    dev = shell('cat /sys/class/block/sda36/dev').decode().strip()
    require(re.fullmatch(r'[0-9]+:[0-9]+', dev), 'Invalid block device number')
    guard = ('set -e; set -o pipefail; '
             'test "$(getprop ro.product.device)" = nabu; '
             'test "$(readlink -f /dev/block/by-name/nabu_system)" = /dev/block/sda36; '
             f'test "$(blockdev --getsize64 {TARGET})" = {cfg["partition_bytes"]}; '
             f'test "$(blockdev --getss {TARGET})" = 4096; '
             f'test "$(cat /sys/class/block/sda36/start)" = {part["first_lba"]*8}; '
             f'test "$(cat /sys/class/block/sda36/size)" = {cfg["partition_bytes"]//512}; '
             f'test "$(cat /sys/class/block/sda36/dev)" = {dev}; '
             'test -z "$(ls -A /sys/class/block/sda36/holders)"; '
             f'for mi in /proc/self/mountinfo /proc/1/mountinfo; do '
             f'if grep -qE "^[0-9]+ [0-9]+ {dev} " "$mi"; then exit 71; '
             'else mount_scan_status=$?; test "$mount_scan_status" -eq 1 || exit 72; fi; done; ')
    shell(guard+'true')
    report['gpt_before_verified'] = check_gpt()
    for w in cfg['system_windows']:
        remote = REMOTE+'/'+w['filename']
        result = shell(f'test -f {remote} && test ! -L {remote} && stat -c %s {remote} && sha256sum {remote}', 180).decode().split()
        require(int(result[0]) == w['bytes'] and result[1] == w['sha256'], 'Device source no longer matches')
    header = root_header(cfg)
    marker = bytearray(4096)
    marker[:8] = b'NABUINIT'
    marker[8:40] = bytes.fromhex(layout_hash)
    marker[40:72] = bytes.fromhex(bundle['image_sha256'])
    head = read_range(TARGET, 0, 4096)
    original = (a.inventory/'nabu_system-head.bin').read_bytes()
    require(len(original) == 4096, 'Missing original target header')
    committed = head == header
    require(head[:8] != b'SHNGROOT' or committed,
            'An installed layout already exists. Capacity selection cannot resize or recreate its Data.')
    require(committed or head == original or head == marker, 'Unrecognized target contents; refuse reinitialization')
    report['committed_installation_found'] = committed
    report['ranges'] = [{'name': name, 'offset': start, 'bytes': size}
                        for start, size, name in validate_layout(cfg)]
    save()
    if not a.apply:
        report['status'] = 'plan-verified'; save()
        print(json.dumps(report, indent=2), flush=True)
        return

    def hash_range(start, size):
        require(start >= 0 and size > 0 and size <= cfg['partition_bytes']-start, 'Hash exceeds partition')
        command = guard+f'dd if={TARGET} bs=4194304 skip={start} count={size} iflag=skip_bytes,count_bytes status=none | sha256sum'
        actual = shell(command, 900).decode().split()[0]
        require(re.fullmatch(r'[0-9a-f]{64}', actual), 'Invalid readback hash')
        return actual

    def record(kind, start, size, sha=None):
        item = {'kind': kind, 'offset': start, 'bytes': size}
        if sha:
            item['sha256'] = sha
        report['operations'].append(item); save()

    def write_from(source, start, size):
        require(start >= 0 and start % 4096 == 0 and size > 0 and size % 4096 == 0 and
                size <= cfg['partition_bytes']-start, 'Write exceeds authorized partition')
        require(source == '/dev/zero' or re.fullmatch(re.escape(REMOTE)+r'/[A-Za-z0-9_.-]+', source),
                'Unexpected write input')
        command = guard+f'dd if={source} of={TARGET} bs=4194304 seek={start} count={size} oflag=seek_bytes iflag=count_bytes conv=notrunc,fsync status=none'
        shell(command, 1800)
        record('zero' if source == '/dev/zero' else 'write', start, size)

    def upload(path, name):
        require(re.fullmatch(r'[A-Za-z0-9_.-]+', name), 'Invalid upload name')
        remote = REMOTE+'/'+name
        shell(f'test ! -L {remote}')
        r = subprocess.run(adb+['push', str(path), remote], capture_output=True, timeout=120)
        require(r.returncode == 0, 'Metadata upload failed')
        require(shell('sha256sum '+remote).decode().split()[0] == digest(path), 'Metadata upload hash differs')
        return remote

    lock = ROOT/'log/device/nabu-system-install.lock'
    fd = None
    try:
        fd = lock.open('x')
        fd.write(layout_hash+'\n'); fd.flush()
        report['status'] = 'verifying-existing-installation' if committed else 'installing'; save()
        if not committed:
            for name, start in [('target-first-mib.bin', 0), ('target-last-mib.bin', cfg['partition_bytes']-MIB)]:
                path = a.output/name
                if not path.exists():
                    path.write_bytes(read_range(TARGET, start, MIB))
            marker_path = a.output/'installing-marker.bin'; marker_path.write_bytes(marker)
            write_from(upload(marker_path, 'installing-marker.bin'), 0, 4096)
            for w in cfg['system_windows']:
                print('Writing '+w['name']+' to nabu_system...', flush=True)
                write_from(REMOTE+'/'+w['filename'], w['offset'], w['bytes'])
                actual = hash_range(w['offset'], w['bytes'])
                require(actual == w['sha256'], 'System window readback mismatch: '+w['name'])
                record('readback-verified-'+w['name'], w['offset'], w['bytes'], actual)
            data = cfg['data']
            print(f'Initializing {data["bytes"]//1024**3} GiB Data window...', flush=True)
            write_from('/dev/zero', data['offset'], data['bytes'])
            for e in bundle['extents']:
                remote = upload(a.data_bundle/e['filename'], e['filename'])
                write_from(remote, data['offset']+e['offset'], e['bytes'])
            print('Verifying complete Data window SHA-256...', flush=True)
            actual = hash_range(data['offset'], data['bytes'])
            require(actual == bundle['image_sha256'], 'Data window readback differs from sparse source')
            record('readback-verified-Data', data['offset'], data['bytes'], actual)
            # New target installation only: initialize the owned log reserve.
            # The committed-installation branch below never touches this area.
            reserve = cfg['reserved']
            print('Initializing the new installation log reserve...', flush=True)
            write_from('/dev/zero', reserve['offset'], reserve['bytes'])
            header_path = a.output/'root-header.bin'; header_path.write_bytes(header)
            write_from(upload(header_path, 'root-header.bin'), 0, 4096)
            require(read_range(TARGET, 0, 4096) == header, 'Installation header readback differs')
        else:
            for w in cfg['system_windows']:
                require(hash_range(w['offset'], w['bytes']) == w['sha256'], 'Installed system image differs')
            # Data is mutable after installation. Never compare it with or restore the initial seed here.
            report['existing_data_preserved'] = True
        shell(guard+'sync')
        report['gpt_after_verified'] = check_gpt()
        report['status'] = 'installed-and-readback-verified' if not committed else 'existing-installation-verified-data-preserved'
        save()
        print('Receipt: '+str(receipt), flush=True)
    except Exception as e:
        report.update(status='incomplete', error=str(e).replace(serial, '[device]')); save()
        raise
    finally:
        if fd is not None:
            fd.close(); lock.unlink()


if __name__ == '__main__':
    main()
