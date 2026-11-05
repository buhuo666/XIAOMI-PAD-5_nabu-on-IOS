#!/usr/bin/env python3
"""Capture Android's hardware/service view for comparison with the iPadOS scan."""
import argparse
import datetime
import json
from pathlib import Path
import re
import subprocess


COMMANDS = {
    'identity': 'for k in ro.product.device ro.product.model ro.product.manufacturer ro.board.platform ro.soc.model ro.soc.manufacturer ro.build.version.release ro.build.version.sdk ro.build.fingerprint; do echo "$k=$(getprop $k)"; done',
    'features': 'pm list features',
    'memory': 'cat /proc/meminfo',
    'cpu': 'cat /proc/cpuinfo; for p in possible present online; do echo "$p=$(cat /sys/devices/system/cpu/$p)"; done',
    'display': 'wm size; wm density; dumpsys display',
    'backlight': 'for p in /sys/class/backlight/*; do echo "DEVICE $p"; for k in brightness actual_brightness max_brightness bl_power; do if test -f "$p/$k"; then echo "$k=$(cat "$p/$k")"; fi; done; readlink -f "$p/device/driver"; done',
    'brightness_settings': 'settings get system screen_brightness; settings get system screen_brightness_mode; settings get system screen_auto_brightness_adj',
    'sensors': 'dumpsys sensorservice',
    'input': 'cat /proc/bus/input/devices; getevent -lp',
    'power': 'for p in /sys/class/power_supply/*; do echo "DEVICE $p"; cat "$p/uevent"; done',
    'rtc': 'cat /sys/class/rtc/rtc0/name /sys/class/rtc/rtc0/since_epoch; date +%s',
    'storage': 'df -k /data; cat /proc/partitions',
    'i2c': 'for p in /sys/bus/i2c/devices/*; do if test -f "$p/name"; then echo "DEVICE $p $(cat "$p/name")"; readlink -f "$p/driver"; fi; done',
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--adb', default='D:/platform-tools/adb.exe')
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 1, 'os': 'Android', 'captured_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'scope': 'Read-only hardware inventory and Android service declarations; not MobileGestalt answers',
              'commands': {}, 'summary': {}}
    for name, command in COMMANDS.items():
        started = datetime.datetime.now(datetime.timezone.utc)
        try:
            result = subprocess.run([a.adb, 'exec-out', 'su', '-c', command], capture_output=True, timeout=30)
            output, error, code = result.stdout, result.stderr, result.returncode
        except subprocess.TimeoutExpired as e:
            output, error, code = e.stdout or b'', e.stderr or b'', 'timeout'
        (a.output/(name+'.txt')).write_bytes(output)
        if error:
            (a.output/(name+'.stderr.txt')).write_bytes(error)
        report['commands'][name] = {'command': command, 'status': code, 'bytes': len(output),
                                   'elapsed_seconds': (datetime.datetime.now(datetime.timezone.utc)-started).total_seconds()}
        print(f'{name}: status={code}, bytes={len(output)}', flush=True)
    def read(name):
        return (a.output/(name+'.txt')).read_text(encoding='utf-8', errors='replace')
    summary = report['summary']
    summary['identity'] = dict(line.split('=', 1) for line in read('identity').splitlines() if '=' in line)
    summary['features'] = sorted(line.removeprefix('feature:') for line in read('features').splitlines() if line.startswith('feature:'))
    summary['mem_total_kib'] = int(re.search(r'^MemTotal:\s+(\d+)', read('memory'), re.M)[1])
    summary['cpu_online'] = re.search(r'^online=(.*)', read('cpu'), re.M)[1]
    summary['display_shell'] = [s for s in read('display').splitlines() if s.startswith(('Physical size:', 'Physical density:', 'Override size:', 'Override density:'))]
    summary['backlight'] = read('backlight').splitlines()
    summary['brightness_setting_lines'] = read('brightness_settings').splitlines()
    summary['sensor_inventory_lines'] = [s.strip() for s in read('sensors').splitlines() if re.search(r'(?i)light|proximity|accelerometer|gyroscope|magnetometer', s)][:45]
    report['limitations'] = ['Features are Android declarations, not hardware self-tests.',
                              'Brightness setting is a stored preference; backlight reads are an instantaneous sample.',
                              'MemTotal is Linux-managed RAM, not physical installed capacity.',
                              'Raw identifiers and service output remain in the ignored local log directory.']
    (a.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print('Saved', a.output/'report.json')


if __name__ == '__main__':
    main()
