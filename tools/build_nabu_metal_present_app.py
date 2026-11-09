#!/usr/bin/env python3
"""Build the self-owned UIKit/CAMetalLayer App against the run 172 frontend.

Only the App is compiled and signed. Its frontend and Turnip stay at the same
/redwood/sbin paths used by the qualified factory; the metallib is an App resource.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import zipfile

from build_nabu_gpu_vulkan_probe import TARGET, macho_target

ROOT = Path(__file__).resolve().parents[1]
QUALIFIED_RUN = '42615860281'
BUNDLE_ID = 'org.nabu.MetalPresent'
APP_NAME = 'MetalPresent'
EXECUTABLE = 'nabu-gpu-metal-probe'
APP_ENTITLEMENTS = {
    'com.apple.security.iokit-user-client-class': ['AGXDeviceUserClient'],
    'com.apple.security.ts.opengl-or-metal': True,
}


def app_info():
    return {
        'CFBundleIdentifier': BUNDLE_ID, 'CFBundleName': APP_NAME,
        'CFBundleDisplayName': 'GPU呈现测试', 'CFBundleExecutable': EXECUTABLE,
        'CFBundlePackageType': 'APPL', 'CFBundleInfoDictionaryVersion': '6.0',
        'CFBundleVersion': '1', 'CFBundleShortVersionString': '1.0',
        'CFBundleDevelopmentRegion': 'zh-Hans', 'CFBundleLocalizations': ['zh-Hans'],
        'CFBundleSupportedPlatforms': ['iPhoneOS'], 'MinimumOSVersion': '16.5',
        'LSRequiresIPhoneOS': True, 'UIDeviceFamily': [2], 'UIRequiresFullScreen': True,
        'UILaunchStoryboardName': 'LaunchScreen',
        'UISupportedInterfaceOrientations': ['UIInterfaceOrientationPortrait',
                                            'UIInterfaceOrientationPortraitUpsideDown'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='CI42615860281 nabu-gpu-iosurface-copy-read artifact directory')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Apple App builds run in macOS GitHub Actions')
    source, output = args.input.resolve(), args.output.resolve()
    app = output / 'Payload' / (APP_NAME + '.app')
    app.mkdir(parents=True, exist_ok=False)
    report = {
        'result': 'building', 'target': TARGET, 'bundle_identifier': BUNDLE_ID,
        'bundle_directory': APP_NAME + '.app', 'display_name': 'GPU呈现测试', 'executable': EXECUTABLE,
        'reused_ci_run': QUALIFIED_RUN, 'reused_device_qualification': 172,
        'mtl_device_instance_bytes': 528, 'construction': 'MTLCreateSystemDefaultDevice',
        'frontend_rebuilt': False, 'turnip_rebuilt': False, 'rust_rebuilt': False,
        'metallib_rebuilt': False, 'factory_bundle_rebuilt': False,
        'container_preserved': True, 'entitlements': APP_ENTITLEMENTS,
        'no_container_entitlement_added': False, 'network_features_added': False,
        'installed_verified': False, 'launch_verified': False,
        'gpu_exercised': False, 'presentation_verified': False,
        'documents': ['metal-present-result.json', 'metal-present-readback.bgra', 'metal-present-readback.json'],
        'runtime_paths': {'frontend': '/redwood/sbin/libnabu-metal-frontend.dylib',
                          'turnip': '/redwood/sbin/libvulkan_freedreno.dylib',
                          'factory_cache': '/var/mobile/Media/NabuMetalCache',
                          'mount_ready': '/var/run/nabu-system-metal.ready'},
        'ci': {'run_id': os.environ.get('GITHUB_RUN_ID'), 'head_sha': os.environ.get('GITHUB_SHA')},
        'commands': [],
    }

    def run(command):
        command = list(map(str, command))
        report['commands'].append(command)
        print('+ ' + ' '.join(command), flush=True)
        result = subprocess.run(command, capture_output=True, text=True)
        (output / ('command-%02d.log' % len(report['commands']))).write_text(
            result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-4000:])
        return result

    try:
        prior = json.loads((source / 'build-report.json').read_text(encoding='utf-8'))
        if (prior['ci']['run_id'] != QUALIFIED_RUN or prior['result'] != 'signed_not_run'
                or prior['target'] != TARGET or prior['mtl_device_instance_bytes'] != 528):
            raise ValueError('Expected the exact frontend artifact qualified in run 172')
        report['external_frontend'] = prior['frontend']
        report['external_turnip'] = prior['turnip']
        report['external_factory_bundle'] = prior['bundle']
        shutil.copyfile(source / 'build-report.json', output / 'qualified-runtime-input-report.json')
        metallib = prior['metallib']
        shutil.copyfile(source / metallib['file'], app / metallib['file'])
        report['metallib'] = {**metallib, 'copied_without_recompiling': True, 'location': 'App bundle root'}
        xcode = run(['xcodebuild', '-version']).stdout.strip()
        if not xcode.startswith('Xcode 16.4\n'):
            raise ValueError('Use the qualified Xcode 16.4 App compiler')
        report['xcode'] = xcode
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        app_source = ROOT / 'userland/nabu/apps/MetalPresent/main.mm'
        executable = app / EXECUTABLE
        run(['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', TARGET, '-isysroot', sdk,
             '-std=c++17', '-O2', '-g', '-fobjc-arc', '-fblocks', '-Wall', '-Wextra', '-Werror',
             '-Wno-deprecated-declarations', '-fstack-protector-strong', '-DNABU_EXPECTED_MTL_DEVICE_BYTES=528',
             '-I', ROOT / 'userland/nabu/src', '-I', ROOT / 'src/nabu/gpu/upstream/Adreno6xx', app_source,
             '-L', source, '-lnabu-metal-frontend', '-Wl,-rpath,/redwood/sbin',
             '-framework', 'UIKit', '-framework', 'Foundation', '-framework', 'Metal',
             '-framework', 'QuartzCore', '-framework', 'IOSurface', '-o', executable])
        executable.chmod(0o755)
        macho_target(executable, 2)
        run(['xcrun', 'ibtool', '--compile', app / 'LaunchScreen.storyboardc',
             '--sdk', sdk, '--minimum-deployment-target', '16.5', '--target-device', 'ipad',
             ROOT / 'userland/nabu/apps/LocalTest/LaunchScreen.storyboard'])
        (app / 'Info.plist').write_bytes(plistlib.dumps(app_info(), fmt=plistlib.FMT_BINARY))
        entitlements = output / 'app-entitlements.plist'
        entitlements.write_bytes(plistlib.dumps(APP_ENTITLEMENTS))
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
             '--identifier', BUNDLE_ID, '--entitlements', entitlements, app])
        run(['codesign', '--verify', '--strict', app])
        detail = run(['codesign', '--display', '--verbose=4', app]).stderr
        if not re.search(r'^Page size=4096$', detail, re.M):
            raise ValueError('App code signature must use 4 KiB pages')
        signed = plistlib.loads(run(['codesign', '--display', '--xml', '--entitlements', '-', app]).stdout.encode())
        if signed != APP_ENTITLEMENTS or signed['com.apple.security.ts.opengl-or-metal'] is not True:
            raise ValueError('App signature differs from the two GPU entitlements')
        dependencies = run(['otool', '-L', executable]).stdout
        load_commands = run(['otool', '-l', executable]).stdout
        rpaths = re.findall(r'cmd LC_RPATH\s+cmdsize \d+\s+path (.*?) \(offset \d+\)', load_commands)
        if '@rpath/libnabu-metal-frontend.dylib' not in dependencies or rpaths != ['/redwood/sbin']:
            raise ValueError('App must load the factory frontend through the single /redwood/sbin rpath')
        report['binary'] = {'bytes': executable.stat().st_size, 'dependencies': dependencies.strip(),
                            'rpaths': rpaths, 'signature_page_bytes': 4096,
                            'cdhash': re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)[1],
                            'signed_entitlements': signed}
        ipa = output / 'NabuMetalPresent.ipa'
        with zipfile.ZipFile(ipa, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(app.rglob('*')):
                if path.is_file():
                    archive.write(path, path.relative_to(output).as_posix())
        report.update(result='signed_not_run', ipa=ipa.name, ipa_bytes=ipa.stat().st_size,
                      source=str(app_source.relative_to(ROOT)), codesign_verify_passed=True,
                      provisioning_profile_included=False, native_libraries_embedded=False)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(result='failed', error=str(error))
        print(str(error), file=sys.stderr)
    finally:
        (output / 'build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('result', 'bundle_identifier', 'frontend_rebuilt', 'presentation_verified')}))
    return 0 if report['result'] == 'signed_not_run' else 1


if __name__ == '__main__':
    sys.exit(main())
