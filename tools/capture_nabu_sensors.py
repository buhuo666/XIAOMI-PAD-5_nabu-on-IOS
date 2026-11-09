#!/usr/bin/env python3
"""Record the connected Android sensor inventory and its actual board resources."""
import argparse
import datetime
import json
from pathlib import Path
import re
import shlex
import subprocess


COMMANDS = {
    'identity': 'getprop ro.product.device; getprop ro.build.fingerprint; cat /proc/uptime',
    'sensorservice': 'dumpsys sensorservice',
    'features': 'pm list features',
    'runtime_registry': 'ls -lR /mnt/vendor/persist/sensors/registry; cat /mnt/vendor/persist/sensors/sensors_list.txt; cat /mnt/vendor/persist/sensors/acc_caldata.txt /mnt/vendor/persist/sensors/gyro_caldata.txt',
    'subsystems': 'for p in /sys/bus/msm_subsys/devices/*; do echo "DEVICE $p"; cat "$p/name" "$p/state"; done; ls -l /dev/*slpi* /dev/*sensors*; cat /proc/interrupts',
    'iio': 'for p in /sys/bus/iio/devices/*; do echo "DEVICE $p"; cat "$p/name"; ls "$p"; done',
    'sensor_log': 'logcat -d -t 3000 -b all | grep -iE "sns_|ssc|lsm6|ak099|tcs370|bu270|slpi"',
    'input': 'cat /proc/bus/input/devices',
}


def run_adb(adb, serial, command, timeout=30):
    # adb joins its final arguments into a remote shell command. Quote the
    # entire su program so compound commands all run in the same root shell.
    argv = [adb, '-s', serial, 'exec-out', 'su -c ' + shlex.quote(command)]
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        return 'timeout', e.stdout or b'', e.stderr or b''


def parse_sensorservice(text):
    block = text.split('Sensor List:\n', 1)[1].split('Fusion States:', 1)[0]
    sensors = []
    pattern = (r'^(0x[0-9a-f]+)\) (.*?)\s*\|\s*(.*?)\s*\| ver: (\d+) '
               r'\| type:\s*(.*?)\((\d+)\) \| perm: (.*?) \| flags: (0x[0-9a-f]+)\n\s*([^\n]+)')
    for m in re.finditer(pattern, block, re.M):
        handle, name, vendor, version, string_type, sensor_type, perm, flags, detail = m.groups()
        sensors.append(dict(handle=int(handle, 16), name=name.strip(), vendor=vendor.strip(),
                            version=int(version), string_type=string_type.strip(), type=int(sensor_type),
                            permission=perm, flags=int(flags, 16), detail=detail.strip()))
    if not sensors:
        raise ValueError('No complete Sensor List entries captured')
    return sensors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--adb', default='D:/platform-tools/adb.exe')
    ap.add_argument('--serial', required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    report = dict(schema=1, captured_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  commands={}, sensor_inventory=[], live_sampling_verified=False)

    def capture(name, command, timeout=30):
        code, data, error = run_adb(a.adb, a.serial, command, timeout)
        (a.output / name).write_bytes(data)
        if error:
            (a.output / (name + '.stderr')).write_bytes(error)
        report['commands'][name] = dict(command=command, status=code, bytes=len(data))
        print(f'{name}: status={code}, bytes={len(data)}', flush=True)
        return code, data

    for name, command in COMMANDS.items():
        capture(name + '.txt', command)
    # These archives stay in ignored local logs, including per-device calibration.
    capture('vendor-sensors.tar', 'tar -cf - -C /vendor/etc sensors')
    capture('registry.tar', 'tar -cf - -C /mnt/vendor/persist/sensors registry')
    capture('device-tree.tar', 'tar -cf - -C /sys/firmware/devicetree base')
    capture('test-nusensors_v2', 'cat /vendor/bin/test-nusensors_v2')
    capture('test-usage.txt', 'timeout 3 /vendor/bin/test-nusensors_v2', 8)
    text = (a.output / 'sensorservice.txt').read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n')
    report['sensor_inventory'] = parse_sensorservice(text)
    types = {s['type'] for s in report['sensor_inventory']}
    report['not_exposed_android_types'] = {name: kind for name, kind in
        [('pressure', 6), ('proximity', 8), ('relative_humidity', 12), ('ambient_temperature', 13)] if kind not in types}
    report['limitations'] = [
        'HAL and framework entries include wakeup duplicates, calibrated variants and software fusion.',
        'A registry config or a proto file alone is not evidence of a present sensor.',
        'Absence from Android public Sensor List does not establish physical absence of every vendor component.',
        'Inventory and recent cached events do not replace a bounded live sampling run.',
    ]
    (a.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
