#!/usr/bin/env python3
"""Build the fixed Sileo 2.5.1 parent-checked helper for the Nabu rootless prefix."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from build_nabu_gpu_vulkan_probe import macho_target
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'patches/nabu-jailbreak/SileoGiveMeRoot.c'
COMMIT = 'c9f70158a037dc76b91c450e72af2de0514dd3ee'
ENTITLEMENTS = {
    'platform-application': True,
    'com.apple.private.security.no-container': True,
    'com.apple.private.skip-library-validation': True,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['signed', 'compile'], default='signed')
    parser.add_argument('--sdk', type=Path, help='Required for a local cross-compile')
    args = parser.parse_args()
    if args.mode == 'signed' and sys.platform != 'darwin':
        parser.error('Signed output requires macOS codesign; use --mode compile --sdk for the local ABI check')
    if sys.platform != 'darwin' and not args.sdk:
        parser.error('--sdk is required for a local cross-compile')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    binary = out / 'giveMeRoot'
    source = SOURCE.read_text(encoding='utf-8')
    (out / SOURCE.name).write_text(source, encoding='utf-8')
    (out / 'entitlements.plist').write_bytes(plistlib.dumps(ENTITLEMENTS))
    license_text = source.split(' * Source:', 1)[0][3:]
    license_text = '\n'.join(line[3:] if line.startswith(' * ') else '' for line in license_text.splitlines()).strip() + '\n'
    (out / 'Sileo-LICENSE').write_text(license_text, encoding='utf-8')
    provenance = {
        'project': 'Sileo/Sileo', 'commit': COMMIT,
        'source': f'https://github.com/Sileo/Sileo/blob/{COMMIT}/giveMeRoot/giveMeRoot.c',
        'license': f'https://github.com/Sileo/Sileo/blob/{COMMIT}/LICENSE',
        'change': 'Release path /Applications/Sileo.app/Sileo -> /var/jb/Applications/Sileo.app/Sileo',
        'parent_path_check_preserved': True,
        'original_uid_and_exec_behavior_preserved': True,
        'ios13plus_sileo_uses_persona_instead_of_this_legacy_helper': True,
    }
    (out / 'source-provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    report = {
        'result': 'building', 'target': 'arm64-apple-ios16.5', 'commands': [],
        'device_executed': False, 'signed_entitlements_verified': False,
        'source_provenance': provenance,
        'ci': {'run_id': os.environ.get('GITHUB_RUN_ID'), 'head_sha': os.environ.get('GITHUB_SHA')},
    }

    def run(command):
        command = list(map(str, command))
        report['commands'].append(command)
        value = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        (out / ('command-%02d.log' % len(report['commands']))).write_text(value.stdout + value.stderr, encoding='utf-8')
        if value.returncode:
            raise RuntimeError((value.stdout + value.stderr)[-6000:])
        return value

    try:
        if sys.platform == 'darwin':
            sdk = args.sdk.resolve() if args.sdk else Path(run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip())
            run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', report['target'], '-isysroot', sdk,
                 '-O2', '-Wall', '-Wextra', '-Werror', SOURCE, '-o', binary])
        else:
            sdk = args.sdk.resolve()
            obj = out / 'giveMeRoot.o'
            run(host_command(['clang-18', '-target', report['target'], '-isysroot', host_path(sdk),
                 '-O2', '-Wall', '-Wextra', '-Werror', '-c', host_path(SOURCE), '-o', host_path(obj)]))
            run(host_command(['ld64.lld-18', '-arch', 'arm64', '-platform_version', 'ios', '16.5', '16.5',
                 '-syslibroot', host_path(sdk), '-adhoc_codesign', host_path(obj), '-lSystem', '-o', host_path(binary)]))
        macho_target(binary, 2)
        raw = binary.read_bytes()
        assert b'/var/jb/Applications/Sileo.app/Sileo\0' in raw
        assert b'/Applications/Sileo.app/Sileo\0' not in raw.replace(b'/var/jb/Applications/Sileo.app/Sileo\0', b'')
        assert b'Error: permission denied, parent process is not Sileo\0' in raw
        binary.chmod(0o755)
        report['result'] = 'arm64-linked-not-distribution-signed'
        if args.mode == 'signed':
            run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
                 '--identifier', 'org.coolstar.SileoStore.giveMeRoot', '--entitlements', out / 'entitlements.plist', binary])
            run(['codesign', '--verify', '--strict', binary])
            displayed = run(['codesign', '--display', '--entitlements', '-', '--xml', binary]).stdout
            assert plistlib.loads(displayed.encode()) == ENTITLEMENTS
            report['signed_entitlements_verified'] = True
            report['result'] = 'signed-not-run'
    finally:
        (out / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'result': report['result'], 'output': str(out)}))


if __name__ == '__main__':
    main()
