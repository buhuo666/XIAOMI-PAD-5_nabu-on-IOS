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
import tomllib
from make_nabu_adt import make_tree, parse, validate_wifi_mac, validate_userland_serial, CHECKPOINTS, DEFAULT_CHECKPOINT
from nabu_log_format import parse_manifest, slot_offset, extent_bytes, BLOCK_BYTES, SLOT_BYTES, PARTITION_BYTES
from nabu_runtime_logs import checked_receipt, zero_suffix_sha256

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT/'artifacts/ci/41959293411-attempt-1/xnu8796-reference-38/artifacts/8796-reference/mach.development.bcm2837'
KERNEL_SHA = '6c35058f01859b8be71e98423c06aa3cbba52858164360a12035936796f5a5d8'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_setup_compat_boot_policy(args, boot_report):
    """The explicit UI policy switch must match the qualified RAM image."""
    switches = [x for x in args if x.startswith('nabu-setup-compat')]
    compat = boot_report.get('setup_compat')
    if compat is None:
        assert not switches, \
            'Setup compatibility requires a qualified library in the bootstrap image'
        return False
    assert switches == ['nabu-setup-compat=1'], 'Qualified setup library requires one exact boot switch'
    assert boot_report.get('private_address_injections_enabled') is True
    assert compat['library'] == '/redwood/lib/libnabu.setup.dylib'
    assert compat['process'] == 'SpringBoard' and compat['host_tests_passed'] is True
    assert compat['required_bootarg'] == 'nabu-setup-compat=1'
    assert re.fullmatch(r'[0-9a-f]{64}', compat['binary_sha256'])
    source = (ROOT/'userland/nabu/src/setup_compat.c').read_text(encoding='utf-8')
    assert hashlib.sha256(source.encode()).hexdigest() == compat['source_sha256_lf'], \
        'Setup library source differs from the qualified bootstrap image'
    return True


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


