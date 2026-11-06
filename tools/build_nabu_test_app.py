#!/usr/bin/env python3
"""Build the source-owned offline UIKit test IPA with the macOS iPhoneOS SDK."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='Output directory; Payload/LocalTest.app must not already exist')
    args = parser.parse_args()
    output = args.output.resolve()
    app = output / 'Payload/LocalTest.app'
    app.mkdir(parents=True)
    sdk = subprocess.check_output(
        ['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    source = ROOT / 'userland/nabu/apps/LocalTest/main.m'
    executable = app / 'LocalTest'
    command = ['xcrun', 'clang', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk,
               '-fobjc-arc', '-fblocks', '-Os', '-Wall', '-Wextra', '-Werror',
               str(source), str(source.with_name('keyboard_diagnostic.m')),
               str(ROOT / 'userland/nabu/src/experience_compat.m'), '-framework', 'UIKit', '-framework', 'Foundation',
               '-o', str(executable)]
    subprocess.run(command, check=True)
    executable.chmod(0o755)
    subprocess.run(['xcrun', 'ibtool', '--compile', str(app / 'LaunchScreen.storyboardc'),
                    '--sdk', sdk, '--minimum-deployment-target', '16.5', '--target-device', 'ipad',
                    str(source.with_name('LaunchScreen.storyboard'))], check=True)
    info = {
        'CFBundleIdentifier': 'org.nabu.LocalTest',
        'CFBundleName': 'LocalTest',
        'CFBundleDisplayName': 'Nabu Test',
        'CFBundleExecutable': 'LocalTest',
        'CFBundlePackageType': 'APPL',
        'CFBundleInfoDictionaryVersion': '6.0',
        'CFBundleVersion': '4',
        'CFBundleShortVersionString': '1.3',
        'CFBundleDevelopmentRegion': 'zh-Hans',
        'CFBundleLocalizations': ['zh-Hans'],
        'CFBundleSupportedPlatforms': ['iPhoneOS'],
        'MinimumOSVersion': '16.5',
        'LSRequiresIPhoneOS': True,
        'UIDeviceFamily': [2],
        'UILaunchStoryboardName': 'LaunchScreen',
        'UISupportedInterfaceOrientations': [
            'UIInterfaceOrientationPortrait', 'UIInterfaceOrientationPortraitUpsideDown',
            'UIInterfaceOrientationLandscapeLeft', 'UIInterfaceOrientationLandscapeRight'],
    }
    (app / 'Info.plist').write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(app)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(app)], check=True)
    ipa = output / 'NabuLocalTest.ipa'
    with zipfile.ZipFile(ipa, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(output).as_posix())
    report = {
        'target': 'arm64-ios16.5', 'bundle_identifier': info['CFBundleIdentifier'],
        'display_name': info['CFBundleDisplayName'],
        'source': source.relative_to(ROOT).as_posix(), 'command': command,
        'ipa': str(ipa), 'ipa_bytes': ipa.stat().st_size,
        'executable_bytes': executable.stat().st_size,
        'signature': 'ad-hoc', 'codesign_verify_passed': True,
        'provisioning_profile_included': False, 'certificate_included': False,
        'network_calls': False, 'state_file': 'Documents/counts.plist',
        'installed_verified': False, 'launch_verified': False,
        'persistence_verified': False,
        'scope': 'Self-owned UIKit test; archive and signature checks do not prove device installation',
    }
    (output / 'build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                             encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
