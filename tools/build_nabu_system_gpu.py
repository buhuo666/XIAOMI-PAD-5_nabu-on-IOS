#!/usr/bin/env python3
"""Build system Metal discovery and a startup gate, reusing the run172 GPU runtime."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys

from build_nabu_gpu_vulkan_probe import TARGET, macho_target, sign

ROOT = Path(__file__).resolve().parents[1]
QUALIFIED_RUN = '42615860281'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--backboard-fault-diagnostics', action='store_true',
                        help='Record the observed backboardd SIGSEGV context before default termination')
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Apple userspace compilation runs in macOS GitHub Actions')
    source, output = args.input.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = dict(result='building', target=TARGET, test_revision=177,
        reused_ci_run=QUALIFIED_RUN, reused_device_qualification=172,
        frontend_rebuilt=False, turnip_rebuilt=False, mount_helper_rebuilt=False,
        system_clients_enabled=True, cache='NSCachesDirectory/NativeAdrenoMetal/<process>',
        graphics_start_gate=['com.apple.backboardd', 'com.apple.SpringBoard'],
        gate_loads_metal=False, gate_timeout_seconds=180, gpu_boot_delay_seconds=0,
        gpu_exercised=False, system_runtime_verified=False,
        backboard_fault_diagnostics=args.backboard_fault_diagnostics,
        ci=dict(run_id=os.environ.get('GITHUB_RUN_ID'), head_sha=os.environ.get('GITHUB_SHA')),
        commands=[])

    def run(command):
        command = list(map(str, command))
        report['commands'].append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        (output / ('command-%02d.log' % len(report['commands']))).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-4000:])
        return result

    try:
        prior = json.loads((source / 'build-report.json').read_text())
        if prior['ci']['run_id'] != QUALIFIED_RUN or prior['result'] != 'signed_not_run' or prior['mtl_device_instance_bytes'] != 528:
            raise ValueError('Expected run172 qualified frontend')
        for key in ('frontend', 'turnip', 'mount_helper'):
            item = prior[key]
            shutil.copyfile(source / item['file'], output / item['file'])
            report[key] = {**item, 'copied_without_rebuilding': True}
        shutil.copyfile(source / 'build-report.json', output / 'qualified-runtime-input-report.json')
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        xcode = run(['xcodebuild', '-version']).stdout.strip()
        if not xcode.startswith('Xcode 16.4\n'):
            raise ValueError('Expected Xcode 16.4')
        report['xcode'] = xcode
        base = ['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', TARGET, '-isysroot', sdk,
                '-std=c++17', '-O2', '-g', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                '-Wno-deprecated-declarations', '-fstack-protector-strong']
        bundle = output / 'NativeAdrenoMetal.bundle'
        bundle.mkdir()
        binary = bundle / 'NativeAdrenoMetal'
        diagnostics = []
        if args.backboard_fault_diagnostics:
            trace = ROOT / 'userland/nabu/src/gpu_metal_fault_trace.c'
            test = output / 'fault-trace-host-test'
            run(['xcrun', '--sdk', 'macosx', 'clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                 '-O1', trace, ROOT / 'userland/nabu/tests/gpu_metal_fault_trace_test.c', '-o', test])
            run([test])
            obj = output / 'gpu-metal-fault-trace.o'
            run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', TARGET, '-isysroot', sdk,
                 '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-c', trace, '-o', obj])
            diagnostics = ['-DNABU_METAL_BACKBOARD_FAULT_DIAGNOSTICS=1', obj]
            report.update(test_revision=179, fault_trace_host_test_passed=True,
                          fault_trace_scope='backboardd SIGSEGV; original termination preserved')
        run([*base, '-DNABU_METAL_SYSTEM_CLIENTS=1', *diagnostics, '-bundle',
             ROOT / 'userland/nabu/src/gpu_metal_factory.mm', '-Wl,-dead_strip',
             '-framework', 'Foundation', '-framework', 'Metal', '-o', binary])
        info = plistlib.loads((source / 'NativeAdrenoMetal.bundle/Info.plist').read_bytes())
        version = '3' if args.backboard_fault_diagnostics else '2'
        info.update(CFBundleVersion=version, CFBundleShortVersionString=version)
        (bundle / 'Info.plist').write_bytes(plistlib.dumps(info))
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
             '--identifier', info['CFBundleIdentifier'], bundle])
        run(['codesign', '--verify', '--strict', bundle])
        detail = run(['codesign', '--display', '--verbose=4', bundle]).stderr
        if not re.search(r'^Page size=4096$', detail, re.M):
            raise ValueError('Factory signature page size differs')
        macho_target(binary, 8)
        report['bundle'] = dict(path=bundle.name, executable_bytes=binary.stat().st_size,
            cdhash=re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)[1], signature_page_bytes=4096,
            dependencies=run(['otool', '-L', binary]).stdout.strip(), process_name_restriction=False)
        gate = output / 'nabu-metal-wait-exec'
        run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', TARGET, '-isysroot', sdk, '-std=c11',
             '-O2', '-Wall', '-Wextra', '-Werror', '-fstack-protector-strong',
             ROOT / 'userland/nabu/src/gpu_metal_wait_exec.c', '-framework', 'CoreFoundation', '-o', gate])
        report['gate'] = sign(gate, 'org.nabu16.metal-wait-exec', run)
        macho_target(gate, 2)
        report['gate']['dependencies'] = run(['otool', '-L', gate]).stdout.strip()
        if '/Metal.framework/' in report['gate']['dependencies'] or 'libnabu' in report['gate']['dependencies']:
            raise ValueError('Startup gate must not initialize Metal')
        jobs = output / 'LaunchDaemons'
        jobs.mkdir()
        shutil.copyfile(source / 'LaunchDaemons/org.nabu.metal-plugin-mount.plist',
                        jobs / 'org.nabu.metal-plugin-mount.plist')
        report['result'] = 'signed_not_run'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report.update(result='failed', error=str(error))
        print(str(error), file=sys.stderr)
    finally:
        (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: report[k] for k in ('result', 'system_clients_enabled', 'system_runtime_verified')}))
    return 0 if report['result'] == 'signed_not_run' else 1


if __name__ == '__main__':
    sys.exit(main())
