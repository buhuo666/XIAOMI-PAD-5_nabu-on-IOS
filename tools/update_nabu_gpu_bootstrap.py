#!/usr/bin/env python3
"""Assemble an APFS system GPU candidate from the qualified display/GPU bootstrap."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from package_nabu_userland import bootstrap_permissions

ROOT = Path(__file__).resolve().parents[1]
GATE = '/redwood/sbin/nabu-metal-wait-exec'
GRAPHICS_JOBS = ('com.apple.backboardd', 'com.apple.SpringBoard')


def gate_job(job):
    updated = copy.deepcopy(job)
    arguments = list(job['ProgramArguments'])
    program = job.get('Program', arguments[0])
    updated['Program'] = GATE
    updated['ProgramArguments'] = [GATE, '--exec', program, *arguments[1:]]
    return updated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True, help='Qualified bootstrap artifacts directory')
    parser.add_argument('--baseline-tree', type=Path, required=True, help='Corresponding build directory containing root/')
    parser.add_argument('--runtime', type=Path, required=True, help='Downloaded system GPU build directory')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    baseline, source = args.baseline.resolve(), args.runtime.resolve()
    work, output = args.work.resolve(), args.output.resolve()
    if work.exists() or output.exists():
        parser.error('Use new candidate directories')
    build = json.loads((source / 'build-report.json').read_text())
    if build['result'] != 'signed_not_run' or not build['system_clients_enabled']:
        parser.error('Expected the signed system GPU build')
    shutil.copytree(args.baseline_tree.resolve(), work)
    output.mkdir(parents=True)
    root = work / 'root'
    changed = []
    for key in ('frontend', 'turnip', 'mount_helper', 'gate'):
        name = build[key]['file']
        shutil.copyfile(source / name, root / 'sbin' / name)
        changed.append('sbin/' + name)
    bundle = 'NativeAdrenoMetal.bundle'
    # This is the new candidate tree, and copytree replaces only bundle payloads.
    shutil.copytree(source / bundle, root / 'metal-addons' / bundle, dirs_exist_ok=True)
    changed.extend(str(p.relative_to(root)).replace('\\', '/') for p in (root / 'metal-addons' / bundle).rglob('*') if p.is_file())
    transitions = []
    for label in GRAPHICS_JOBS:
        relative = 'LaunchDaemons/' + label + '.plist'
        path = root / relative
        original = plistlib.loads(path.read_bytes())
        updated = gate_job(original)
        path.write_bytes(plistlib.dumps(updated, fmt=plistlib.FMT_BINARY))
        transitions.append(dict(label=label, before=original, after=updated))
        changed.append(relative)
    # The existing mount-only daemon already carries its qualified root entitlement.
    mount = root / 'LaunchDaemons/org.nabu.metal-plugin-mount.plist'
    assert mount.is_file()
    sys.path.insert(0, str(ROOT / 'src/hakios-8796/tools/apfs'))
    from mkapfs import read_tree, Volume, Container
    nodes = read_tree(str(root))
    bootstrap_permissions(nodes)
    nodes.children['metal-addons'].children[bundle].children['NativeAdrenoMetal'].mode = stat.S_IFREG | 0o755
    init = output / 'NabuInit.apfs'
    volume = Volume(0, 'NabuInit', nodes, False, 1683900000 * 1000000000, None, [])
    container = Container([volume], 256, init.name)
    container.layout()
    container.write(str(init))
    checked = subprocess.run(host_command([host_path(ROOT / 'build/apfsprogs/apfsck/apfsck'), '-c', '-u', '-w', host_path(init)]), capture_output=True)
    (output / 'NabuInit-apfsck.log').write_bytes(checked.stdout + checked.stderr)
    checked.check_returncode()
    for name in ('Boot.apfs', 'App.apfs'):
        shutil.copyfile(baseline / name, output / name)
    combined = output / 'bootstrap.apfs'
    with combined.open('wb') as destination:
        for name in ('Boot.apfs', 'NabuInit.apfs', 'App.apfs'):
            with (output / name).open('rb') as stream:
                shutil.copyfileobj(stream, destination)
    assert combined.stat().st_size <= 256 * 1024 * 1024
    readbacks = []
    for relative in changed:
        result = subprocess.run(host_command([host_path(ROOT / 'build/nabu-audio-apfs-reader/apfs-tool'), 'cat', host_path(init), '/' + relative]), capture_output=True, check=True)
        assert result.stdout == (root / relative).read_bytes(), relative
        readbacks.append(dict(path=relative, bytes=len(result.stdout), native_readback_equal=True))
    report = json.loads((baseline / 'bootstrap-report.json').read_text())
    report.update(bytes=combined.stat().st_size, sha256=hashlib.sha256(combined.read_bytes()).hexdigest(), device_execution_validated=False)
    for item in report['containers']:
        if item['name'] == 'NabuInit.apfs':
            item.update(bytes=init.stat().st_size, sha256=hashlib.sha256(init.read_bytes()).hexdigest())
    report['system_gpu'] = dict(build=build, graphics_jobs=transitions, native_readbacks=readbacks,
        required_boot_argument='nabu-gpu-delay=0', original_graphics_executables_preserved=True,
        system_runtime_verified=False, kernel_rebuilt=False, apfsck_passed=True)
    (output / 'bootstrap-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result='assembled_not_run', bytes=report['bytes'], gated_jobs=list(GRAPHICS_JOBS), readbacks=len(readbacks))))


if __name__ == '__main__':
    main()
