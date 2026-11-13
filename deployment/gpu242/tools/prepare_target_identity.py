"""Capture target-owned identity/calibration and prepare local chain inputs.

Reads tablet files only. Firmware reuse requires explicit hardware review.
No device partitions or files are written by this script.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import shlex
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bluetooth-address', required=True, help='Actual destination tablet Bluetooth address, AA:BB:CC:DD:EE:FF')
    p.add_argument('--confirm-matching-board-firmware', action='store_true', required=True,
                   help='Only after confirming the destination touch/panel and Bluetooth ROM match the bundled reference.')
    a = p.parse_args()
    if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', a.bluetooth_address):
        p.error('Invalid Bluetooth address.')
    address = bytes.fromhex(a.bluetooth_address.replace(':',''))
    if address in (bytes(6), b'\xff'*6, bytes.fromhex('020000000000')):
        p.error('A real target address is required.')
    inv = json.loads((ROOT/'device/target/inventory.json').read_text(encoding='utf-8'))
    adb = str(ROOT/'host/platform-tools/adb.exe')
    rows = subprocess.check_output([adb,'devices'], text=True).splitlines()[1:]
    devices = [x.split()[0] for x in rows if x.strip().endswith('\tdevice')]
    if len(devices) != 1 or hashlib.sha256(devices[0].encode()).hexdigest() != inv['device_serial_sha256']:
        raise ValueError('Connect the scanned destination tablet only.')
    def shell(cmd, timeout=90):
        return subprocess.check_output([adb,'-s',devices[0],'exec-out','su','-c',cmd], timeout=timeout)
    if shell('getprop ro.product.device').strip() != b'nabu':
        raise ValueError('Expected nabu.')
    out = ROOT/'target-inputs/personalized'
    out.mkdir(exist_ok=False)
    mac = shell('cat /sys/class/net/wlan0/address').decode().strip()
    if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', mac) or shell('cat /sys/class/net/wlan0/addr_assign_type').strip() != b'0':
        raise ValueError('Permanent wlan0 address unavailable; do not substitute a randomized address.')
    from make_nabu_adt import validate_wifi_mac
    (out/'wifi-mac.bin').write_bytes(validate_wifi_mac(bytes.fromhex(mac.replace(':',''))))
    (out/'bluetooth-address-hci.bin').write_bytes(address[::-1])
    (out/'image4-nonce-key.bin').write_bytes(secrets.token_bytes(16))
    subprocess.run([sys.executable,str(ROOT/'tools/capture_nabu_power.py'),'--adb',adb,
                    '--output',str(out/'power-and-identity.json')], check=True, stdout=subprocess.DEVNULL)
    power = json.loads((out/'power-and-identity.json').read_text())
    (out/'compatibility-label.txt').write_text('NABU'+format(power['soc_identity']['serial_number'],'X')+'\n', encoding='ascii')
    raw = out/'wireless-original'
    raw.mkdir()
    origins = json.loads((ROOT/'reference/wireless-file-origins.json').read_text())
    for row in origins:
        source = row['device_path']
        data = shell('cat '+shlex.quote(source))
        if data != (ROOT/'firmware/nabu-wireless'/row['file']).read_bytes():
            raise ValueError('Target firmware differs; review before building: '+row['file'])
        (raw/row['file']).write_bytes(data)
    # Board file selected in the GPU242 reference is distinct from bdwlan.bin.
    board = shell('cat /vendor/firmware_mnt/image/bd_k82c.bin')
    if board != (ROOT/'firmware/nabu-wireless/bd_k82c.bin').read_bytes():
        raise ValueError('Target board calibration template differs.')
    (raw/'bd_k82c.bin').write_bytes(board)
    gpu = out/'gpu'
    gpu.mkdir()
    for name in ['a640_gmu.bin','a630_sqe.fw','a640_zap.mdt','a640_zap.b02']:
        data = shell('cat /vendor/firmware/'+name)
        if data != (ROOT/'firmware/adreno640'/name).read_bytes():
            raise ValueError('Target GPU firmware differs: '+name)
        (gpu/name).write_bytes(data)
    rmtfs = out/'rmtfs'
    rmtfs.mkdir()
    snapshots = []
    for name in ['modemst1','modemst2','fsg','fsc']:
        path = '/dev/block/by-name/'+name
        size = int(shell('blockdev --getsize64 '+path))
        if not 0 < size <= 16*1024*1024:
            raise ValueError('Unexpected calibration partition length: '+name)
        data = shell('dd if='+path+' bs=1048576 2>/dev/null')
        if len(data) != size:
            raise ValueError('Short calibration snapshot: '+name)
        (rmtfs/(name+'.bin')).write_bytes(data)
        snapshots.append({'partition':name,'file':name+'.bin','bytes':size})
    (rmtfs/'snapshot.json').write_text(json.dumps({'device':'nabu','files':snapshots,'publish':False},indent=2))
    subprocess.run([sys.executable,str(ROOT/'tools/prepare_nabu_bluetooth_firmware.py'),
                    '--firmware',str(raw),'--address-hci',str(out/'bluetooth-address-hci.bin'),
                    '--rom-version',str(ROOT/'reference/bluetooth-rom-reference.json'),
                    '--output',str(out/'bluetooth'),'--baud','3200000'],check=True,stdout=subprocess.DEVNULL)
    subprocess.run([sys.executable,str(ROOT/'tools/prepare_nabu_modem_firmware.py'),
                    '--firmware',str(raw),'--output',str(out/'modem')],check=True,stdout=subprocess.DEVNULL)
    (out/'receipt.json').write_text(json.dumps({'status':'local-inputs-prepared',
        'device_serial_sha256':inv['device_serial_sha256'],'device_writes_performed':False,
        'target_hardware_boot_validated':False,'common_touch_and_rom_manually_confirmed':True},indent=2))
    print('Target-owned local inputs prepared. Keep this folder private and reuse its nonce key for this tablet.')

if __name__ == '__main__':
    main()
