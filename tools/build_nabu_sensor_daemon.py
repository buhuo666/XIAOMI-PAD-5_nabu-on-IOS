#!/usr/bin/env python3
"""Compile the serial NabuSensorSource-to-HID owner; never launch it."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys

from build_nabu_gpu_vulkan_probe import macho_target

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'arm64-apple-ios16.5'
# Present in Apple's IOHIDEventSystemMonitor entitlement profile. Its acceptance
# by the original 20F66 virtual-service server remains a separate device check.
ENTITLEMENTS = {'com.apple.private.hid.client.event-dispatch': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Use macOS with the existing Xcode 16.4 iPhoneOS SDK')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        'result': 'building', 'target': TARGET, 'commands': [],
        'ci': {'run_id': os.environ.get('GITHUB_RUN_ID'), 'head_sha': os.environ.get('GITHUB_SHA')},
        'source_abi': 'patches/nabu-sensors/NabuSensorHid.h', 'source_abi_version': 1,
        'source_service': 'NabuSensorSource', 'source_open_type': 0x534e,
        'entitlements': ENTITLEMENTS,
        'entitlement_evidence': 'Apple IOHIDFamily tools/IOHIDEventSystemMonitor-Entitlements.plist; local evidence log/host/sensors-daemon-20261110',
        'independent_virtual_service_authority_verified': False,
        'axes_six_face_verified': False, 'device_executed': False,
        'automatic_launch_added': False,
        'runtime_command': '/redwood/sbin/nabu-sensor-daemon --axes 1,2,3 --seconds 120 --log /var/mobile/Media/nabu-sensor-daemon.jsonl',
    }

    def run(command):
        command = list(map(str, command))
        report['commands'].append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        (output / ('command-%02d.log' % len(report['commands']))).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-6000:])
        return result

    try:
        report['xcode'] = run(['xcodebuild', '-version']).stdout.strip()
        if not report['xcode'].startswith('Xcode 16.4\n'):
            raise ValueError('Select Xcode 16.4')
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        base = ['xcrun', '--sdk', 'iphoneos', 'clang', '-target', TARGET, '-isysroot', sdk,
                '-Os', '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
                '-I' + str(ROOT / 'patches/nabu-sensors')]
        daemon_object, bridge_object = output / 'sensor-daemon.o', output / 'sensor-bridge.o'
        run([*base, '-fobjc-arc', '-c', ROOT / 'userland/nabu/src/sensor_daemon.m', '-o', daemon_object])
        run([*base, '-std=c11', '-c', ROOT / 'userland/nabu/src/sensor_bridge.c', '-o', bridge_object])
        binary = output / 'nabu-sensor-daemon'
        run([*base, daemon_object, bridge_object, '-framework', 'Foundation', '-framework', 'IOKit', '-o', binary])
        macho_target(binary, 2)
        entitlements = output / 'entitlements.plist'
        entitlements.write_bytes(plistlib.dumps(ENTITLEMENTS))
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
             '--identifier', 'org.nabu.sensor-daemon', '--entitlements', entitlements, binary])
        run(['codesign', '--verify', '--strict', binary])
        details = run(['codesign', '--display', '--verbose=4', binary]).stderr
        match = re.search(r'^CDHash=([0-9a-f]{40})$', details, re.M)
        if not match or not re.search(r'^Page size=4096$', details, re.M):
            raise ValueError('Expected 4 KiB signature pages and a CDHash')
        signed = plistlib.loads(run(['codesign', '--display', '--xml', '--entitlements', '-', binary]).stdout.encode())
        if signed != ENTITLEMENTS:
            raise ValueError('Signed entitlements differ from the candidate profile')
        report['binary'] = {'file': binary.name, 'bytes': binary.stat().st_size,
                            'cdhash': match[1], 'signature_page_bytes': 4096,
                            'dependencies': run(['xcrun', 'otool', '-L', binary]).stdout.strip()}
        report['result'] = 'signed_not_run'
    except Exception as error:
        report.update(result='failed', error=str(error))
        raise
    finally:
        (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
