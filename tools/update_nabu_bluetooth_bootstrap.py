#!/usr/bin/env python3
"""Rebuild the existing RAM bootstrap with the Bluetooth jobs and diagnostic."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from package_nabu_userland import bootstrap_permissions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/hakios-8796/tools/apfs'))
from mkapfs import read_tree, Volume, Container


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', type=Path, required=True)
    parser.add_argument('--ci-run', type=int, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--lifecycle', type=Path, help='Source-owned QCA implementation of the BlueTool lifecycle service')
    parser.add_argument('--lifecycle-ci-run', type=int)
    parser.add_argument('--compatibility', type=Path, help='20F66 bluetoothd optional-HCI initializer adapter')
    parser.add_argument('--diagnose-le-family', action='store_true', help='One first-boot Reset/legacy/Reset/query/legacy/Reset controller diagnostic; never enables scanning')
    args = parser.parse_args()
    jobs = json.loads((ROOT / 'userland/nabu/jobs.json').read_text())
    baseline = ROOT / 'artifacts/nabu-bootstrap-v77'
    shutil.copytree(ROOT / 'build/nabu-bootstrap-v77', args.work)
    args.output.mkdir()
    shutil.copy2(args.probe, args.work / 'root/sbin/system-service-probe')
    source = ROOT / 'build/nabu-userland-inputs-v1/rootfs/System/Library/LaunchDaemons'
    destination = args.work / 'root/LaunchDaemons'
    changed = ['sbin/system-service-probe']
    policies = {}
    for filename in ('com.apple.bluetoothd', 'com.apple.bluetoothuserd', 'com.apple.bluetoothuiservice'):
        job = plistlib.loads((source / (filename + '.plist')).read_bytes())
        job['StandardErrorPath'] = '/dev/console'
        if filename == 'com.apple.bluetoothd':
            job.setdefault('EnvironmentVariables', {}).update(jobs['environment_overrides'][filename])
        if filename == 'com.apple.bluetoothuserd':
            for field in ('RunAtLoad', 'KeepAlive', 'StartInterval', 'StartCalendarInterval',
                          'WatchPaths', 'QueueDirectories', 'StartOnMount', 'LaunchEvents'):
                job.pop(field, None)
            job.setdefault('EnvironmentVariables', {})['OS_ACTIVITY_DT_MODE'] = 'YES'
        (destination / (filename + '.plist')).write_bytes(plistlib.dumps(job, fmt=plistlib.FMT_BINARY))
        changed.append('LaunchDaemons/' + filename + '.plist')
        policies[filename] = job
    if args.compatibility:
        shutil.copy2(args.compatibility, args.work / 'root/lib/libnabu.bluetooth.compat.dylib')
        config = args.work / 'root/etc/inject.conf'
        injection = config.read_text() + '/redwood/lib/libnabu.bluetooth.compat.dylib bluetoothd\n'
        if len(injection.encode()) >= 512:
            raise ValueError('Bluetooth injection exceeds the existing kern.exec_inject 512-byte buffer')
        config.write_text(injection)
        changed.extend(['lib/libnabu.bluetooth.compat.dylib', 'etc/inject.conf'])
    if args.lifecycle:
        shutil.copy2(args.lifecycle, args.work / 'root/sbin/nabu-bluetooth-lifecycle')
        filename = 'com.apple.BlueTool'
        job = plistlib.loads((destination / (filename + '.plist')).read_bytes())
        job['ProgramArguments'] = ['/redwood/sbin/nabu-bluetooth-lifecycle']
        if args.diagnose_le_family: job['ProgramArguments'].append('--diagnose-le-family')
        (destination / (filename + '.plist')).write_bytes(plistlib.dumps(job, fmt=plistlib.FMT_BINARY))
        changed.extend(['sbin/nabu-bluetooth-lifecycle', 'LaunchDaemons/' + filename + '.plist'])
        policies[filename] = job
    nodes = read_tree(str(args.work / 'root'))
    bootstrap_permissions(nodes)
    image = args.output / 'NabuInit.apfs'
    volume = Volume(0, 'NabuInit', nodes, False, 1683900000 * 1000000000, None, [])
    container = Container([volume], 256, image.name)
    container.layout()
    container.write(str(image))
    check = subprocess.run([str(ROOT / 'build/apfsprogs/apfsck/apfsck'), '-c', '-u', '-w', str(image)],
                           capture_output=True, check=True)
    (args.output / 'NabuInit-apfsck.log').write_bytes(check.stdout + check.stderr)
    for name in ('Boot.apfs', 'App.apfs'):
        shutil.copy2(baseline / name, args.output / name)
    combined = args.output / 'bootstrap.apfs'
    with combined.open('wb') as output:
        for name in ('Boot.apfs', 'NabuInit.apfs', 'App.apfs'):
            with (args.output / name).open('rb') as source_file:
                shutil.copyfileobj(source_file, output)
    report = json.loads((baseline / 'bootstrap-report.json').read_text())
    report.update(bytes=combined.stat().st_size, sha256=hashlib.sha256(combined.read_bytes()).hexdigest(),
                  jobs=len(list(destination.glob('*.plist'))), device_execution_validated=False)
    for item in report['containers']:
        if item['name'] == 'NabuInit.apfs':
            item.update(bytes=image.stat().st_size, sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    report['jobs_policy_sha256'] = hashlib.sha256((ROOT / 'userland/nabu/jobs.json').read_bytes()).hexdigest()
    report['environment_overrides'] = jobs['environment_overrides']
    report['on_demand_allow'] = jobs['on_demand_allow']
    report['bluetooth_service_update'] = {'ci_run': args.ci_run, 'probe': str(args.probe),
        'baseline': str(baseline), 'changed_root_files': changed, 'jobs': policies,
        'boot_and_app_containers_unchanged': True, 'runtime_verified': False}
    report['system_service_probe_update'] = {'ci_run': args.ci_run, 'source': str(args.probe),
        'baseline': str(baseline), 'actions_added': ['BluetoothInventory', 'BluetoothUseSingleAdvertising', 'BluetoothTransportTrial', 'BluetoothSocketTrial'],
        'wireless_smem611_snapshots': True}
    if args.lifecycle:
        report['bluetooth_lifecycle'] = {
            'ci_run': args.lifecycle_ci_run, 'source': str(args.lifecycle),
            'service': 'com.apple.BlueTool', 'user': policies['com.apple.BlueTool']['UserName'],
            'boot_init': 'Real HCI Reset (boot), QCA LocalVersion and requested BD_ADDR verification',
            'deepsleep': 'Real HCI Reset then confirmed IBS transport idle; shared supplies retained',
            'donor_firmware_scripts_used': False, 'runtime_verified': False}
        report['bluetooth_lifecycle']['le_family_diagnostic'] = args.diagnose_le_family
    if args.compatibility:
        report['bluetooth_optional_reporting'] = {
            'ci_run': args.lifecycle_ci_run, 'source': str(args.compatibility),
            'process': 'bluetoothd', 'injection': '/redwood/lib/libnabu.bluetooth.compat.dylib',
            'scope': 'Advance optional initializer only when real supportedCommands[18] lacks 0x08',
            'controller_support_or_hci_replies_modified': False, 'runtime_verified': False}
    report['service_restoration'].append({'label': 'com.apple.bluetoothuiservice',
        'operation': 'include-original-job', 'original_conditions_preserved': True})
    report['filesystem_check'] = 'Regenerated NabuInit: apfsck -c -u -w passed; Boot/App copied from qualified v77'
    (args.output / 'bootstrap-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'bytes': report['bytes'], 'jobs': report['jobs'], 'changed_root_files': changed,
                      'apfsck': 'passed'}, indent=2))


if __name__ == '__main__':
    main()
