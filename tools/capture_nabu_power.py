#!/usr/bin/env python3
"""Read Android's power telemetry and calibrate the Pad 5's free-running RTC."""
import argparse
import collections
import datetime
import json
from pathlib import Path
import shlex
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--adb', default='D:/platform-tools/adb.exe')
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()

    def shell(command):
        return subprocess.check_output([args.adb, 'shell', 'su', '-c', shlex.quote(command)],
                                       text=True, encoding='utf-8').strip()

    assert shell('getprop ro.product.device') == 'nabu'
    samples = []
    for _ in range(5):
        first, epoch, last = map(int, shell(
            'cat /sys/class/rtc/rtc0/since_epoch; date +%s; cat /sys/class/rtc/rtc0/since_epoch').split())
        samples.append({'rtc_before': first, 'android_utc': epoch, 'rtc_after': last})
    offsets = [s['android_utc'] - s['rtc_before'] for s in samples if s['rtc_before'] == s['rtc_after']]
    if not offsets:
        raise RuntimeError('RTC advanced during every sample; run capture again')
    offset = collections.Counter(offsets).most_common(1)[0][0]
    properties = {'STATUS', 'PRESENT', 'CAPACITY', 'REAL_CAPACITY', 'VOLTAGE_NOW', 'CURRENT_NOW',
                  'TEMP', 'CHARGE_FULL', 'CHARGE_FULL_DESIGN', 'CHARGE_COUNTER', 'CYCLE_COUNT',
                  'BATTERY_TYPE', 'ONLINE', 'TYPE', 'CURRENT_MAX', 'VOLTAGE_MAX'}
    supplies = {}
    for name in ('battery', 'bms', 'usb'):
        fields = dict(line.split('=', 1) for line in shell(f'cat /sys/class/power_supply/{name}/uevent').splitlines())
        supplies[name] = {key.removeprefix('POWER_SUPPLY_'): value for key, value in fields.items()
                          if key.removeprefix('POWER_SUPPLY_') in properties}
    report = {'device': 'nabu', 'captured_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'rtc_name': shell('cat /sys/class/rtc/rtc0/name'), 'rtc_offset_seconds': offset,
              'calibration_resolution_seconds': 1, 'samples': samples, 'power_supplies': supplies,
              'bms_driver': shell('readlink -f /sys/class/power_supply/bms/device/driver')}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