def verify_prepared_log(shell, prepared, kernel_sha, serial_sha):
    """Read-only bind of one untouched prepared extent to this device and kernel."""
    assert prepared['device_serial_sha256'] == serial_sha
    assert prepared['kernel_sha256'] == kernel_sha
    assert shell('readlink -f /dev/block/by-name/nabu_system').strip() == b'/dev/block/sda36'
    assert int(shell('blockdev --getsize64 /dev/block/sda36')) == PARTITION_BYTES
    offset = slot_offset(prepared['slot'])
    span = prepared.get('span', 1)
    size = extent_bytes(prepared['slot'], span)
    assert prepared.get('slot_bytes', size) == size
    raw = shell(f'dd if=/dev/block/sda36 bs={BLOCK_BYTES} skip={offset//BLOCK_BYTES} count=1 status=none')
    parse_manifest(raw, expected_slot=prepared['slot'], expected_run_uuid=prepared['run_uuid'],
                   expected_kernel_sha256=kernel_sha, expected_manifest_sha256=prepared['manifest_sha256'],
                   expected_span=span)
    expected = zero_suffix_sha256(raw, size)
    actual = shell(f'dd if=/dev/block/sda36 bs={BLOCK_BYTES} skip={offset//BLOCK_BYTES} '
                   f'count={size//BLOCK_BYTES} status=none | sha256sum').decode().split()[0]
    assert actual == expected, 'Prepared runtime log slot was already used or changed; preserve it and select a fresh slot'
    return {'slot': prepared['slot'], 'span': span, 'slot_bytes': size,
            'run_uuid': prepared['run_uuid'], 'prepared_slot_sha256': actual}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT/'artifacts/nabu-chain')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--adb', default='D:/platform-tools/adb.exe')
    ap.add_argument('--gpt-backup', type=Path)
    ap.add_argument('--checkpoint', type=int, choices=CHECKPOINTS, default=DEFAULT_CHECKPOINT)
    ap.add_argument('--bootstrap', type=Path, help='Verified local bootstrap.apfs; report must be beside it')
    ap.add_argument('--wifi-mac-file', type=Path,
                    help='Six binary octets from this device; rechecked against Android before deployment')
    ap.add_argument('--userland-model', choices=['iPad7,11'],
                    help='Explicit model compatibility for the selected iPadOS userland')
    ap.add_argument('--userland-serial-file', type=Path,
                    help='Explicit local compatibility serial, independent of the Android device identity')
    ap.add_argument('--log-preparation', type=Path, help='Verified fresh runtime-log slot preparation receipt')
    ap.add_argument('--touch-firmware-dir', type=Path, help='Local NT36523 firmware, partitions and CRC bank')
    a = ap.parse_args()
    touch_firmware = None
    if a.touch_firmware_dir:
        meta = json.loads((a.touch_firmware_dir/'firmware.json').read_text())
        firmware = a.touch_firmware_dir/meta['firmware']['path']
        assert sha(firmware) == meta['firmware']['sha256']
        touch_firmware = {'firmware': firmware.read_bytes(),
                          'partitions': (a.touch_firmware_dir/'partitions.bin').read_bytes(),
                          'crc-bank': (a.touch_firmware_dir/'crc-bank.bin').read_bytes()}
    wifi_mac = validate_wifi_mac(a.wifi_mac_file.read_bytes()) if a.wifi_mac_file else None
    userland_serial = (validate_userland_serial(a.userland_serial_file.read_text(encoding='ascii').strip())
                       if a.userland_serial_file else None)
    assert sha(KERNEL) == KERNEL_SHA, 'Kernel differs from verified successful build'
    efi = ROOT/'artifacts/nabu-efi'
    for f in json.loads((efi/'build-report.json').read_text())['binaries']:
        assert sha(efi/f['name']) == f['sha256']
    config_bytes=(ROOT/'configs/nabu-unixnu.toml').read_bytes()
    config=tomllib.loads(config_bytes.decode())
    entry=next(x for x in config['entry'] if x['id']=='nabu8796')
    data_enabled='nabu-data=1' in entry['args'].split()
    bootstrap_mode='initrd' in entry
    setup_compat_enabled = False
    log_args=[x for x in entry['args'].split() if x.startswith(('nabu-log-slot','nabu-log-span'))]
    log_prepared=checked_receipt(a.log_preparation) if a.log_preparation else None
    if log_args or log_prepared:
        assert log_prepared
        expected_log_args=[f"nabu-log-slot={log_prepared['slot']}"]
        if log_prepared.get('span',1)>1:
            expected_log_args.append(f"nabu-log-span={log_prepared['span']}")
        assert log_args == expected_log_args
        assert log_prepared['kernel_sha256'] == KERNEL_SHA
    if bootstrap_mode:
        assert a.bootstrap is not None and entry['initrd']==r'\EFI\Nabu16\Payloads\bootstrap.apfs'
        args=entry['args'].split()
        assert all(x in args for x in ['nabu-storage=1','nabu-bootstrap=1','rd=md0','root_apfs=nabu_os'])
        assert not any(x.startswith(('nabu-root-probe=','return_panic=','return_cpu=')) for x in args)
        boot_report=json.loads((a.bootstrap.parent/'bootstrap-report.json').read_text())
        if data_enabled:
            assert boot_report.get('persistent_data_supported') is True
        assert a.bootstrap.stat().st_size==boot_report['bytes']<=256*1024*1024
        assert sha(a.bootstrap)==boot_report['sha256'] and len(boot_report['containers'])==2
        setup_compat_enabled = check_setup_compat_boot_policy(args, boot_report)
        input_bridge = boot_report.get('input_bridge')
        if input_bridge:
            assert input_bridge['process'] == 'backboardd'
            assert input_bridge['library'] == '/redwood/lib/libnabu.input.dylib'
            assert hashlib.sha256((ROOT/'userland/nabu/src/input_bridge.c').read_text().encode()).hexdigest() == input_bridge['source_sha256_lf']
            assert all(x in args for x in ['nabu-input=1', 'nabu-touch=1', 'nabu-buttons=1'])
            assert touch_firmware is not None
        else:
            assert 'nabu-input=1' not in args and touch_firmware is None
    else:
        assert a.bootstrap is None, 'Config has no initrd'
        assert not data_enabled, 'Persistent Data requires the qualified PID1 bootstrap'
        assert not any(x.startswith('nabu-setup-compat') for x in entry['args'].split())
    files = {
        'EFI/Nabu16/UniXNU.efi': (efi/'UniXNU.efi').read_bytes(),
        'EFI/Nabu16/DarwinBoot.efi': (efi/'DarwinBoot.efi').read_bytes(),
        'EFI/Nabu16/Payloads/kernel.macho': KERNEL.read_bytes(),
        'EFI/UniXNU/unixnu.toml': config_bytes,
    }
    if bootstrap_mode:files['EFI/Nabu16/Payloads/bootstrap.apfs']=a.bootstrap.read_bytes()
    adt_path = a.output/'EFI/Nabu16/Payloads/kernel.macho.adt'
    if adt_path.exists():
        blob = adt_path.read_bytes()
        props, nodes = parse(blob)
        chosen = next(p for p, _ in nodes if p['name'] == b'chosen\0')
        assert blob == make_tree(chosen['random-seed'], a.checkpoint, bootstrap_mode, wifi_mac,
                                 a.userland_model, userland_serial, touch_firmware).encode(), 'Existing ADT differs from current builder/checkpoint; use a new output directory'
    else:
        import secrets
        blob = make_tree(secrets.token_bytes(64), a.checkpoint, bootstrap_mode, wifi_mac,
                         a.userland_model, userland_serial, touch_firmware).encode()
    files['EFI/Nabu16/Payloads/kernel.macho.adt'] = blob
    manifest = []
    for rel, data in files.items():
        target = a.output/rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest.append({'path': rel, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    receipt = {'files': manifest, 'status': 'prepared', 'kernel_execution_validated': False,
               'checkpoint': a.checkpoint,
               'root_storage_integrated': True, 'root_mount_validated': False,
               'storage_writes_enabled': bool(log_prepared) or data_enabled,
               'system_data_writes_enabled': data_enabled,
               'runtime_log_preparation': log_prepared, 'deployment_scope': 'nabu_esp files only'}
    receipt.update(bootstrap_ramdisk_used=bootstrap_mode,temporary_data=bootstrap_mode and not data_enabled)
    receipt['setup_compat_enabled'] = setup_compat_enabled
    receipt['input_bridge_enabled'] = bootstrap_mode and bool(boot_report.get('input_bridge'))
    receipt['touch_firmware_in_adt'] = touch_firmware is not None
    receipt['wifi_mac_supplied'] = wifi_mac is not None
    receipt['compatibility_serial_supplied'] = userland_serial is not None
    receipt['userland_model'] = a.userland_model
    if wifi_mac is not None:
        receipt['wifi_mac_source_sha256'] = hashlib.sha256(wifi_mac).hexdigest()
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
    if wifi_mac is not None:
        observed = shell('cat /sys/class/net/wlan0/address').decode().strip()
        assert re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', observed)
        assert bytes.fromhex(observed.replace(':', '')) == wifi_mac, 'Wi-Fi identity differs from candidate'
        assert shell('cat /sys/class/net/wlan0/addr_assign_type').strip() == b'0', 'Wi-Fi address is not marked permanent'
        receipt['wifi_mac_rechecked_on_device'] = True
    assert shell('readlink -f /dev/block/by-name/nabu_esp').strip() == b'/dev/block/sda35'
    assert shell('blockdev --getsize64 /dev/block/sda35').strip() == b'4294967296'
    assert b'uid=0' in shell('id')
    receipt['gpt_before_verified'] = check_gpt(shell, gpt)
    if log_prepared:
        receipt['runtime_log_preflight'] = verify_prepared_log(shell,log_prepared,KERNEL_SHA,inv['device_serial_sha256'])
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
