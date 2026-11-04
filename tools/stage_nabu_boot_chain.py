#!/usr/bin/env python3
"""Prepare and optionally deploy the verified EFI chain to the existing nabu ESP."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from make_nabu_adt import make_tree, parse, CHECKPOINTS, DEFAULT_CHECKPOINT

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT/'artifacts/ci/41765915458-attempt-1/xnu8796-reference-17/artifacts/8796-reference/mach.development.bcm2837'
KERNEL_SHA = '1a252b0f5506123f228cea5e009abb68d710e35a75ca60bf4025f9bc36f6a3b5'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_gpt(shell, baseline):
    """Compare only bounded GPT metadata reads with the verified backup."""
    records = []
    for lun in baseline['luns']:
        name, block = lun['name'], lun['logical_block_bytes']
        assert re.fullmatch(r'sd[a-z]', name) and block == 4096
        for item in lun['files']:
            start, count = item['lba'], item['block_count']
            assert start >= 0 and 0 < count * block <= 16 * 1024 * 1024
            assert (start + count) * block <= lun['bytes']
            data = shell(f'dd if=/dev/block/{name} bs={block} skip={start} count={count} 2>/dev/null')
            assert len(data) == count * block, 'Short GPT read'
            digest = hashlib.sha256(data).hexdigest()
            assert digest == item['sha256'], 'GPT differs: '+item['file']
            records.append({'file': item['file'], 'sha256': digest})
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT/'artifacts/nabu-chain')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--adb', default='D:/platform-tools/adb.exe')
    ap.add_argument('--gpt-backup', type=Path)
    ap.add_argument('--checkpoint', type=int, choices=CHECKPOINTS, default=DEFAULT_CHECKPOINT)
    a = ap.parse_args()
    assert sha(KERNEL) == KERNEL_SHA, 'Kernel differs from verified successful build'
    efi = ROOT/'artifacts/nabu-efi'
    for f in json.loads((efi/'build-report.json').read_text())['binaries']:
        assert sha(efi/f['name']) == f['sha256']
    files = {
        'EFI/Nabu16/UniXNU.efi': (efi/'UniXNU.efi').read_bytes(),
        'EFI/Nabu16/DarwinBoot.efi': (efi/'DarwinBoot.efi').read_bytes(),
        'EFI/Nabu16/Payloads/kernel.macho': KERNEL.read_bytes(),
        'EFI/UniXNU/unixnu.toml': (ROOT/'configs/nabu-unixnu.toml').read_bytes(),
    }
    adt_path = a.output/'EFI/Nabu16/Payloads/kernel.macho.adt'
    if adt_path.exists():
        blob = adt_path.read_bytes()
        props, nodes = parse(blob)
        chosen = next(p for p, _ in nodes if p['name'] == b'chosen\0')
        assert blob == make_tree(chosen['random-seed'], a.checkpoint).encode(), 'Existing ADT differs from current builder/checkpoint; use a new output directory'
    else:
        import secrets
        blob = make_tree(secrets.token_bytes(64), a.checkpoint).encode()
    files['EFI/Nabu16/Payloads/kernel.macho.adt'] = blob
    manifest = []
    for rel, data in files.items():
        target = a.output/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest.append({'path': rel, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    receipt = {'files': manifest, 'status': 'prepared', 'kernel_execution_validated': False,
               'checkpoint': a.checkpoint,
               'root_storage_integrated': False, 'deployment_scope': 'nabu_esp files only'}
    (a.output/'chain-manifest.json').write_text(json.dumps(receipt, indent=2)+'\n')
    if not a.apply:
        print(json.dumps(receipt, indent=2))
        return
    assert a.gpt_backup is not None, '--apply requires a verified GPT backup'
    gpt = json.loads((a.gpt_backup/'gpt-report.json').read_text())
    permitted = json.loads((ROOT/'device/reclaimed-region.json').read_text())
    lun = next(x for x in gpt['luns'] if x['name'] == 'sda')
    assert [p for p in lun['partitions'] if p['number'] in (35, 36)] == permitted['partitions']
    inv = json.loads((ROOT/'device/inventory-20261103-235705/inventory.json').read_text())
    lines = subprocess.check_output([a.adb, 'devices'], text=True).splitlines()[1:]
    devices = [line.split()[0] for line in lines if line.endswith('\tdevice')]
    assert len(devices) == 1 and hashlib.sha256(devices[0].encode()).hexdigest() == inv['device_serial_sha256']
    adb = [a.adb, '-s', devices[0]]
    def shell(cmd):
        return subprocess.check_output(adb+['exec-out', 'su', '-c', cmd], timeout=120)
    assert shell('getprop ro.product.device').strip() == b'nabu'
    assert shell('getprop ro.boot.slot_suffix').strip() == b'_a'
    assert shell('readlink -f /dev/block/by-name/nabu_esp').strip() == b'/dev/block/sda35'
    assert shell('blockdev --getsize64 /dev/block/sda35').strip() == b'4294967296'
    assert b'uid=0' in shell('id')
    receipt['gpt_before_verified'] = check_gpt(shell, gpt)
    receipt['source_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    receipt['deployment_tool_sha256'] = sha(Path(__file__))
    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    log = ROOT/'log/device'/('nabu-chain-'+stamp)
    log.mkdir(parents=True)
    remote = '/data/local/tmp/nabu16-chain-'+stamp
    mount = '/data/local/tmp/nabu16/esp-chain'
    # Backup files before replacing them. Never reformat or write a raw image.
    shell(f'set -e; mkdir -p {mount}; test ! -L {mount}; test -z "$(ls -A {mount})"; '
          'test -z "$(ls -A /sys/class/block/sda35/holders)"; '
          'dev=$(cat /sys/class/block/sda35/dev); '
          'for mi in /proc/self/mountinfo /proc/1/mountinfo; do '
          'if grep -qE "^[0-9]+ [0-9]+ $dev " "$mi"; then exit 71; '
          'else result=$?; test "$result" -eq 1 || exit 72; fi; done')
    for rel in files:
        assert re.fullmatch(r'[A-Za-z0-9_./-]+', rel)
        subprocess.run(adb+['shell', 'mkdir', '-p', f'{remote}/{Path(rel).parent.as_posix()}'], check=True, capture_output=True)
        pushed = subprocess.run(adb+['push', str(a.output/rel), remote+'/'+rel], capture_output=True)
        if pushed.returncode:
            raise RuntimeError('ADB push failed: '+pushed.stderr.decode(errors='replace'))
    mounted = False
    try:
        shell(f'mount -t vfat -o rw,nosuid,nodev,noexec /dev/block/sda35 {mount}')
        mounted = True
        mounts = [line.split() for line in shell('cat /proc/self/mountinfo').decode().splitlines()]
        actual = next(line for line in mounts if line[4] == mount)
        assert actual[2] == shell('cat /sys/class/block/sda35/dev').decode().strip()
        assert actual[actual.index('-')+1] == 'vfat'
        listing = shell(f'find {mount}/EFI -type f')
        (log/'before-files.txt').write_bytes(listing)
        for record in manifest:
            rel = record['path']
            target = mount+'/'+rel
            existing = shell(f'if test -f {target}; then echo yes; fi').strip()
            if existing:
                backup = log/'previous'/rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(shell(f'cat {target}'))
            staged = remote+'/'+rel
            assert shell(f'sha256sum {staged}').decode().split()[0] == record['sha256']
            parent = Path(rel).parent.as_posix()
            shell(f'set -e; mkdir -p {mount}/{parent}; cp {staged} {target}.new; sync; mv {target}.new {target}; sync')
            assert shell(f'sha256sum {target}').decode().split()[0] == record['sha256']
        shell('sync')
        receipt['gpt_after_verified'] = check_gpt(shell, gpt)
        assert shell('getprop ro.boot.slot_suffix').strip() == b'_a'
        receipt.update(status='deployed-and-readback-verified', timestamp=stamp,
                       device_serial_sha256=inv['device_serial_sha256'], active_slot='_a')
    except BaseException:
        receipt['status'] = 'deployment-failed-see-file-backups'
        raise
    finally:
        if mounted:
            shell(f'umount {mount}')
        (log/'deployment.json').write_text(json.dumps(receipt, indent=2)+'\n')
    assert shell('getprop ro.boot.slot_suffix').strip() == b'_a'
    print(json.dumps({'status': receipt['status'], 'receipt': str(log/'deployment.json')}, indent=2))


if __name__ == '__main__':
    main()
