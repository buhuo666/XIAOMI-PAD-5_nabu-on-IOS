#!/usr/bin/env python3
"""Build a removable package testing the installed ElleKit on two owned processes."""
import argparse
import gzip
import io
import json
import math
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile

from build_nabu_gpu_vulkan_probe import macho_target

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'org.nabu.jailbreak.selftest'
VERSION = '1.0'
BIN = 'var/jb/usr/libexec/nabu-jailbreak-tests'
INJECT = 'var/jb/usr/lib/TweakInject'


def tar_gzip(entries):
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
            for name, mode, data in entries:
                item = tarfile.TarInfo('./' + name)
                item.uid = item.gid = item.mtime = 0
                item.uname = item.gname = 'root'
                item.mode = mode
                if data is None:
                    item.type = tarfile.DIRTYPE
                    archive.addfile(item)
                else:
                    item.size = len(data)
                    archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


def deb_archive(members):
    output = bytearray(b'!<arch>\n')
    for name, data in members:
        header = f'{name + "/":<16}{0:<12}{0:<6}{0:<6}{"100644":<8}{len(data):<10}`\n'.encode('ascii')
        assert len(header) == 60
        output += header + data
        if len(data) & 1:
            output += b'\n'
    return output


def package(out, target, tweak):
    filter_data = plistlib.dumps({'Filter': {'Executables': ['nabu-tweak-target']}}, fmt=plistlib.FMT_XML)
    files = [(BIN + '/nabu-tweak-target', 0o755, target.read_bytes()),
             (BIN + '/nabu-tweak-control', 0o755, target.read_bytes()),
             (INJECT + '/NabuJailbreakTest.dylib', 0o644, tweak.read_bytes()),
             (INJECT + '/NabuJailbreakTest.plist', 0o644, filter_data)]
    # Common prefix directories already belong to the bootstrap/ElleKit.
    # The package only adds its own two binaries and one filter/dylib pair.
    control = (f'Package: {PACKAGE}\nVersion: {VERSION}\nArchitecture: iphoneos-arm64\n'
               'Maintainer: Nabu Project\nSection: Development\nPriority: optional\n'
               'Depends: ellekit (>= 0.4.5)\n'
               f'Installed-Size: {math.ceil(sum(len(data) for _, _, data in files) / 1024)}\n'
               'Name: Nabu Jailbreak Self Test\n'
               'Description: Temporary owned-process package and ElleKit acceptance test.\n').encode()
    package_file = out / 'NabuJailbreakSelfTest.deb'
    package_file.write_bytes(deb_archive([
        ('debian-binary', b'2.0\n'),
        ('control.tar.gz', tar_gzip([('control', 0o644, control)])),
        ('data.tar.gz', tar_gzip([(BIN, 0o755, None), *files]))]))
    (out / 'NabuJailbreakTest.plist').write_bytes(filter_data)
    manifest = dict(package=PACKAGE, version=VERSION, architecture='iphoneos-arm64',
                    depends='ellekit (>= 0.4.5)', maintainer_scripts=[],
                    files=[dict(path='/' + name, mode=oct(mode), uid=0, gid=0, bytes=len(data)) for name, mode, data in files],
                    owned_directory='/' + BIN, device_executed=False,
                    target='/' + BIN + '/nabu-tweak-target', control='/' + BIN + '/nabu-tweak-control',
                    expected_uid=501, expected_euid=501,
                    loader_environment={'DYLD_INSERT_LIBRARIES': '/var/jb/usr/lib/TweakLoader.dylib'},
                    cases=[dict(executable='nabu-tweak-target', arguments=['--expect', 'plain'], inject_loader=False, expected_value=7),
                           dict(executable='nabu-tweak-target', arguments=['--expect', 'hooked'], inject_loader=True, expected_value=42, expected_original=7),
                           dict(executable='nabu-tweak-control', arguments=['--expect', 'filtered'], inject_loader=True, expected_value=7)],
                    removal=['/var/jb/usr/bin/dpkg', '--purge', PACKAGE],
                    removal_verification='Every listed file and the exact dpkg package record must be absent after purge.')
    (out / 'package-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return package_file


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--target', type=Path, help='Package an already built target together with --tweak; no compilation.')
    parser.add_argument('--tweak', type=Path, help='Package an already built signed dylib together with --target.')
    args = parser.parse_args()
    if bool(args.target) != bool(args.tweak):
        parser.error('--target and --tweak must be supplied together')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = dict(result='building', device_executed=False, commands=[],
                  ci={'run_id': os.environ.get('GITHUB_RUN_ID'), 'head_sha': os.environ.get('GITHUB_SHA')})

    def run(command):
        command = list(map(str, command)); report['commands'].append(command)
        result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        (out / ('command-%02d.log' % len(report['commands']))).write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr)[-6000:])
        return result.stdout

    try:
        target = out / 'nabu-tweak-target'
        tweak = out / 'NabuJailbreakTest.dylib'
        if args.target:
            shutil.copyfile(args.target, target); shutil.copyfile(args.tweak, tweak)
            macho_target(target, 2); macho_target(tweak, 6)
        else:
            if sys.platform != 'darwin':
                raise RuntimeError('The iOS compilation/signing step requires macOS and Xcode.')
            sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).strip()
            common = ['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk,
                      '-std=gnu11', '-Os', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations']
            run([*common, ROOT / 'userland/nabu/src/jailbreak_tweak_target.c',
                 '-Wl,-exported_symbol,_nabu_tweak_value', '-Wl,-exported_symbol,_main', '-o', target])
            run([*common, '-dynamiclib', ROOT / 'userland/nabu/src/jailbreak_tweak_test.c',
                 '-Wl,-install_name,/var/jb/usr/lib/TweakInject/NabuJailbreakTest.dylib', '-o', tweak])
            for binary, identifier, file_type in [(target, PACKAGE + '.target', 2), (tweak, PACKAGE + '.tweak', 6)]:
                macho_target(binary, file_type)
                run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
                     '--identifier', identifier, binary])
                run(['codesign', '--verify', '--strict', binary])
            report['entitlements'] = 'No platform, persona, task_for_pid, JIT or get-task-allow entitlements requested.'
        target.chmod(0o755)
        package_file = package(out, target, tweak)
        report.update(result='package-built-not-run', package=str(package_file), package_bytes=package_file.stat().st_size,
                      built_ios_binaries=not bool(args.target), supplied_binary_mode=bool(args.target))
    finally:
        (out / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'result': report['result'], 'package': str(package_file)}))


if __name__ == '__main__':
    main()
