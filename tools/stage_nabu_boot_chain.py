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
from make_nabu_adt import make_tree, parse, validate_wifi_mac, validate_userland_serial, platform_uuid_from_soc, CHECKPOINTS, DEFAULT_CHECKPOINT
from nabu_log_format import parse_manifest, slot_offset, extent_bytes, BLOCK_BYTES, SLOT_BYTES, PARTITION_BYTES
from nabu_runtime_logs import checked_receipt, zero_suffix_sha256
from nabu_rmtfs_sparse import pack as pack_rmtfs
from nabu_servreg import encode as encode_servreg

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT/'artifacts/ci/41959293411-attempt-1/xnu8796-reference-38/artifacts/8796-reference/mach.development.bcm2837'


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
    ap.add_argument('--kernel', type=Path, default=KERNEL)
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
    ap.add_argument('--image4-nonce-key-file', type=Path,
                    help='Persistent 16-byte software key for Image4 nonce selector 2212')
    ap.add_argument('--rtc-calibration', type=Path, help='Android time / PM8150 RTC capture from capture_nabu_power.py')
    ap.add_argument('--platform-identity', type=Path, help='Local capture containing the real Qualcomm SoC identity')
    ap.add_argument('--native-usb', action='store_true', help='Select the experimental native Apple USB controller for this staged boot')
    wireless = ap.add_mutually_exclusive_group()
    wireless.add_argument('--wireless-survey', action='store_true', help='Enable the compiled Nabu wireless hardware survey')
    wireless.add_argument('--bluetooth-version', action='store_true', help='Enable Nabu wireless power and Bluetooth UART ROM version trial')
    wireless.add_argument('--bluetooth-firmware', type=Path, help='Prepared original-board Bluetooth firmware for the UART download trial')
    ap.add_argument('--modem-firmware', type=Path, help='Prepared Nabu modem metadata/segments for the bounded PAS boot trial')
    ap.add_argument('--modem-glink', action='store_true', help='Negotiate GLINK/IPCRTR and inventory QRTR services before stopping the modem')
    ap.add_argument('--wlan-firmware', type=Path, help='Original wlanmdsp.mbn served read-only over QRTR TFTP')
    ap.add_argument('--rmtfs-snapshot', type=Path, help='This board modem storage snapshots for RAM-only RMTFS')
    ap.add_argument('--servreg',type=Path,help='Original-board JSON service-registry directory')
    ap.add_argument('--wlan-qmi',action='store_true',help='Register WLAN QMI client and query host capability/MSA information')
    ap.add_argument('--wlan-msa',action='store_true',help='Assign returned MSA regions, signal ready and query chipset capabilities')
    ap.add_argument('--wlan-board',type=Path,help='Original board parameters for QMI download and calibration report')
    ap.add_argument('--wlan-native-service',action='store_true',help='Publish the real wlan device and native en0 for service discovery; station control is separate')
    ap.add_argument('--bluetooth-transport', action='store_true', help='Keep the initialized Bluetooth UART running and publish its board capabilities')
    ap.add_argument('--adsp-trial', action='store_true', help='Run the bounded Nabu PAS1 ADSP boot/readiness/shutdown trial')
    ap.add_argument('--gpu-firmware', type=Path, help='Original local A640 GMU/SQE/ZAP inputs; enables the linked A640 backend')
    a = ap.parse_args()
    assert not a.modem_glink or a.modem_firmware, 'GLINK trial requires the signed modem firmware'
    assert not a.wlan_firmware or a.modem_glink, 'WLAN firmware transfer requires GLINK'
    assert not a.rmtfs_snapshot or a.modem_glink, 'RMTFS requires GLINK'
    assert not a.servreg or a.modem_glink, 'Service registry requires GLINK'
    assert not a.wlan_qmi or a.modem_glink, 'WLAN QMI requires GLINK'
    assert not a.wlan_msa or a.wlan_qmi, 'MSA setup requires WLAN QMI'
    assert not a.wlan_board or a.wlan_msa, 'Board parameter download requires MSA setup'
    assert not a.wlan_native_service or (a.wlan_board and a.wifi_mac_file), 'Native WLAN discovery requires the board identity and configured WLAN path'
    assert not a.bluetooth_transport or a.bluetooth_firmware, 'Bluetooth transport requires controller firmware'
    bluetooth_firmware = None
    if a.bluetooth_firmware:
        meta = json.loads((a.bluetooth_firmware/'firmware.json').read_text())
        bluetooth_firmware = {'rampatch': (a.bluetooth_firmware/meta['rampatch']).read_bytes(),
                              'nvm': (a.bluetooth_firmware/meta['nvm']).read_bytes(),
                              'address-hci': (a.bluetooth_firmware/meta['address_hci']).read_bytes()}
    gpu_firmware = None
    if a.gpu_firmware:
        gpu_firmware = {key: (a.gpu_firmware/name).read_bytes() for key, name in (
            ('gmu-firmware', 'a640_gmu.bin'), ('sqe-firmware', 'a630_sqe.fw'),
            ('zap-metadata', 'a640_zap.mdt'), ('zap-shader', 'a640_zap.b02'))}
    modem_firmware = None
    if a.modem_firmware:
        assert a.bluetooth_firmware, 'The modem trial retains the qualified Bluetooth initialization'
        meta = json.loads((a.modem_firmware/'firmware.json').read_text())
        modem_firmware = {'metadata': (a.modem_firmware/meta['metadata']).read_bytes()}
        for segment in meta['segments']:
            if segment['file']:
                modem_firmware[f"segment-{segment['index']:02}"] = (a.modem_firmware/segment['file']).read_bytes()
        if a.wlan_firmware: modem_firmware['wlanmdsp'] = a.wlan_firmware.read_bytes()
        if a.servreg: modem_firmware['servreg']=encode_servreg(a.servreg)
        if a.wlan_qmi: modem_firmware['wlfw-qmi']=(1).to_bytes(4,'little')
        if a.wlan_msa: modem_firmware['wlfw-msa']=(1).to_bytes(4,'little')
        if a.wlan_board: modem_firmware['wlfw-board']=a.wlan_board.read_bytes()
        if a.rmtfs_snapshot:
            for file in json.loads((a.rmtfs_snapshot/'snapshot.json').read_text())['files']:
                modem_firmware['rmtfs-'+file['partition']] = pack_rmtfs((a.rmtfs_snapshot/file['file']).read_bytes())
    platform_identity = json.loads(a.platform_identity.read_text()) if a.platform_identity else None
    platform_uuid = platform_uuid_from_soc(platform_identity['soc_identity']) if platform_identity else None
    rtc_calibration = json.loads(a.rtc_calibration.read_text()) if a.rtc_calibration else None
    rtc_offset = rtc_calibration['rtc_offset_seconds'] if rtc_calibration else None
    if rtc_calibration:
        assert rtc_calibration['device'] == 'nabu' and rtc_offset > 0
    image4_nonce_key = a.image4_nonce_key_file.read_bytes() if a.image4_nonce_key_file else None
    kernel_sha = sha(a.kernel)
    touch_firmware = None
    if a.touch_firmware_dir:
        meta = json.loads((a.touch_firmware_dir/'firmware.json').read_text())
        firmware = a.touch_firmware_dir/meta['firmware']['path']
        touch_firmware = {'firmware': firmware.read_bytes(),
                          'partitions': (a.touch_firmware_dir/'partitions.bin').read_bytes(),
                          'crc-bank': (a.touch_firmware_dir/'crc-bank.bin').read_bytes()}
    wifi_mac = validate_wifi_mac(a.wifi_mac_file.read_bytes()) if a.wifi_mac_file else None
    userland_serial = (validate_userland_serial(a.userland_serial_file.read_text(encoding='ascii').strip())
                       if a.userland_serial_file else None)
    efi = ROOT/'artifacts/nabu-efi'
    config_bytes=(ROOT/'configs/nabu-unixnu.toml').read_bytes()
    config=tomllib.loads(config_bytes.decode())
    entry=next(x for x in config['entry'] if x['id']=='nabu8796')
    if a.wireless_survey or a.bluetooth_version or a.bluetooth_firmware:
        kernel_report=json.loads(a.kernel.with_name('prelink-report.json').read_text())
        assert kernel_report['data_block']['wireless_start'], 'Wireless survey requires its linked Nabu module'
        if a.bluetooth_version or a.bluetooth_firmware:
            assert kernel_report['data_block']['bluetooth_trial'], 'Bluetooth trial requires its linked ROM transport'
        if a.bluetooth_firmware:
            assert kernel_report['data_block']['bluetooth_firmware'], 'Bluetooth download requires its linked firmware loader'
        if a.modem_firmware:
            assert kernel_report['data_block']['modem_trial'], 'Modem startup requires its linked PAS/SMP2P implementation'
        old_args=entry['args']
        entry['args'] += ' nabu-wireless=' + ('5' if a.modem_glink else '4' if a.modem_firmware else '3' if a.bluetooth_firmware else '2' if a.bluetooth_version else '1')
        if a.bluetooth_transport:
            entry['args'] += ' nabu-bt-transport=1'
        assert config_bytes.count(old_args.encode())==1
        config_bytes=config_bytes.replace(old_args.encode(),entry['args'].encode(),1)
    if a.adsp_trial:
        kernel_report=json.loads(a.kernel.with_name('prelink-report.json').read_text())
        assert kernel_report['data_block']['adsp_trial'], 'ADSP trial requires its linked Nabu driver'
        assert a.bootstrap and json.loads(a.bootstrap.with_name('bootstrap-report.json').read_text()).get('adsp_firmware'), 'ADSP trial requires original firmware in Boot APFS'
        old_args=entry['args']
        entry['args'] += ' nabu-adsp=1'
        assert config_bytes.count(old_args.encode())==1
        config_bytes=config_bytes.replace(old_args.encode(),entry['args'].encode(),1)
    if a.gpu_firmware:
        kernel_report=json.loads(a.kernel.with_name('prelink-report.json').read_text())
        assert kernel_report['data_block'].get('gpu_start'), 'GPU inputs require the linked A640 backend'
        old_args=entry['args']
        entry['args'] += ' nabu-gpu=1'
        assert config_bytes.count(old_args.encode())==1
        config_bytes=config_bytes.replace(old_args.encode(),entry['args'].encode(),1)
    if a.native_usb:
        kernel_report=json.loads(a.kernel.with_name('prelink-report.json').read_text())
        assert kernel_report['stock_apple_usb_included'] and kernel_report['data_block']['usb_class']
        assert platform_uuid, 'Native USB uses this board-derived identity'
        old_args=entry['args']
        args=[x for x in old_args.split() if not x.startswith('nabu-usb-cdc-log')]
        args.append('nabu-usb-native=1')
        entry['args']=' '.join(args)
        assert config_bytes.count(old_args.encode())==1
        config_bytes=config_bytes.replace(old_args.encode(),entry['args'].encode(),1)
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
        assert log_prepared['kernel_sha256'] == kernel_sha
    if bootstrap_mode:
        assert a.bootstrap is not None and entry['initrd']==r'\EFI\Nabu16\Payloads\bootstrap.apfs'
        args=entry['args'].split()
        assert all(x in args for x in ['nabu-storage=1','nabu-bootstrap=1','rd=md0','root_apfs=nabu_os'])
        assert not any(x.startswith(('nabu-root-probe=','return_panic=','return_cpu=')) for x in args)
        boot_report=json.loads((a.bootstrap.parent/'bootstrap-report.json').read_text())
        if boot_report.get('local_activation'):
            assert data_enabled, 'Local activation state requires persistent APFS Data'
            args.append('nabu-local-activation=1')
            config_bytes=config_bytes.replace(entry['args'].encode(),' '.join(args).encode(),1)
            entry['args']=' '.join(args)
        if data_enabled:
            assert boot_report.get('persistent_data_supported') is True
        assert a.bootstrap.stat().st_size==boot_report['bytes']<=256*1024*1024
        assert sha(a.bootstrap)==boot_report['sha256']
        assert [c['name'] for c in boot_report['containers']] == (
            ['Boot.apfs', 'NabuInit.apfs', 'App.apfs'] if boot_report.get('app_cryptex') else ['Boot.apfs', 'NabuInit.apfs'])
        setup_compat_enabled = check_setup_compat_boot_policy(args, boot_report)
        input_bridge = boot_report.get('input_bridge')
        if input_bridge:
            assert input_bridge['process'] == 'backboardd'
            assert input_bridge['library'] == '/redwood/lib/libnabu.input.dylib'
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
        'EFI/Nabu16/Payloads/kernel.macho': a.kernel.read_bytes(),
        'EFI/UniXNU/unixnu.toml': config_bytes,
    }
    if bootstrap_mode:files['EFI/Nabu16/Payloads/bootstrap.apfs']=a.bootstrap.read_bytes()
    adt_path = a.output/'EFI/Nabu16/Payloads/kernel.macho.adt'
    if adt_path.exists():
        blob = adt_path.read_bytes()
        props, nodes = parse(blob)
        chosen = next(p for p, _ in nodes if p['name'] == b'chosen\0')
        assert blob == make_tree(chosen['random-seed'], a.checkpoint, bootstrap_mode, wifi_mac,
                                 a.userland_model, userland_serial, touch_firmware, image4_nonce_key, rtc_offset, platform_uuid, bluetooth_firmware, modem_firmware, a.bluetooth_transport, a.wlan_native_service, gpu_firmware).encode(), 'Existing ADT differs from current builder/checkpoint; use a new output directory'
    else:
        import secrets
        blob = make_tree(secrets.token_bytes(64), a.checkpoint, bootstrap_mode, wifi_mac,
                         a.userland_model, userland_serial, touch_firmware, image4_nonce_key, rtc_offset, platform_uuid, bluetooth_firmware, modem_firmware, a.bluetooth_transport, a.wlan_native_service, gpu_firmware).encode()
    files['EFI/Nabu16/Payloads/kernel.macho.adt'] = blob
    assert len(blob) <= 16*1024*1024, 'ADT exceeds the current DarwinBoot ReadFile limit (16 MiB)'
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
    receipt['gpu_firmware_in_adt'] = gpu_firmware is not None
    receipt['image4_software_nonce_key_supplied'] = image4_nonce_key is not None
    receipt['rtc_calibration'] = rtc_calibration
    receipt['platform_uuid_from_soc'] = platform_identity is not None
    receipt['native_usb_selected'] = a.native_usb
    receipt['wifi_mac_supplied'] = wifi_mac is not None
    receipt['wlan_native_service_selected'] = a.wlan_native_service
    receipt['bluetooth_transport_selected'] = a.bluetooth_transport
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
        receipt['runtime_log_preflight'] = verify_prepared_log(shell,log_prepared,kernel_sha,inv['device_serial_sha256'])
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
