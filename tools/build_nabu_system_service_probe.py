#!/usr/bin/env python3
"""Compile the source-owned filesystem/LaunchServices probe with the iOS SDK."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    source = ROOT / 'userland/nabu/src/system_service_probe.m'
    binary = args.output / 'system-service-probe'
    command = ['xcrun', 'clang', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk,
               '-fobjc-arc', '-Os', '-Wall', '-Wextra', '-Werror',
               '-Wno-deprecated-declarations', str(source), '-framework', 'Foundation', '-o', str(binary)]
    subprocess.run(command, check=True)
    entitlements = ROOT / 'userland/nabu/system-service-probe.entitlements.plist'
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none',
                    '--entitlements', str(entitlements), str(binary)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
    signed_entitlements = plistlib.loads(subprocess.check_output(
        ['codesign', '--display', '--entitlements', '-', str(binary)]))
    assert signed_entitlements == plistlib.loads(entitlements.read_bytes())
    report = {'target': 'arm64-ios16.5', 'source': str(source.relative_to(ROOT)),
              'bytes': binary.stat().st_size, 'command': command, 'default_action': 'inventory',
              'repair_requires_live_paired_host_request': True, 'request_window_seconds': 1200,
              'network_calls': False, 'runtime_verified': False,
              'signed_entitlements': signed_entitlements,
              'daemon_container_query_diagnostic': True}
    (args.output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
