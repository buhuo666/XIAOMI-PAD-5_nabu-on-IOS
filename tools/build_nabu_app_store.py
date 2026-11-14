#!/usr/bin/env python3
"""Build the Nabu store apps. 'compile' works on Linux; signed IPAs need macOS."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import zipfile
from build_nabu_gpu_vulkan_probe import macho_target

ROOT = Path(__file__).resolve().parents[1]


def zip_app(app, target):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob('*')):
            if not path.is_file():
                continue
            entry = zipfile.ZipInfo('Payload/'+app.name+'/'+path.relative_to(app).as_posix())
            entry.create_system = 3
            entry.external_attr = (0o100000 | (0o755 if os.access(path, os.X_OK) else 0o644)) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['compile', 'all'], default='all')
    args = parser.parse_args()
    sources = args.sources.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    config = json.loads((ROOT/'configs/nabu-app-store.json').read_text())
    report = {'result': 'building', 'revision': config['revision'], 'target': config['target'],
              'commands': [], 'apps': [], 'device_executed': False, 'ipa_ready': False}

    def run(command, cwd=None):
        command = [str(x) for x in command]
        index = len(report['commands'])+1
        report['commands'].append(command)
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
        (output/f'command-{index:03d}.log').write_text(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError(f'Command {index} failed ({result.returncode}):\n'+(result.stdout+result.stderr)[-7000:])
        return result

    def sign(path, identifier, entitlements=None):
        command = ['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096', '--identifier', identifier]
        if entitlements:
            command += ['--entitlements', entitlements]
        run([*command, path])
        run(['codesign', '--verify', '--strict', path])
        if entitlements:
            signed = run(['codesign', '--display', '--entitlements', '-', '--xml', path])
            actual = plistlib.loads(signed.stdout.encode())
            if actual != plistlib.loads(Path(entitlements).read_bytes()):
                raise ValueError(f'Signed entitlements differ: {path}')

    try:
        if args.mode == 'all' and sys.platform != 'darwin':
            raise RuntimeError('Full TrollApps SwiftUI build requires macOS/Xcode; use --mode compile for the local arm64 checks')
        sdk = sources/'SDK'/config['sdk']['directory']
        store = sources/'TrollStore'
        compiler = ['xcrun', '--sdk', 'iphoneos', 'clang'] if sys.platform == 'darwin' else ['clang-18']
        includes = [sources/'Common', sources/'Headers', sources/'ArchiveHeaders', store/'Shared',
                    store/'ChOma/src', store/'Exploits/fastPathSign/src']
        base = [*compiler, '-target', config['target'], '-isysroot', sdk, '-Os', '-fblocks', '-fmodules',
                '-fmodules-cache-path='+str(output/'module-cache'), '-DNABU_APP_STORE=1',
                '-DTROLLSTORE_LITE=1', '-DDISABLE_SIGNING=1', '-Wno-deprecated-declarations']
        for directory in includes:
            base += ['-I', directory]
        base += ['-F', sdk/'System/Library/PrivateFrameworks']
        frameworks = ['Foundation', 'CoreFoundation', 'UIKit', 'CoreGraphics', 'CoreServices',
                      'CoreTelephony', 'Security', 'Preferences', 'MobileIcons', 'MobileContainerManager',
                      'SpringBoardServices', 'BackBoardServices', 'FrontBoardServices',
                      'RunningBoardServices', 'UniformTypeIdentifiers']

        def executable(name, files):
            print(f'Compiling {name}: {len(files)} translation units', flush=True)
            objdir = output/'objects'/name
            objdir.mkdir(parents=True)
            objects = []
            for number, source in enumerate(files):
                obj = objdir/f'{number:02d}-{source.stem}.o'
                run([*base, *(['-fobjc-arc'] if source.suffix == '.m' else []), '-c', source, '-o', obj])
                objects.append(obj)
            binary = output/name
            if sys.platform == 'darwin':
                command = [*compiler, '-target', config['target'], '-isysroot', sdk,
                           '-F', sdk/'System/Library/PrivateFrameworks', '-Wl,-dead_strip', *objects,
                           '-larchive.2', '-o', binary]
            else:
                command = ['ld64.lld-18', '-arch', 'arm64', '-platform_version', 'ios', '16.5', '16.5',
                           '-syslibroot', sdk, '-F', sdk/'System/Library/PrivateFrameworks',
                           '-dead_strip', '-adhoc_codesign', *objects, '-lSystem', '-lobjc', '-larchive.2', '-o', binary]
            for framework in frameworks:
                command += ['-framework', framework]
            run(command)
            macho_target(binary, 2)
            return binary

        shared = sorted((store/'Shared').glob('*.m'))
        helper = executable('trollstorehelper', sorted((store/'RootHelper').glob('*.m'))+shared+sorted((store/'ChOma/src').glob('*.c')))
        main_binary = executable('TrollStoreLite', sorted((store/'TrollStore').glob('*.m'))+shared)

        # Compile the real Objective-C bridge used by TrollApps with the same SDK.
        bridge = sources/'TrollApps/TrollApps/TrollApps/Objective C/TSUtil.m'
        run([*base, '-fobjc-arc', '-c', bridge, '-o', output/'TrollApps-TSUtil.o'])
        report['local_arm64'] = {'lite_linked': True, 'root_helper_linked': True, 'trollapps_objc_bridge_compiled': True}
        if args.mode == 'compile':
            report['result'] = 'arm64-linked-not-packaged'
            return

        print('Signing and packaging TrollStore Lite', flush=True)
        app = output/'Payload/TrollStoreLite.app'
        shutil.copytree(store/'TrollStoreLite/Resources', app)
        shutil.copy2(main_binary, app/'TrollStoreLite')
        shutil.copy2(helper, app/'trollstorehelper')
        shutil.copy2(sources/'ldid', app/'ldid')
        (app/'ldid.version').write_text(config['ldid_version'])
        for name in ('TrollStoreLite', 'trollstorehelper', 'ldid'):
            (app/name).chmod(0o755)
        sign(app/'trollstorehelper', 'com.opa334.TrollStoreLite.helper', store/'RootHelper/entitlements.plist')
        # Keep the already reviewed official ldid byte-for-byte.
        sign(app, config['apps'][0]['bundle_id'], store/'TrollStoreLite/entitlements.plist')
        zip_app(app, output/config['apps'][0]['ipa'])
        report['apps'].append(config['apps'][0])

        print('Building TrollApps SwiftUI application', flush=True)
        apps_root = sources/'TrollApps/TrollApps'
        derived = output/'TrollAppsDerived'
        run(['xcodebuild', '-project', apps_root/'TrollApps.xcodeproj', '-scheme', 'TrollApps',
             '-configuration', 'Release', '-derivedDataPath', derived, '-destination', 'generic/platform=iOS',
             'build', 'ARCHS=arm64', 'ONLY_ACTIVE_ARCH=YES', 'IPHONEOS_DEPLOYMENT_TARGET=16.5',
             'CODE_SIGNING_ALLOWED=NO', 'CODE_SIGNING_REQUIRED=NO', 'CODE_SIGN_IDENTITY=',
             'DEVELOPMENT_TEAM=', 'HEADER_SEARCH_PATHS='+str(sources/'Common'),
             'CURRENT_PROJECT_VERSION='+config['apps'][1]['build']])
        apps_bundle = output/'Payload/TrollApps.app'
        shutil.copytree(derived/'Build/Products/Release-iphoneos/TrollApps.app', apps_bundle)
        macho_target(apps_bundle/'TrollApps', 2)
        info_path = apps_bundle/'Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info['NabuStoreRevision'] = config['revision']
        info_path.write_bytes(plistlib.dumps(info, fmt=plistlib.FMT_BINARY))
        for framework in sorted((apps_bundle/'Frameworks').glob('*.framework')):
            sign(framework, framework.stem)
        for dylib in sorted((apps_bundle/'Frameworks').glob('*.dylib')):
            sign(dylib, dylib.stem)
        sign(apps_bundle, config['apps'][1]['bundle_id'], apps_root/'entitlements.plist')
        zip_app(apps_bundle, output/config['apps'][1]['ipa'])
        report['apps'].append(config['apps'][1])
        report.update(result='signed-not-run', ipa_ready=True)
    except Exception as error:
        report.update(result='failed', error=str(error))
        raise
    finally:
        (output/'build-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
        print(json.dumps({k: report[k] for k in ('result', 'ipa_ready', 'device_executed')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
