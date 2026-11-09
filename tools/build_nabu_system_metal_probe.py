#!/usr/bin/env python3
"""Build the thin Metal discovery bundle, mount helper and standard-factory probe.

Reuse the frontend, Turnip and metallib qualified in run 167. No Rust, Mesa or
frontend source is rebuilt, and no device or system file is modified here.
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

from build_nabu_gpu_vulkan_probe import TARGET, ENTITLEMENTS, macho_target, sign

ROOT = Path(__file__).resolve().parents[1]
QUALIFIED_RUN = '42590211952'
MOUNT_ENTITLEMENTS = {'com.apple.private.bindfs-allow': True}


def sign_mount_helper(path, run):
    # bindfs grants PID 1 an exception; a launchd root job needs this exact key.
    entitlements = path.parent / 'mount-entitlements.plist'
    entitlements.write_bytes(plistlib.dumps(MOUNT_ENTITLEMENTS))
    identifier = 'org.nabu16.metal-plugin-mount'
    run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
         '--identifier', identifier, '--entitlements', entitlements, path])
    run(['codesign', '--verify', '--strict', path])
    detail = run(['codesign', '--display', '--verbose=4', path]).stderr
    match = re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)
    if not match or not re.search(r'^Page size=4096$', detail, re.M):
        raise ValueError(path.name + ' lacks the required CDHash or 4 KiB signature pages')
    signed = plistlib.loads(run(['codesign', '--display', '--xml', '--entitlements', '-', path]).stdout.encode())
    if signed != MOUNT_ENTITLEMENTS or signed['com.apple.private.bindfs-allow'] is not True:
        raise ValueError('Signed mount helper must carry only boolean bindfs-allow=true')
    return {'file': path.name, 'bytes': path.stat().st_size, 'cdhash': match[1],
            'identifier': identifier, 'signature_page_bytes': 4096, 'entitlements': signed}


def jobs():
    mount = {'Label': 'org.nabu.metal-plugin-mount',
             'ProgramArguments': ['/redwood/sbin/nabu-metal-plugin-mount', '--mount'],
             'UserName': 'root', 'RunAtLoad': True, 'LaunchOnlyOnce': True, 'Umask': 0o022,
             'StandardOutPath': '/var/mobile/Media/nabu-system-metal-mount.stdout.log',
             'StandardErrorPath': '/var/mobile/Media/nabu-system-metal-mount.stderr.log'}
    probe = {'Label': 'org.nabu.system-metal-probe',
             'ProgramArguments': ['/redwood/sbin/nabu-gpu-metal-probe', '--run-system-metal'],
             'UserName': 'mobile', 'GroupName': 'mobile', 'LaunchOnlyOnce': True, 'Umask': 0o022,
             'LaunchEvents': {'com.apple.iokit.matching': {'org.nabu.system-metal-probe': {
                 'IOProviderClass': 'AGXAccelerator', 'IOMatchLaunchStream': True}}},
             'StandardOutPath': '/var/mobile/Media/nabu-system-metal-probe.stdout.log',
             'StandardErrorPath': '/var/mobile/Media/nabu-system-metal-probe.stderr.log'}
    return mount, probe


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Run 167 qualified Metal artifact directory')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Apple userspace builds run in macOS GitHub Actions')
    source, output = args.input.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'result': 'building', 'target': TARGET, 'reused_ci_run': QUALIFIED_RUN,
              'reused_device_qualification': 167, 'mtl_device_instance_bytes': 528,
              'factory': 'MTLCreateSystemDefaultDevice', 'accelerator_class': 'AGXAccelerator',
              'properties': {'MetalPluginName': 'NativeAdrenoMetal', 'MetalPluginClassName': 'NativeAdrenoMetalDevice'},
              'allowed_process_basename': 'nabu-gpu-metal-probe',
              'turnip_service': 'NativeAdrenoGpuPublished', 'turnip_open_type': 0x4147,
              'rust_rebuilt': False, 'frontend_rebuilt': False, 'turnip_rebuilt': False,
              'scanout_enabled': False, 'quartzcore_address_hooks': False, 'a740_replay': False,
              'runtime_qualified': False, 'gpu_exercised': False,
              'ci': {'run_id': os.environ.get('GITHUB_RUN_ID'), 'head_sha': os.environ.get('GITHUB_SHA')},
              'commands': []}

    def run(command, **kwargs):
        command = list(map(str, command))
        report['commands'].append(command)
        print('+ ' + ' '.join(command), flush=True)
        result = subprocess.run(command, capture_output=True, text=True, **kwargs)
        log = output / ('command-%02d.log' % len(report['commands']))
        log.write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Command failed; see ' + str(log) + '\n' + (result.stderr or result.stdout)[-3500:])
        return result

    try:
        prior = json.loads((source / 'build-report.json').read_text(encoding='utf-8'))
        if prior['ci']['run_id'] != QUALIFIED_RUN or prior['target'] != TARGET or prior['result'] != 'signed_not_run':
            raise ValueError('Expected the exact frontend artifact qualified in run 167')
        for key in ('frontend', 'turnip'):
            item = prior[key]
            library = source / item['file']
            macho_target(library, 6)
            run(['codesign', '--verify', '--strict', library])
            detail = run(['codesign', '--display', '--verbose=4', library]).stderr
            if re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)[1] != item['cdhash']:
                raise ValueError('Input library CDHash differs: ' + key)
            shutil.copyfile(library, output / library.name)
            report[key] = {**item, 'copied_without_resigning': True}
        metallib = source / prior['metallib']['file']
        shutil.copyfile(metallib, output / metallib.name)
        shutil.copyfile(source / 'build-report.json', output / 'qualified-metal-input-report.json')
        report['metallib'] = {**prior['metallib'], 'copied_without_recompiling': True}
        report['success_criteria'] = prior['success_criteria']
        report['runtime_outputs'] = prior['runtime_outputs']
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        base = ['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', TARGET, '-isysroot', sdk,
                '-std=c++17', '-O2', '-g', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                '-Wno-deprecated-declarations', '-fstack-protector-strong']
        probe = output / 'nabu-gpu-metal-probe'
        run([*base, '-DNABU_EXPECTED_MTL_DEVICE_BYTES=528', '-I', ROOT / 'src/nabu/gpu/upstream/Adreno6xx',
             ROOT / 'userland/nabu/src/gpu_metal_probe.mm', '-L', output, '-lnabu-metal-frontend',
             '-Wl,-rpath,@executable_path', '-framework', 'Foundation', '-framework', 'Metal', '-o', probe])
        entitlements = output / 'entitlements.plist'
        entitlements.write_bytes(plistlib.dumps(ENTITLEMENTS))
        report['probe'] = sign(probe, 'org.nabu16.gpu-metal-probe', run, entitlements)
        macho_target(probe, 2)
        bundle = output / 'NativeAdrenoMetal.bundle'
        bundle.mkdir()
        bundle_exe = bundle / 'NativeAdrenoMetal'
        run([*base, '-bundle', ROOT / 'userland/nabu/src/gpu_metal_factory.mm', '-Wl,-dead_strip',
             '-framework', 'Foundation', '-framework', 'Metal', '-o', bundle_exe])
        (bundle / 'Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'org.nabu16.NativeAdrenoMetal', 'CFBundleExecutable': 'NativeAdrenoMetal',
            'CFBundlePackageType': 'BNDL', 'CFBundleVersion': '1', 'CFBundleShortVersionString': '1',
            'NSPrincipalClass': 'NativeAdrenoMetalDevice', 'MinimumOSVersion': '16.5'}))
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
             '--identifier', 'org.nabu16.NativeAdrenoMetal', bundle])
        run(['codesign', '--verify', '--strict', bundle])
        detail = run(['codesign', '--display', '--verbose=4', bundle]).stderr
        if not re.search(r'^Page size=4096$', detail, re.M):
            raise ValueError('Bundle signature must use 4 KiB pages')
        macho_target(bundle_exe, 8)
        report['bundle'] = {'path': bundle.name, 'executable_bytes': bundle_exe.stat().st_size,
                            'cdhash': re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)[1],
                            'signature_page_bytes': 4096,
                            'dependencies': run(['otool', '-L', bundle_exe]).stdout.strip(),
                            'frontend_loaded_only_after_process_allowlist': True}
        helper = output / 'nabu-metal-plugin-mount'
        run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', TARGET, '-isysroot', sdk, '-std=c11',
             '-O2', '-Wall', '-Wextra', '-Werror', '-fstack-protector-strong',
             ROOT / 'userland/nabu/src/gpu_metal_mount.c', '-o', helper])
        report['mount_helper'] = sign_mount_helper(helper, run)
        macho_target(helper, 2)
        jobs_path = output / 'LaunchDaemons'
        jobs_path.mkdir()
        for job in jobs():
            (jobs_path / (job['Label'] + '.plist')).write_bytes(plistlib.dumps(job, fmt=plistlib.FMT_BINARY))
        report['deployment'] = {
            'sbin_files': ['nabu-gpu-metal-probe', 'nabu-metal-plugin-mount', 'libnabu-metal-frontend.dylib',
                           'libvulkan_freedreno.dylib', 'nabu-metal-smoke.metallib'],
            'sbin_directory': '/redwood/sbin',
            'bundle_source': '/redwood/metal-addons/NativeAdrenoMetal.bundle',
            'bundle_discovery': '/System/Library/Extensions/NativeAdrenoMetal.bundle',
            'mount': 'bindfs, MNT_RDONLY | MNT_UNION; existing AGXMetalA10.bundle must remain visible',
            'mount_gate': {'file': '/var/run/nabu-system-metal.ready', 'owner': 'root', 'mode': '0644',
                           'atomic_publish_after_all_checks': True, 'identity': 'current kern.boottime',
                           'probe_wait_seconds': 30},
            'permissions': {'directories': 'root:wheel 0755', 'bundle_executable': 'root:wheel 0755',
                            'plist_and_signature_resources': 'root:wheel 0644'},
            'jobs': list(jobs()), 'replace_previous_trial_job': True,
            'factory_call_requires': ['runtime _MTLDevice size 528', 'NativeAdreno ABI/chip preflight',
                                      'root mount readiness for the current boot',
                                      'AGXAccelerator and exact plugin properties', 'mounted bundle files readable']}
        report['result'] = 'signed_not_run'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(result='failed', error=str(error))
        print(str(error), file=sys.stderr)
    finally:
        (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('result', 'target', 'rust_rebuilt', 'runtime_qualified')}))
    return 0 if report['result'] == 'signed_not_run' else 1


if __name__ == '__main__':
    sys.exit(main())
