#!/usr/bin/env python3
"""Build and test the source-owned QCA service for the native BlueTool contract."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    include = ROOT / 'patches/nabu-wireless'
    source = ROOT / 'userland/nabu/src/bluetooth_lifecycle.c'
    common = ['-fblocks', '-Os', '-Wall', '-Wextra', '-Werror', '-I', str(include)]
    test = args.output / 'lifecycle-host-test'
    subprocess.run(['xcrun', '--sdk', 'macosx', 'clang', *common,
                    '-fsanitize=address,undefined', '-g',
                    str(ROOT / 'tools/test_nabu_bluetooth_lifecycle.c'), '-o', str(test)], check=True)
    tested = subprocess.run([str(test.resolve())], capture_output=True, text=True)
    (args.output / 'host-test.log').write_text(tested.stdout + tested.stderr)
    tested.check_returncode()
    compat_test = args.output / 'compat-host-test'
    subprocess.run(['xcrun', '--sdk', 'macosx', 'clang', *common,
                    '-fsanitize=address,undefined', '-g',
                    str(ROOT / 'tools/test_nabu_bluetooth_compat.c'), '-o', str(compat_test)], check=True)
    tested = subprocess.run([str(compat_test.resolve())], capture_output=True, text=True)
    (args.output / 'compat-host-test.log').write_text(tested.stdout + tested.stderr)
    tested.check_returncode()
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    binary = args.output / 'nabu-bluetooth-lifecycle'
    command = ['xcrun', 'clang', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk,
               *common, str(source), '-o', str(binary)]
    subprocess.run(command, check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(binary)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
    compat = args.output / 'libnabu.bluetooth.compat.dylib'
    subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk,
                    *common, '-dynamiclib', '-install_name', '/redwood/lib/libnabu.bluetooth.compat.dylib',
                    str(ROOT / 'userland/nabu/src/bluetooth_compat.c'), '-o', str(compat)], check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(compat)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(compat)], check=True)
    report = {'target': 'arm64-ios16.5', 'source': str(source.relative_to(ROOT)),
              'command': command, 'bytes': binary.stat().st_size,
              'host_hci_tests': 'ASan/UBSan passed', 'runtime_verified': False,
              'service': 'com.apple.BlueTool', 'user': 'mobile',
              'deepsleep_semantics': 'HCI Reset and confirmed IBS transport idle; shared supplies retained',
              'donor_vendor_or_firmware_fabricated': False, 'private_entitlements_added': False}
    report['optional_reporting_compatibility'] = {
        'binary': compat.name, 'bytes': compat.stat().st_size, 'host_test': 'ASan/UBSan passed',
        'scope': '20F66 bluetoothd initializer slot24; actual supportedCommands byte18 bit3',
        'supported_path': 'original initializer with original record argument',
        'unsupported_path': 'advance original sequence without emitting an HCI command or reply',
        'text_or_controller_support_patched': False, 'runtime_verified': False}
    report['legacy_host_periodic_compatibility'] = {
        'binary': compat.name, 'host_test': 'ASan/UBSan passed',
        'scope': '20F66 bluetoothd slot18; temporary host initialization downgrade',
        'required_disabled_host_choices': ['standard_advertising', 'extended_advertising',
            'extended_scanning', 'extended_scan_hci', 'periodic_advertiser',
            'periodic_synchronizer', 'enhanced_connections'],
        'host_policy_boolean_combinations_tested': 128,
        'all_disabled_path': 'advance original sequence without sending ReadPeriodicAdvertiserListSize',
        'any_enabled_path': 'original initializer with original record argument',
        'initializer_data_slot_replaced': True,
        'controller_features_or_responses_fabricated': False, 'runtime_verified': False}
    (args.output / 'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
