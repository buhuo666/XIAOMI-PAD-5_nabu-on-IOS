#!/usr/bin/env python3
"""Build the on-device root/debug/JIT/injection capability probe."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from build_nabu_app_store import zip_app
from build_nabu_gpu_vulkan_probe import macho_target

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Use macOS/Xcode')
    out = args.output.resolve()
    app = out/'Payload/JailbreakProbe.app'
    app.mkdir(parents=True, exist_ok=False)
    identifier = 'org.nabu.JailbreakProbe'
    entitlements = {key: True for key in ['platform-application', 'com.apple.private.security.no-sandbox',
        'com.apple.private.persona-mgmt', 'task_for_pid-allow',
        'com.apple.security.cs.allow-jit', 'dynamic-codesigning']}
    entitlements['application-identifier'] = identifier
    entitlement_file = out/'entitlements.plist'
    entitlement_file.write_bytes(plistlib.dumps(entitlements))
    (app/'Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleIdentifier=identifier, CFBundleExecutable='JailbreakProbe', CFBundleName='JailbreakProbe',
        CFBundleDisplayName='越狱能力验证', CFBundlePackageType='APPL', CFBundleVersion='2',
        CFBundleShortVersionString='1.0', MinimumOSVersion='16.5', UIDeviceFamily=[2],
        CFBundleSupportedPlatforms=['iPhoneOS'], LSRequiresIPhoneOS=True, UIRequiresFullScreen=True,
        UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait'],
        UILaunchScreen={}, UIRequiredDeviceCapabilities=['arm64'])))
    report = {'result': 'building', 'ci': {'run_id': os.environ.get('GITHUB_RUN_ID'), 'head_sha': os.environ.get('GITHUB_SHA')},
              'commands': [], 'bundle_id': identifier, 'device_executed': False,
              'scope': 'Root helper and owned child processes only; task memory, ptrace, W-to-X JIT and DYLD injection'}

    def run(command):
        command = list(map(str, command))
        report['commands'].append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        (out/('command-%02d.log' % len(report['commands']))).write_text(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout+result.stderr)[-6000:])
        return result

    try:
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        flags = ['xcrun', '--sdk', 'iphoneos', 'clang', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk,
                 '-Os', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations']
        injection = app/'NabuProbeInjection.dylib'
        run([*flags, '-dynamiclib', ROOT/'userland/nabu/src/jailbreak_probe_injection.c',
             '-Wl,-install_name,@executable_path/NabuProbeInjection.dylib', '-o', injection])
        run([*flags, '-fobjc-arc', '-fblocks', ROOT/'userland/nabu/src/jailbreak_probe.m',
             '-framework', 'Foundation', '-framework', 'UIKit', '-o', app/'JailbreakProbe'])
        macho_target(injection, 6)
        macho_target(app/'JailbreakProbe', 2)
        for path in [injection, app/'JailbreakProbe']:
            path.chmod(0o755)
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096', injection])
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
             '--identifier', identifier, '--entitlements', entitlement_file, app])
        run(['codesign', '--verify', '--strict', app])
        actual = run(['codesign', '--display', '--entitlements', '-', '--xml', app]).stdout
        assert plistlib.loads(actual.encode()) == entitlements
        zip_app(app, out/'NabuJailbreakProbe.ipa')
        report.update(result='signed-not-run', ipa_ready=True)
    finally:
        (out/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ['result', 'bundle_id', 'device_executed']}))


if __name__ == '__main__':
    main()
