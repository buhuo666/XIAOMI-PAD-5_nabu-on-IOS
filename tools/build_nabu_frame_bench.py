#!/usr/bin/env python3
"""Build the standalone sustained native-resolution Metal benchmark on macOS CI."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = 'org.nabu.FrameBench'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Build with macOS GitHub Actions and Xcode16.4')
    output = args.output.resolve()
    app = output / 'Payload/FrameBench.app'
    app.mkdir(parents=True, exist_ok=False)
    report = {'result': 'building', 'source_commit': os.environ.get('GITHUB_SHA'),
              'ci_run': os.environ.get('GITHUB_RUN_ID'), 'bundle_identifier': BUNDLE,
              'device_executed': False, 'commands': []}

    def run(argv):
        argv = list(map(str, argv)); report['commands'].append(argv)
        result = subprocess.run(argv, capture_output=True, text=True)
        (output / f'command-{len(report["commands"]):02d}.log').write_text(result.stdout + result.stderr)
        if result.returncode: raise RuntimeError((result.stdout + result.stderr)[-6000:])
        return result

    try:
        xcode = run(['xcodebuild', '-version']).stdout.strip()
        if not xcode.startswith('Xcode 16.4\n'): raise ValueError('Expected Xcode16.4')
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        source = ROOT / 'userland/nabu/apps/FrameBench'
        air = output / 'FrameBench.air'
        run(['xcrun', '--sdk', 'iphoneos', 'metal', '-target', 'air64-apple-ios16.5',
             '-std=ios-metal2.4', '-c', source / 'FrameBench.metal', '-o', air])
        run(['xcrun', '--sdk', 'iphoneos', 'metallib', air, '-o', app / 'FrameBench.metallib'])
        run(['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', 'arm64-apple-ios16.5',
             '-isysroot', sdk, '-std=c++17', '-O2', '-g', '-fobjc-arc', '-fblocks',
             '-Wall', '-Wextra', '-Werror', '-fstack-protector-strong', source / 'main.mm',
             '-framework', 'UIKit', '-framework', 'Foundation', '-framework', 'Metal',
             '-framework', 'QuartzCore', '-framework', 'IOSurface', '-o', app / 'FrameBench'])
        run(['xcrun', 'ibtool', '--compile', app / 'LaunchScreen.storyboardc', '--sdk', sdk,
             '--minimum-deployment-target', '16.5', '--target-device', 'ipad',
             ROOT / 'userland/nabu/apps/LocalTest/LaunchScreen.storyboard'])
        info = {'CFBundleIdentifier': BUNDLE, 'CFBundleName': 'FrameBench', 'CFBundleExecutable': 'FrameBench',
                'CFBundleDisplayName': 'GPU帧率基准', 'CFBundlePackageType': 'APPL',
                'CFBundleInfoDictionaryVersion': '6.0', 'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0',
                'MinimumOSVersion': '16.5', 'CFBundleSupportedPlatforms': ['iPhoneOS'],
                'LSRequiresIPhoneOS': True, 'UIDeviceFamily': [2], 'UIRequiresFullScreen': True,
                'UILaunchStoryboardName': 'LaunchScreen', 'UIFileSharingEnabled': True,
                'UISupportedInterfaceOrientations': ['UIInterfaceOrientationPortrait'],
                'CADisableMinimumFrameDurationOnPhone': True}
        (app / 'Info.plist').write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
        entitlements = {'com.apple.security.ts.opengl-or-metal': True}
        signing = output / 'entitlements.plist'; signing.write_bytes(plistlib.dumps(entitlements))
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
             '--identifier', BUNDLE, '--entitlements', signing, app])
        run(['codesign', '--verify', '--strict', app])
        signature = run(['codesign', '--display', '--verbose=4', app]).stderr
        if not re.search(r'^Page size=4096$', signature, re.M): raise ValueError('Signature page size mismatch')
        signed = plistlib.loads(run(['codesign', '--display', '--xml', '--entitlements', '-', app]).stdout.encode())
        if signed != entitlements: raise ValueError('Entitlements mismatch')
        dependencies = run(['otool', '-L', app / 'FrameBench']).stdout
        if 'libnabu' in dependencies or 'libvulkan' in dependencies: raise ValueError('App must use system Metal discovery')
        ipa = output / 'NabuFrameBench.ipa'
        with zipfile.ZipFile(ipa, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(app.rglob('*')):
                if path.is_file(): archive.write(path, path.relative_to(output).as_posix())
        report.update(result='signed_not_run', ipa=ipa.name, ipa_bytes=ipa.stat().st_size,
                      width=1600, height=2560, scenes=['opaque_motion', 'eight_layer_alpha'],
                      repetitions=3, seconds_per_run=60, soak_seconds=600, readback_during_capture=False)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(result='failed', error=str(error))
    (output / 'build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'commands'}, ensure_ascii=False))
    return 0 if report['result'] == 'signed_not_run' else 1


if __name__ == '__main__':
    raise SystemExit(main())
