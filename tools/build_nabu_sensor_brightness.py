#!/usr/bin/env python3
"""Test and compile the scoped original-20F66 ALS association bridge; never launch it."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from build_nabu_gpu_vulkan_probe import macho_target

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'arm64-apple-ios16.5'


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
        'source': 'userland/nabu/src/sensor_brightness_bridge.m',
        'scope': 'Original 20F66 CBABModuleiOS addHIDServiceClient: callsite +0x134 only',
        'identity': 'actual NabuSensorSource registry ID, physical SUID, generation, active ALS and lux units',
        'host_tests_passed': False, 'automatic_launch_added': False, 'device_executed': False,
        'required_bootarg': 'nabu-sensor-brightness=1',
        'entitlements_added': False,
        'runtime_limitations': [
            'Host tests substitute in-memory IOKit endpoints while executing the production wrappers with real CF objects.',
            'Host tests do not verify dyld interposing, original 20F66 installation or AABC initialization on iPadOS.',
            'Native add return values and association do not establish ALS event delivery or automatic brightness.',
            'Actual automatic brightness and CoreBrightness consumption require real-device validation.',
        ],
    }

    def run(command, *, timeout=180):
        command = list(map(str, command))
        report['commands'].append(command)
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        (output / ('command-%02d.log' % len(report['commands']))).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-6000:])
        return result

    try:
        report['xcode'] = run(['xcodebuild', '-version']).stdout.strip()
        if not report['xcode'].startswith('Xcode 16.4\n'):
            raise ValueError('Select Xcode 16.4')
        host_sdk = run(['xcrun', '--sdk', 'macosx', '--show-sdk-path']).stdout.strip()
        host_base = ['xcrun', '--sdk', 'macosx', 'clang', '-isysroot', host_sdk,
                     '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
                     '-g', '-O1', '-fsanitize=address,undefined']
        identity_test = output / 'sensor-brightness-identity-test'
        run([*host_base, '-std=c11', ROOT / 'userland/nabu/tests/sensor_brightness_identity_test.c',
             '-o', identity_test])
        report['identity_test'] = run([identity_test], timeout=30).stdout.strip()
        wrapper_test = output / 'sensor-brightness-wrapper-test'
        run([*host_base, '-std=gnu11', '-fobjc-arc', '-fobjc-exceptions',
             ROOT / 'userland/nabu/tests/sensor_brightness_bridge_test.m',
             '-framework', 'Foundation', '-framework', 'IOKit', '-o', wrapper_test])
        report['wrapper_test'] = run([wrapper_test], timeout=30).stdout.strip()
        report['host_tests_passed'] = True

        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        binary = output / 'libnabu.sensor-brightness.dylib'
        run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', TARGET, '-isysroot', sdk,
             '-std=gnu11', '-Os', '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
             '-fobjc-arc', '-fobjc-exceptions', '-dynamiclib',
             '-install_name', '/redwood/lib/libnabu.sensor-brightness.dylib',
             ROOT / report['source'], '-framework', 'Foundation', '-framework', 'IOKit', '-o', binary])
        macho_target(binary, 6)  # MH_DYLIB; the daemon is MH_EXECUTE (2).
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
             '--identifier', 'org.nabu.sensor-brightness', binary])
        run(['codesign', '--verify', '--strict', binary])
        details = run(['codesign', '--display', '--verbose=4', binary]).stderr
        match = re.search(r'^CDHash=([0-9a-f]{40})$', details, re.M)
        if not match or not re.search(r'^Page size=4096$', details, re.M):
            raise ValueError('Expected 4 KiB signature pages and a CDHash')
        macho_target(binary, 6)
        report['binary'] = {
            'file': binary.name, 'bytes': binary.stat().st_size, 'cdhash': match[1],
            'signature_page_bytes': 4096,
            'dependencies': run(['xcrun', 'otool', '-L', binary]).stdout.strip(),
        }
        report['result'] = 'signed_not_run'
    except Exception as error:
        report.update(result='failed', error=str(error))
        raise
    finally:
        (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
