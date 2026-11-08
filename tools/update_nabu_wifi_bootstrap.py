#!/usr/bin/env python3
"""Add the original wifid job to an explicitly selected, qualified bootstrap."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from nabu_service_policy import apply_service_policy
from package_nabu_userland import bootstrap_permissions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/hakios-8796/tools/apfs'))
from mkapfs import read_tree, Volume, Container


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--baseline-tree', type=Path, required=True)
    p.add_argument('--inputs', type=Path, default=ROOT / 'build/nabu-userland-inputs-v1')
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    jobs = json.loads((ROOT / 'userland/nabu/jobs.json').read_text())
    label = 'com.apple.wifid'
    assert label in jobs['source_job_allow'] and label not in jobs['run_at_boot']
    shutil.copytree(a.baseline_tree, a.work)
    a.output.mkdir(parents=True)
    restoration = apply_service_policy(a.inputs, a.work / 'root/LaunchDaemons',
                                       {'source_job_allow': [label]})
    job_path = a.work / 'root/LaunchDaemons' / (label + '.plist')
    original = plistlib.loads((a.inputs / 'rootfs/System/Library/LaunchDaemons' / (label + '.plist')).read_bytes())
    job = plistlib.loads(job_path.read_bytes())
    expected = dict(original, StandardErrorPath='/dev/console')
    assert job == expected
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
    report.update(bytes=combined.stat().st_size, jobs=len(list((a.work / 'root/LaunchDaemons').glob('*.plist'))),
                  device_execution_validated=False)
    # These artifacts have just been generated; existing baseline inputs are not rehashed.
    import hashlib
    report['sha256'] = hashlib.sha256(combined.read_bytes()).hexdigest()
    for item in report['containers']:
        if item['name'] == 'NabuInit.apfs':
            item.update(bytes=init.stat().st_size, sha256=hashlib.sha256(init.read_bytes()).hexdigest())
    report.setdefault('service_restoration', []).extend(restoration)
    report['wifi_service_update'] = {'baseline': str(a.baseline.resolve()),
        'baseline_tree': str(a.baseline_tree.resolve()),
        'changed_root_files': ['LaunchDaemons/com.apple.wifid.plist'],
        'original_conditions_preserved': True, 'device_tree_requirement': job['_LimitLoadToDeviceTree'],
        'mach_services': list(job['MachServices']), 'boot_and_app_containers_unchanged': True,
        'runtime_verified': False}
    report['filesystem_check'] = 'Regenerated NabuInit: apfsck -c -u -w passed; selected baseline Boot/App copied'
    (a.output / 'bootstrap-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['wifi_service_update'], indent=2))


if __name__ == '__main__':
    main()
