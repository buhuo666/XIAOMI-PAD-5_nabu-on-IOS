#!/usr/bin/env python3
"""Prepare or explicitly run the two store IPA installs over existing native USB."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--install', action='store_true', help='Install only after the device is in iPadOS; never reboots it')
    args = parser.parse_args()
    build = args.build.resolve()
    report = json.loads((build/'build-report.json').read_text())
    if report['result'] != 'signed-not-run' or not report['ipa_ready']:
        parser.error('Both signed IPAs must be built before preparing installation')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    commands = []
    for item in report['apps']:
        ipa = build/item['ipa']
        with zipfile.ZipFile(ipa) as archive:
            info = plistlib.loads(archive.read(f'Payload/{item["app"]}.app/Info.plist'))
        if info['CFBundleIdentifier'] != item['bundle_id']:
            raise ValueError(f'IPA bundle identity differs: {ipa.name}')
        commands.append([sys.executable, str(ROOT/'tools/install_nabu_test_app.py'),
                         '--ipa', str(ipa), '--bundle-id', item['bundle_id'], '--app-name', item['app'],
                         '--output', str(output/item['app'])])
    plan = {'mode': 'install' if args.install else 'plan-only', 'commands': commands,
            'reboots_device': False, 'installs_verified': False, 'launch_verified': False}
    (output/'install-plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    if not args.install:
        print('Installation plan saved. No device connection was made.')
        return
    for item, command in zip(report['apps'], commands):
        print('Installing '+item['app'], flush=True)
        with (output/(item['app']+'.stdout')).open('wb') as stdout, (output/(item['app']+'.stderr')).open('wb') as stderr:
            subprocess.run(command, cwd=ROOT, stdout=stdout, stderr=stderr, check=True)
        installed = json.loads((output/item['app']/'install.json').read_text())
        if not installed['installed_verified']:
            raise RuntimeError('USB installation not verified for '+item['app'])
    plan['installs_verified'] = True
    (output/'install-plan.json').write_text(json.dumps(plan, indent=2)+'\n')
    print('Both apps registered. Opening, downloading and installing an app remain user tests.')


if __name__ == '__main__':
    main()
