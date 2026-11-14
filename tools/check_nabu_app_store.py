#!/usr/bin/env python3
"""Check store inputs and exercise the production child-status code with real processes."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import sys
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sources = args.sources.resolve()
    source_report = json.loads((sources/'source-report.json').read_text())
    assert source_report['result'] == 'sources-prepared-not-built'
    binary = out/'child-status-test'
    compiler = ['xcrun', '--sdk', 'macosx', 'clang'] if sys.platform == 'darwin' else ['clang-18']
    subprocess.run(host_command([*compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                                '-fsanitize=address,undefined', '-g',
                                '-I', host_path(sources/'Common'),
                                host_path(ROOT/'userland/nabu/tests/app_store_child_status_test.c'),
                                '-o', host_path(binary)]), check=True)
    test = subprocess.run(host_command([host_path(binary)]), text=True, encoding='utf-8', errors='replace', capture_output=True, check=True)
    (out/'child-status.log').write_text(test.stdout+test.stderr, encoding='utf-8')
    lite_info = plistlib.loads((sources/'TrollStore/TrollStoreLite/Resources/Info.plist').read_bytes())
    lite_ents = plistlib.loads((sources/'TrollStore/TrollStoreLite/entitlements.plist').read_bytes())
    apps_ents = plistlib.loads((sources/'TrollApps/TrollApps/entitlements.plist').read_bytes())
    assert lite_info['CFBundleIdentifier'] == lite_ents['application-identifier'] == 'com.opa334.TrollStoreLite'
    assert lite_info['UIRequiredDeviceCapabilities'] == ['arm64']
    assert apps_ents['application-identifier'] == 'org.resonance.store'
    assert lite_ents['com.apple.private.persona-mgmt'] and apps_ents['com.apple.private.persona-mgmt']
    report = {'result': 'passed', 'source_revision': source_report['revision'],
              'child_status_cases': 5, 'sanitizers': ['address', 'undefined'],
              'bundle_and_entitlement_identity_consistent': True,
              'device_executed': False, 'swift_application_built': False}
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(test.stdout.strip())
    print(json.dumps(report))


if __name__ == '__main__':
    main()
