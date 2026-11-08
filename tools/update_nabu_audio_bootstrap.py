#!/usr/bin/env python3
"""Restore the selected original Bluetooth audio HAL in the mounted Nabu HAL directory."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from package_nabu_userland import bootstrap_permissions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/hakios-8796/tools/apfs'))
from mkapfs import read_tree, Volume, Container


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--baseline-tree', type=Path, required=True)
    p.add_argument('--bluetooth-hal', type=Path, required=True)
    p.add_argument('--system-service-probe', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    info = plistlib.loads((a.bluetooth_hal / 'Info.plist').read_bytes())
    assert a.bluetooth_hal.name == 'BTAudioHALPlugin.driver'
    assert info['CFBundleIdentifier'] == 'com.apple.audio.BTAudioHALPlugin'
    assert info['CFBundleExecutable'] == 'BTAudioHALPlugin'
    assert (a.bluetooth_hal / info['CFBundleExecutable']).is_file()
    assert 'AudioServerPlugIn_Create' in info['CFPlugInFactories'].values()
    shutil.copytree(a.baseline_tree, a.work)
    a.output.mkdir(parents=True)
    shutil.copytree(a.bluetooth_hal, a.work / 'root/hal/BTAudioHALPlugin.driver')
    shutil.copy2(a.system_service_probe, a.work / 'root/sbin/system-service-probe')
    nodes = read_tree(str(a.work / 'root'))
    bootstrap_permissions(nodes)
    init = a.output / 'NabuInit.apfs'
    volume = Volume(0, 'NabuInit', nodes, False, 1683900000 * 1000000000, None, [])
    container = Container([volume], 256, init.name)
    container.layout()
    container.write(str(init))
    check = subprocess.run(host_command([host_path(ROOT / 'build/apfsprogs/apfsck/apfsck'),
        '-c', '-u', '-w', host_path(init)]), capture_output=True, check=True)
    (a.output / 'NabuInit-apfsck.log').write_bytes(check.stdout + check.stderr)
    for name in ('Boot.apfs', 'App.apfs'):
        shutil.copy2(a.baseline / name, a.output / name)
    combined = a.output / 'bootstrap.apfs'
    with combined.open('wb') as output:
        for name in ('Boot.apfs', 'NabuInit.apfs', 'App.apfs'):
            with (a.output / name).open('rb') as source:
                shutil.copyfileobj(source, output)
    report = json.loads((a.baseline / 'bootstrap-report.json').read_text())
    report.update(bytes=combined.stat().st_size, sha256=hashlib.sha256(combined.read_bytes()).hexdigest(),
        device_execution_validated=False)
    for item in report['containers']:
        if item['name'] == 'NabuInit.apfs':
            item.update(bytes=init.stat().st_size, sha256=hashlib.sha256(init.read_bytes()).hexdigest())
    report['audio_service_update'] = {'baseline': str(a.baseline.resolve()),
        'baseline_tree': str(a.baseline_tree.resolve()), 'original_bluetooth_hal': str(a.bluetooth_hal.resolve()),
        'bundle_identifier': info['CFBundleIdentifier'],
        'changed_root_files': ['hal/BTAudioHALPlugin.driver', 'sbin/system-service-probe'],
        'hal_files': [str(x.relative_to(a.bluetooth_hal)) for x in sorted(a.bluetooth_hal.rglob('*')) if x.is_file()],
        'boot_and_app_containers_unchanged': True, 'runtime_verified': False,
        'interpretation': 'Restores a hidden original output provider; audible playback still needs a live A2DP trial.'}
    report['filesystem_check'] = 'Regenerated NabuInit: apfsck -c -u -w passed; baseline Boot/App copied'
    (a.output / 'bootstrap-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['audio_service_update'], indent=2))


if __name__ == '__main__':
    main()
