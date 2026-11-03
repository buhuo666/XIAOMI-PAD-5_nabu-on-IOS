#!/usr/bin/env python3
"""Read an explicitly selected nabu's inventory over ADB; never write device storage."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {
    'identity': 'id',
    'kernel': 'uname -a',
    'cpuinfo': 'cat /proc/cpuinfo',
    'meminfo': 'cat /proc/meminfo',
    'iomem': 'cat /proc/iomem',
    'partitions': 'cat /proc/partitions',
    'mounts': 'cat /proc/mounts',
    'cmdline': 'cat /proc/cmdline',
    'bootconfig': 'cat /proc/bootconfig',
    'block_links': 'ls -l /dev/block/by-name /dev/block/bootdevice/by-name',
    'block_geometry': 'for p in /sys/class/block/sd*; do [ -e "$p" ] || continue; echo "BLOCK $p"; for f in size start partition queue/logical_block_size queue/physical_block_size device/vendor device/model; do [ ! -f "$p/$f" ] || { printf "%s=" "$f"; cat "$p/$f"; }; done; done',
    'device_tree_paths': 'find /sys/firmware/devicetree/base -maxdepth 3 -type d',
    'tools': 'for t in blockdev sgdisk fdisk dd sha256sum readlink; do command -v "$t"; done',
    'thermal': 'for p in /sys/class/thermal/thermal_zone*; do [ -d "$p" ] || continue; echo "ZONE $p"; cat "$p/type" "$p/temp"; done',
}
PROPERTIES = ['ro.product.device', 'ro.product.model', 'ro.product.manufacturer',
              'ro.build.display.id', 'ro.build.version.release', 'ro.build.version.security_patch',
              'ro.boot.bootloader', 'ro.boot.slot_suffix', 'ro.boot.verifiedbootstate',
              'ro.boot.flash.locked', 'ro.boot.vbmeta.device_state', 'ro.board.platform',
              'ro.hardware', 'ro.soc.model', 'ro.boot.bootdevice']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    def call(tail):
        return subprocess.run([args.adb] + (['-s', args.serial] if args.serial else []) + tail,
                              capture_output=True, timeout=25)
    if not args.serial:
        devices = subprocess.run([args.adb, 'devices'], capture_output=True, timeout=20)
        rows = [line.split() for line in devices.stdout.decode().splitlines()[1:] if line.strip()]
        ready = [row[0] for row in rows if len(row) >= 2 and row[1] == 'device']
        if len(ready) != 1:
            parser.error('Exactly one authorized ADB device is required, or use --serial')
        args.serial = ready[0]
    product = call(['shell', 'getprop', 'ro.product.device']).stdout.decode().strip()
    if product != 'nabu':
        parser.error('Selected device is not nabu; stopping before root commands')
    root_check = call(['shell', 'su', '-c', 'id'])
    if root_check.returncode or b'uid=0' not in root_check.stdout:
        parser.error('Root shell is unavailable')
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
    output = args.output or ROOT / 'device' / ('inventory-' + stamp)
    output.mkdir(parents=True, exist_ok=False)
    record = {'date_timezone': 'Asia/Shanghai', 'timestamp': stamp, 'product': product,
              'device_serial_sha256': hashlib.sha256(args.serial.encode()).hexdigest(),
              'root': True, 'device_writes_performed': False, 'properties': {}, 'captures': {}}
    for prop in PROPERTIES:
        result = call(['shell', 'getprop', prop])
        record['properties'][prop] = result.stdout.decode('utf-8', errors='replace').strip()
    for name, command in COMMANDS.items():
        try:
            result = call(['exec-out', 'su', '-c', command])
            path = output / (name + '.txt')
            path.write_bytes(result.stdout)
            if result.stderr:
                (output / (name + '.stderr.txt')).write_bytes(result.stderr)
            record['captures'][name] = {'command': command, 'exit': result.returncode,
                                      'bytes': len(result.stdout), 'sha256': hashlib.sha256(result.stdout).hexdigest()}
        except subprocess.TimeoutExpired:
            record['captures'][name] = {'command': command, 'error': 'timeout'}
    (output / 'inventory.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'product': product, 'root': True,
                      'captures': len(record['captures']), 'failed': [k for k,v in record['captures'].items() if v.get('exit') != 0]}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
