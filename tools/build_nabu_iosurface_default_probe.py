#!/usr/bin/env python3
"""Build only the default-allocation IOSurface probe against the run 170 frontend.

Reuse every native dependency, the metallib, factory bundle and mount helper from
CI42607114009. The runtime's existing copied-host-pages path remains measurable;
this build does not change import/cache policy or rebuild Rust, Mesa or shaders.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from build_nabu_gpu_vulkan_probe import TARGET, ENTITLEMENTS, macho_target, sign

ROOT = Path(__file__).resolve().parents[1]
QUALIFIED_RUN = '42607114009'
PROBE_LABEL = 'org.nabu.iosurface-default-probe'


def reuse_inputs(source, output, skip_payloads=()):
    """Copy qualified payloads and derive the two job plists; do not resign inputs."""
    prior = json.loads((source / 'build-report.json').read_text(encoding='utf-8'))
    if (prior['ci']['run_id'] != QUALIFIED_RUN or prior['result'] != 'signed_not_run'
            or prior['target'] != TARGET or prior['mtl_device_instance_bytes'] != 528):
        raise ValueError('Expected the exact IOSurface artifact qualified in run 170')
    copied = {}
    for key in ('frontend', 'turnip', 'metallib', 'mount_helper'):
        if key in skip_payloads:
            continue
        item = prior[key]
        shutil.copyfile(source / item['file'], output / item['file'])
        copied[key] = {**item, 'reused_from_ci': prior['ci'], 'copied_without_rebuilding': True}
        if key != 'metallib':
            copied[key]['copied_without_resigning'] = True
    bundle = prior['bundle']
    shutil.copytree(source / bundle['path'], output / bundle['path'])
    copied['bundle'] = {**bundle, 'reused_from_ci': prior['ci'],
                        'copied_without_rebuilding': True, 'copied_without_resigning': True}
    shutil.copyfile(source / 'build-report.json', output / 'qualified-iosurface-input-report.json')
    jobs = output / 'LaunchDaemons'
    jobs.mkdir()
    mount = plistlib.loads((source / 'LaunchDaemons/org.nabu.metal-plugin-mount.plist').read_bytes())
    mount.update(StandardOutPath='/var/mobile/Media/nabu-iosurface-default-mount.stdout.log',
                 StandardErrorPath='/var/mobile/Media/nabu-iosurface-default-mount.stderr.log')
    probe = plistlib.loads((source / 'LaunchDaemons/org.nabu.iosurface-probe.plist').read_bytes())
    probe.update(Label=PROBE_LABEL,
                 ProgramArguments=['/redwood/sbin/nabu-gpu-metal-probe', '--run-iosurface-default'],
                 StandardOutPath='/var/mobile/Media/nabu-iosurface-default-probe.stdout.log',
                 StandardErrorPath='/var/mobile/Media/nabu-iosurface-default-probe.stderr.log')
    matching = probe['LaunchEvents']['com.apple.iokit.matching']
    matching[PROBE_LABEL] = matching.pop('org.nabu.iosurface-probe')
    for job in (mount, probe):
        (jobs / (job['Label'] + '.plist')).write_bytes(plistlib.dumps(job, fmt=plistlib.FMT_BINARY))
    copied['deployment'] = {
        **prior['deployment'], 'jobs': ['org.nabu.metal-plugin-mount.plist', PROBE_LABEL + '.plist'],
        'replace_previous_trial_job': True, 'standard_factory_required': True,
        'runtime_command': probe['ProgramArguments'],
        'permissions': {'directories_and_executables': 'root:wheel 0755',
                        'plists_and_signature_resources': 'root:wheel 0644'},
    }
    return copied


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='CI42607114009 nabu-gpu-iosurface artifact directory')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Apple probe builds run in macOS GitHub Actions')
    source, output = args.input.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        'result': 'building', 'target': TARGET, 'mtl_device_instance_bytes': 528,
        'reused_ci_run': QUALIFIED_RUN, 'reused_device_qualification': 170,
        'construction': 'MTLCreateSystemDefaultDevice', 'allowed_process_basename': 'nabu-gpu-metal-probe',
        'allocation': 'IOSurfaceCreate default allocation; no IOSurfaceAddress wrapper',
        'turnip_service': 'NativeAdrenoGpuPublished', 'turnip_open_type': 0x4147,
        'rust_rebuilt': False, 'frontend_rebuilt': False, 'turnip_rebuilt': False,
        'metallib_rebuilt': False, 'factory_bundle_rebuilt': False, 'mount_helper_rebuilt': False,
        'cached_import_policy_modified': False, 'scanout_enabled': False,
        'quartzcore_address_hooks': False, 'a740_replay': False,
        'runtime_qualified': False, 'gpu_exercised': False,
        'runtime_outputs': {'result': '/var/mobile/Media/nabu-iosurface-default-result.json',
                            'pixels': '/var/mobile/Media/nabu-iosurface-default-readback.bgra',
                            'pixel_metadata': '/var/mobile/Media/nabu-iosurface-default-readback.json'},
        'success_criteria': {
            'epochs': 32, 'completed_command_buffers': 64,
            'pixel_errors': 0, 'padding_errors': 0, 'tail_errors': 0,
            'surface_imports_balanced_after_release': True, 'resources_released': True,
            'accepted_paths': {
                'zero_copy': {'shared_import': True, 'pointer_imports_delta': 1,
                              'pointer_import_bytes_equal_surface_alloc': True,
                              'copied_host_buffers_delta': 0, 'copied_refused_delta': 0,
                              'copied_degraded_delta': 0, 'copied_copy_in_bytes_delta': 0,
                              'copied_merge_back_bytes_delta': 0},
                'copied_compatibility': {'shared_import': False, 'direct_image_alias': False,
                                         'pointer_imports_delta': 0, 'pointer_import_bytes_delta': 0,
                                         'copied_host_buffers_delta': 1, 'copied_refused_delta': 0,
                                         'copied_degraded_delta': 1, 'copy_in_bytes_must_increase': True,
                                         'merge_back_bytes_must_increase': True},
            },
            'in_place_and_shadow_reported_separately': True,
        },
        'ci': {'run_id': os.environ.get('GITHUB_RUN_ID'), 'head_sha': os.environ.get('GITHUB_SHA')},
        'commands': [],
    }

    def run(command, **kwargs):
        command = list(map(str, command))
        report['commands'].append(command)
        print('+ ' + ' '.join(command), flush=True)
        result = subprocess.run(command, capture_output=True, text=True, **kwargs)
        (output / ('command-%02d.log' % len(report['commands']))).write_text(
            result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Command failed: ' + (result.stderr or result.stdout)[-3500:])
        return result

    try:
        report.update(reuse_inputs(source, output))
        xcode = run(['xcodebuild', '-version']).stdout.strip()
        if not xcode.startswith('Xcode 16.4\n'):
            raise ValueError('Use the qualified Xcode 16.4 probe compiler')
        report['xcode'] = xcode
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        probe_source = ROOT / 'userland/nabu/src/gpu_iosurface_default_probe.mm'
        probe = output / 'nabu-gpu-metal-probe'
        run(['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', TARGET, '-isysroot', sdk,
             '-std=c++17', '-O2', '-g', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
             '-Wno-deprecated-declarations', '-fstack-protector-strong',
             '-DNABU_EXPECTED_MTL_DEVICE_BYTES=528', '-I', ROOT / 'src/nabu/gpu/upstream/Adreno6xx',
             probe_source, '-L', output, '-lnabu-metal-frontend', '-Wl,-rpath,@executable_path',
             '-framework', 'Foundation', '-framework', 'Metal', '-framework', 'IOSurface', '-o', probe])
        entitlements = output / 'entitlements.plist'
        entitlements.write_bytes(plistlib.dumps(ENTITLEMENTS))
        report['probe'] = sign(probe, 'org.nabu16.gpu-metal-probe', run, entitlements)
        macho_target(probe, 2)
        report['probe'].update(source=str(probe_source.relative_to(ROOT)),
                               dependencies=run(['otool', '-L', probe]).stdout.strip(),
                               entitlements=ENTITLEMENTS)
        report['result'] = 'signed_not_run'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(result='failed', error=str(error))
        print(str(error), file=sys.stderr)
    finally:
        (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('result', 'target', 'frontend_rebuilt', 'runtime_qualified')}))
    return 0 if report['result'] == 'signed_not_run' else 1


if __name__ == '__main__':
    sys.exit(main())
