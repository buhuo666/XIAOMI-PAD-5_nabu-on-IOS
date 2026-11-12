"""Bind an already-created, reviewed target layout locally. No device writes."""
import argparse
import json
from pathlib import Path
import shutil
from nabu_storage_layout import receipt_geometry, geometry, default_layout
ROOT = Path(__file__).resolve().parents[1]

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scan', type=Path, required=True)
    p.add_argument('--accept-existing-layout', action='store_true', required=True)
    a = p.parse_args()
    storage=geometry(json.loads(default_layout(ROOT).read_text(encoding='utf-8')))
    plan = json.loads((a.scan/'partition-plan.json').read_text(encoding='utf-8'))
    inv = json.loads((a.scan/'inventory.json').read_text(encoding='utf-8'))
    if receipt_geometry(plan)!=storage:
        raise ValueError('Scan was made with a different capacity; rescan with the selected layout.')
    if plan['status'] != 'existing-layout-candidate':
        raise ValueError('The target does not have the required existing layout. Scan cannot create partitions.')
    if inv['device_serial_sha256'] != plan['device_serial_sha256']:
        raise ValueError('Scan identities differ.')
    if inv['properties']['ro.boot.slot_suffix'] not in ('_a', '_b'):
        raise ValueError('Unrecognized target active slot.')
    region = ROOT/'device/reclaimed-region.json'
    if region.exists():
        raise FileExistsError('Existing target binding retained. Use a separate clean kit for each tablet.')
    dest = ROOT/'device/target'
    if dest.resolve() != a.scan.resolve():
        if dest.exists():
            archive = ROOT/'device/target-before-partition'
            if archive.exists():
                raise FileExistsError('Keep existing target scans; choose a fresh kit.')
            dest.rename(archive)
        shutil.copytree(a.scan, dest)
    if len((dest/'nabu_system-head.bin').read_bytes()) != 4096:
        raise ValueError('Missing target header captured after partitioning.')
    record = {'device':'nabu', 'lun':'sda', 'logical_block_bytes':4096,
              'total_bytes':storage.partition_bytes+4*1024**3,
              'storage_geometry':storage.record(), 'partitions':sorted(plan['existing'], key=lambda x:x['number']),
              'device_serial_sha256':inv['device_serial_sha256'],
              'scope':'User selected this existing target layout for installation; no GPT writes by this tool.'}
    region.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print('Bound existing layout locally. GPT backup: ' + plan['gpt_backup'])

if __name__ == '__main__':
    main()
