"""Read the other tablet over ADB and save a capacity/partition plan on this PC.

No device writes, reboot, formatting, partition changes or fastboot operations.
Run only on the destination PC with the destination nabu connected.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid
from nabu_storage_layout import geometry, default_layout, LEGACY

ROOT = Path(__file__).resolve().parents[1]
GIB = 1024 ** 3


def make_plan(gpt, storage=LEGACY):
    units = [u for u in gpt['luns'] if any(p['name'] == 'userdata' for p in u['partitions'])]
    if len(units) != 1:
        return {'status': 'needs-review', 'reason': 'Cannot identify one userdata LUN.'}
    unit = units[0]
    userdata = next(p for p in unit['partitions'] if p['name'] == 'userdata')
    plan = {'status': 'needs-review', 'lun': unit['name'], 'lun_bytes': unit['bytes'],
            'logical_block_bytes': unit['logical_block_bytes'], 'userdata_before': userdata,
            'device_writes_performed': False}
    existing = [p for p in unit['partitions'] if p['name'] in ('nabu_esp', 'nabu_system')]
    if existing:
        good = (unit['name'] == 'sda' and unit['logical_block_bytes'] == 4096 and
                len(existing) == 2 and
                any(p['number'] == 35 and p['name'] == 'nabu_esp' and p['bytes'] == 4*GIB for p in existing) and
                any(p['number'] == 36 and p['name'] == 'nabu_system' and p['bytes'] == storage.partition_bytes for p in existing))
        plan.update(status='existing-layout-candidate' if good else 'existing-layout-needs-port', existing=existing)
        return plan
    if unit['name'] != 'sda' or unit['logical_block_bytes'] != 4096:
        plan['reason'] = 'Current installer requires sda and 4096-byte sectors.'
        return plan
    if any(p['number'] in (35, 36) or p['last_lba'] > userdata['last_lba'] for p in unit['partitions'] if p is not userdata):
        plan['reason'] = 'Partitions occupy the required slots or follow userdata; do not apply a generic layout.'
        return plan
    block = unit['logical_block_bytes']
    align = 1024*1024 // block
    end = ((userdata['last_lba'] + 1) // align) * align
    esp_start = end - (storage.partition_bytes+4*GIB)//block
    system_start = esp_start + 4*GIB//block
    remaining = (esp_start-userdata['first_lba'])*block
    if remaining < 16*GIB:
        plan['reason'] = 'The proposed layout leaves less than 16 GiB for Android userdata.'
        return plan
    plan.update(status='offline-repartition-required',
                android_userdata_bytes_after=remaining,
                userdata_last_lba_proposed=esp_start-1,
                android_data_preserved=False,
                reason='Proposal only. No validated offline shrink/reformat executor is included. Do not change GPT while Android /data is mounted.',
                partitions_proposed=[
                    {'number':35, 'name':'nabu_esp', 'type_guid':'c12a7328-f81f-11d2-ba4b-00a0c93ec93b',
                     'unique_guid':str(uuid.uuid4()), 'first_lba':esp_start, 'last_lba':system_start-1,
                     'bytes':4*GIB, 'attributes':0},
                    {'number':36, 'name':'nabu_system', 'type_guid':'0fc63daf-8483-4772-8e79-3d69d8477de4',
                     'unique_guid':str(uuid.uuid4()), 'first_lba':system_start, 'last_lba':end-1,
                     'bytes':storage.partition_bytes, 'attributes':0}])
    return plan


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, default=ROOT/'device/target')
    ap.add_argument('--adb', type=Path, default=ROOT/'host/platform-tools/adb.exe')
    ap.add_argument('--layout',type=Path,default=default_layout(ROOT))
    a = ap.parse_args()
    if a.output.exists():
        ap.error('Keep prior scans. Choose a new --output directory.')
    adb = str(a.adb.resolve())
    rows = subprocess.check_output([adb, 'devices'], text=True).splitlines()[1:]
    ready = [x.split()[0] for x in rows if x.strip().endswith('\tdevice')]
    if len(ready) != 1:
        ap.error('Connect exactly one authorized destination tablet.')
    serial = ready[0]
    def shell(command):
        return subprocess.check_output([adb, '-s', serial, 'exec-out', 'su', '-c', command], timeout=60)
    if shell('getprop ro.product.device').strip() != b'nabu' or b'uid=0' not in shell('id'):
        ap.error('This package requires nabu and an authorized root shell.')
    subprocess.run([sys.executable, str(ROOT/'tools/collect_device.py'), '--adb', adb,
                    '--serial', serial, '--output', str(a.output)], check=True)
    import backup_gpt
    old = set((ROOT/'backup/gpt').iterdir())
    backup_gpt.ADB = adb
    backup_gpt.main()
    created = set((ROOT/'backup/gpt').iterdir()) - old
    if len(created) != 1:
        raise RuntimeError('Could not identify this scan GPT backup.')
    backup = created.pop()
    gpt = json.loads((backup/'gpt-report.json').read_text(encoding='utf-8'))
    cfg=json.loads(a.layout.read_text(encoding='utf-8'))
    storage=geometry(cfg)
    plan = make_plan(gpt,storage)
    plan['storage_geometry']=storage.record()
    plan.update(device_serial_sha256=hashlib.sha256(serial.encode()).hexdigest(),
                gpt_backup=str(backup.relative_to(ROOT)),
                inventory=str(a.output.resolve()),
                created=datetime.datetime.now(datetime.timezone.utc).isoformat())
    (a.output/'partition-plan.json').write_text(json.dumps(plan, indent=2), encoding='utf-8')
    # This is a read of the source header, not a copy of an old tablet's receipt.
    if plan['status'] == 'existing-layout-candidate':
        header = shell('dd if=/dev/block/by-name/nabu_system bs=4096 count=1 2>/dev/null')
        if len(header) != 4096:
            raise RuntimeError('Short system header read.')
        (a.output/'nabu_system-head.bin').write_bytes(header)
    subprocess.run([sys.executable, str(ROOT/'tools/capture_nabu_power.py'), '--adb', adb,
                    '--output', str(a.output/'android-power.json')], check=True, stdout=subprocess.DEVNULL)
    (a.output/'hardware-summary.txt').write_bytes(shell(
        'cat /proc/meminfo; df -k /data; getprop ro.build.display.id; '
        'getprop ro.boot.slot_suffix; getprop ro.boot.flash.locked; '
        'dmesg | grep -iE "nt36523|novatek|touchpanel|panel.*csot|panel.*boe"'))
    print(json.dumps({'saved':str(a.output.resolve()), 'gpt_backup':str(backup),
                      'storage_lun_gib':round(plan.get('lun_bytes',0)/GIB,2),
                      'partition_status':plan['status'], 'device_writes_performed':False}, indent=2))


if __name__ == '__main__':
    main()
