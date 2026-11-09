#!/usr/bin/env python3
"""Add the original SLPI root firmware to a qualified local Boot APFS image."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from package_nabu_userland import bootstrap_permissions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/hakios-8796/tools/apfs'))
from mkapfs import read_tree, Volume, Container


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--baseline-tree', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    a = parser.parse_args()
    firmware = json.loads((a.firmware / 'firmware.json').read_text())
    if (firmware['pas_id'], firmware['base'], firmware['reserved_bytes']) != (12, 0x97b00000, 0x1400000):
        raise ValueError('Expected the prepared original nabu SLPI firmware')
    names = [firmware['metadata']] + [s['file'] for s in firmware['segments'] if s['file']]
    a.work.mkdir(parents=True, exist_ok=False)
    a.output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(a.baseline_tree / 'boot', a.work / 'boot')
    for name in names:
        shutil.copyfile(a.firmware / name, a.work / 'boot/fw' / name)

    nodes = read_tree(str(a.work / 'boot'))
    bootstrap_permissions(nodes)
    boot = a.output / 'Boot.apfs'
    volume = Volume(0, 'Boot', nodes, False, 1683900000 * 1000000000, None, [])
    container = Container([volume], 256, boot.name)
    container.layout()
    container.write(str(boot))
    check = subprocess.run(host_command([host_path(ROOT / 'build/apfsprogs/apfsck/apfsck'),
        '-c', '-u', '-w', host_path(boot)]), capture_output=True)
    (a.output / 'Boot-apfsck.log').write_bytes(check.stdout + check.stderr)
    check.check_returncode()
    readbacks = []
    for name in names:
        result = subprocess.run(host_command([host_path(ROOT / 'build/nabu-audio-apfs-reader/apfs-tool'),
            'cat', host_path(boot), '/fw/' + name]), capture_output=True, check=True)
        if result.stdout != (a.firmware / name).read_bytes():
            raise ValueError('Native APFS readback differs: ' + name)
        readbacks.append({'path': '/fw/' + name, 'bytes': len(result.stdout), 'native_readback_equal': True})
    (a.output / 'firmware-native-readback.json').write_text(json.dumps(readbacks, indent=2) + '\n')

    for name in ('NabuInit.apfs', 'App.apfs'):
        shutil.copyfile(a.baseline / name, a.output / name)
    combined = a.output / 'bootstrap.apfs'
    with combined.open('wb') as destination:
        for name in ('Boot.apfs', 'NabuInit.apfs', 'App.apfs'):
            with (a.output / name).open('rb') as source:
                shutil.copyfileobj(source, destination)
    if combined.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Bootstrap exceeds the reserved image budget')
    report = json.loads((a.baseline / 'bootstrap-report.json').read_text())
    report.update(bytes=combined.stat().st_size,
                  sha256=hashlib.sha256(combined.read_bytes()).hexdigest(),
                  device_execution_validated=False, deployed=False)
    for item in report['containers']:
        if item['name'] == 'Boot.apfs':
            item.update(bytes=boot.stat().st_size, sha256=hashlib.sha256(boot.read_bytes()).hexdigest())
    report['slpi_firmware'] = {
        'source': str(a.firmware.resolve()), 'baseline': str(a.baseline.resolve()),
        'baseline_tree': str(a.baseline_tree.resolve()), 'path': 'Boot APFS /fw',
        'pas_id': firmware['pas_id'], 'base': firmware['base'],
        'reserved_bytes': firmware['reserved_bytes'], 'files': readbacks,
        'filesystem_check': 'apfsck -c -u -w passed', 'native_readback_equal': True,
        'runtime_verified': False, 'sensor_pd_started': False,
        'scope': 'Original SLPI root firmware only; no sensor daemon or native sensor service added.'}
    report['filesystem_check'] = 'Regenerated Boot: apfsck and native firmware readback passed; NabuInit and App copied from baseline'
    (a.output / 'bootstrap-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'bootstrap': str(combined.resolve()), 'bytes': combined.stat().st_size,
                      'slpi_files': len(names), 'apfsck': 'passed', 'native_readback_equal': True,
                      'device_execution_validated': False}, indent=2))


if __name__ == '__main__':
    main()
