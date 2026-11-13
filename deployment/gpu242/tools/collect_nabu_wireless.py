#!/usr/bin/env python3
"""Save read-only Nabu Android wireless hardware evidence, without network secrets."""
import argparse
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess

from inspect_device_memory import read_fdt


def describe(data):
    if not data:
        return True
    if data[0] != 0 and data.endswith(b'\0') and all(x == 0 or 32 <= x < 127 for x in data):
        return data.rstrip(b'\0').decode().split('\0')
    if len(data) % 4 == 0:
        return [hex(x) for x in struct.unpack('>' + 'I' * (len(data) // 4), data)]
    return data.hex()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default=str(Path(__file__).resolve().parents[1]/'host/platform-tools/adb.exe'))
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    commands = {
        'identity': 'uname -a; getprop ro.product.device; getprop ro.soc.model; getprop ro.wlan.chip; getprop ro.bluetooth.library_name',
        'devices': 'ls -l /sys/class/net/wlan0/device /sys/class/tty/ttyHS0/device; ls -l /sys/bus/platform/drivers/icnss /sys/bus/platform/drivers/bt_power /sys/bus/platform/drivers/subsys-pil-tz; cat /sys/class/rfkill/rfkill*/name /sys/class/rfkill/rfkill*/state',
        'subsystems': 'for d in /sys/bus/msm_subsys/devices/*; do echo "$d"; cat "$d/name" "$d/state"; done',
        'firmware-files': 'find /vendor/firmware /vendor/firmware_mnt/image /vendor/bt_firmware/image /vendor/etc/wifi -type f -o -type l',
        'hardware-log': 'dmesg | grep -Ei "icnss|cnss|wcn|wlan|bluetooth|bt_power|qca|glink|smp2p|pil.*(modem|adsp)|ipa.*fw"',
        'modules': 'cat /proc/modules; ls -l /sys/bus/platform/devices/18800000.qcom,icnss; ls -l /sys/class/tty/ttyHS0/device/of_node',
        'regulators': 'for d in /sys/class/regulator/regulator.*; do echo "$d"; cat "$d/name" "$d/state" "$d/microvolts" "$d/num_users"; done',
        'interrupts': 'cat /proc/interrupts',
        'debug-mounts': 'cat /proc/mounts | grep -E "debugfs|tracefs"; ls /d; ls /d/icnss',
    }
    results = {}
    for name, command in commands.items():
        proc = subprocess.run([args.adb, 'shell', 'su', '-c', shlex.quote(command)], capture_output=True, timeout=45)
        (args.output / (name + '.txt')).write_bytes(proc.stdout)
        (args.output / (name + '.stderr')).write_bytes(proc.stderr)
        results[name] = {'command': command, 'exit_code': proc.returncode, 'bytes': len(proc.stdout)}
    proc = subprocess.run([args.adb, 'exec-out', 'su', '-c', 'cat /sys/firmware/fdt'], capture_output=True, check=True, timeout=45)
    (args.output / 'device.dtb').write_bytes(proc.stdout)
    _, nodes, _ = read_fdt(proc.stdout)
    phandles = {int.from_bytes(node['properties']['phandle'], 'big'): path for path, node in nodes.items() if 'phandle' in node['properties']}
    pattern = r'icnss|bt_wcn|smem@|smp2p-modem|glink/modem|qcom,mss@|pil_wlan|qup_uart@0xc8c000|qupv3_se13|qupv3_2_geni|mailbox@18220000|qmp-aop|cmd-db|syscon@17c0000c'
    selected = {path for path in nodes if re.search(pattern, path)}
    # Resolve direct supply, clock, IOMMU, pinctrl and reserved-memory references.
    for path in list(selected):
        for key, data in nodes[path]['properties'].items():
            if key.endswith('-supply') or key in ('clocks', 'iommus', 'memory-region', 'pinctrl-0', 'pinctrl-1', 'interrupt-parent'):
                for offset in range(0, len(data) - 3, 4):
                    ref = phandles.get(int.from_bytes(data[offset:offset + 4], 'big'))
                    if ref:
                        selected.add(ref)
                        selected.update(p for p in nodes if p.startswith(ref + '/'))
    tree = {path: {key: describe(data) for key, data in nodes[path]['properties'].items()} for path in sorted(selected)}
    (args.output / 'device-tree.json').write_text(json.dumps(tree, indent=2) + '\n', encoding='utf-8')
    (args.output / 'collection.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(args.output), 'commands': results, 'tree_nodes': len(tree)}, indent=2))


if __name__ == '__main__':
    main()
