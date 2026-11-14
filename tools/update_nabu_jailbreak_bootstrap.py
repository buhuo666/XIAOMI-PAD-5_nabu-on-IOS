#!/usr/bin/env python3
"""Add persistent jailbreak path restoration to the qualified bootstrap."""
import argparse
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['baseline', 'baseline-tree', 'setup', 'metal', 'keyboard', 'work', 'output']:
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    build = json.loads((args.setup / 'build-report.json').read_text())
    assert build['result'] == 'signed-not-run'
    assert (args.setup / 'download-review.json').is_file()
    assert (args.metal / 'download-review.json').is_file()
    assert (args.keyboard / 'download-review.json').is_file()
    keyboard_build = json.loads((args.keyboard / 'build-report.json').read_text())
    assert keyboard_build['result'] == 'signed-not-run'
    metal_build = json.loads((args.metal / 'build-report.json').read_text())
    assert metal_build['result'] == 'signed_not_run'
    assert not args.work.exists() and not args.output.exists()
    shutil.copytree(args.baseline_tree, args.work)
    args.output.mkdir(parents=True)
    root = args.work / 'root'
    changed = ['sbin/nabu-jailbreak-boot', 'etc/rc', 'sbin/libnabu-metal-frontend.dylib',
               'sbin/nabu-jailbreak-boot-probe', 'LaunchDaemons/org.nabu.jailbreak-boot-probe.plist',
               'lib/libnabu.keyboard.dylib', 'etc/inject.conf']
    shutil.copyfile(args.setup / 'nabu-jailbreak-boot', root / changed[0])
    script = (root / 'etc/rc').read_text()
    anchor = 'exec /sbin/launchd.darwin'
    assert script.count(anchor) == 1 and 'nabu-jailbreak-boot' not in script
    (root / 'etc/rc').write_bytes(script.replace(anchor,
        '/redwood/sbin/nabu-jailbreak-boot --restore\n' + anchor).encode())
    assert (root / changed[2]).is_file()
    shutil.copyfile(args.metal / 'libnabu-metal-frontend.dylib', root / changed[2])
    shutil.copyfile(args.setup / 'nabu-jailbreak-boot-probe', root / changed[3])
    (root / changed[4]).write_bytes(plistlib.dumps(dict(
        Label='org.nabu.jailbreak-boot-probe',
        ProgramArguments=['/redwood/sbin/nabu-jailbreak-boot-probe'],
        UserName='mobile', RunAtLoad=True,
        StandardOutPath='/dev/console', StandardErrorPath='/dev/console'), fmt=plistlib.FMT_BINARY))
    shutil.copyfile(args.keyboard / 'libnabu.keyboard.dylib', root / changed[5])
    lines = (root / changed[6]).read_text().splitlines()
    for index, line in enumerate(lines):
        if line.startswith('/redwood/lib/libnabu.experience.dylib '):
            words = line.split()
            words.extend(name for name in ['Sileo', 'TrollStoreLite', 'TrollApps'] if name not in words)
            lines[index] = ' '.join(words)
    keyboard_rule = '/redwood/lib/libnabu.keyboard.dylib *'
    assert not any(keyboard_rule.split()[0] in line for line in lines)
    lines.append(keyboard_rule)
    # init converts LF-delimited lines to semicolon-delimited kernel rules.
    # CR bytes become part of process names in the actual exec parser.
    configuration = ('\n'.join(lines) + '\n').encode()
    assert b'\r' not in configuration and len(configuration) < 4096
    (root / changed[6]).write_bytes(configuration)
    baseline_files = {p.relative_to(args.baseline_tree / 'root').as_posix(): p
                      for p in (args.baseline_tree / 'root').rglob('*') if p.is_file()}
    actual_changes = sorted(p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
                            and (p.relative_to(root).as_posix() not in baseline_files or
                                 p.read_bytes() != baseline_files[p.relative_to(root).as_posix()].read_bytes()))
    assert actual_changes == sorted(changed), actual_changes
    sys.path.insert(0, str(ROOT / 'src/hakios-8796/tools/apfs'))
    from mkapfs import read_tree, Volume, Container
    nodes = read_tree(str(root))
    bootstrap_permissions(nodes)
    nodes.children['metal-addons'].children['NativeAdrenoMetal.bundle'].children['NativeAdrenoMetal'].mode = stat.S_IFREG | 0o755
    image = args.output / 'NabuInit.apfs'
    container = Container([Volume(0, 'NabuInit', nodes, False, 1683900000 * 1000000000, None, [])], 256, image.name)
    container.layout()
    container.write(str(image))
    check = subprocess.run(host_command([host_path(ROOT / 'build/apfsprogs/apfsck/apfsck'),
        '-c', '-u', '-w', host_path(image)]), capture_output=True)
    (args.output / 'NabuInit-apfsck.log').write_bytes(check.stdout + check.stderr)
    check.check_returncode()
    readbacks = []
    for relative in changed:
        result = subprocess.run(host_command([host_path(ROOT / 'build/nabu-audio-apfs-reader/apfs-tool'),
            'cat', host_path(image), '/' + relative]), capture_output=True, check=True)
        assert result.stdout == (root / relative).read_bytes(), relative
        readbacks.append(dict(path=relative, bytes=len(result.stdout), native_readback_equal=True))
    for name in ['Boot.apfs', 'App.apfs']:
        shutil.copyfile(args.baseline / name, args.output / name)
    combined = args.output / 'bootstrap.apfs'
    with combined.open('wb') as output:
        for name in ['Boot.apfs', 'NabuInit.apfs', 'App.apfs']:
            with (args.output / name).open('rb') as source:
                shutil.copyfileobj(source, output)
    report = json.loads((args.baseline / 'bootstrap-report.json').read_text())
    report.update(bytes=combined.stat().st_size, sha256=hashlib.sha256(combined.read_bytes()).hexdigest(),
                  device_execution_validated=False)
    for item in report['containers']:
        if item['name'] == 'NabuInit.apfs':
            item.update(bytes=image.stat().st_size, sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    report['jailbreak_runtime'] = dict(baseline=str(args.baseline), setup_build=build,
        changed_files=changed, readbacks=readbacks, apfsck_passed=True,
        prefix='/private/var/db/nabu-jailbreak/procursus', existing_seed_preserved=True,
        restore_before_launchd=True, tweak_injection_enabled=False,
        tweak_injection_requires_verified_persistent_marker=True, runtime_verified=False,
        keyboard_compatibility=keyboard_build, requires_extended_exec_configuration=True,
        unity_metal_fix=metal_build)
    (args.output / 'bootstrap-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result='assembled-not-run', bytes=report['bytes'], changed_files=changed,
                         apfsck_passed=True, native_readbacks_passed=True)))


if __name__ == '__main__':
    main()
