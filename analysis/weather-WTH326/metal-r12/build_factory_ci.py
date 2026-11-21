"""Run actual Foundation exception checks and build the observed iOS factory."""
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
INPUT = HERE / 'factory-ci-input'
ROOT = HERE.parents[2]
OUT = ROOT / 'artifacts/nabu-metal-factory-WTH326-r12'


def main():
    if sys.platform != 'darwin':
        raise SystemExit('The Foundation runtime and codesign check run on macOS Actions.')
    OUT.mkdir(parents=True, exist_ok=False)
    report = dict(result='building', ci=dict(run_id=os.environ.get('GITHUB_RUN_ID'),
        head_sha=os.environ.get('GITHUB_SHA')), device_executed=False,
        input=json.loads((INPUT / 'input-manifest.json').read_text()), commands=[],
        original_signal_diagnostics_retained=True, application_specific_behavior=False)

    def save():
        (OUT / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(command, label, env=None, allow_failure=False):
        command = list(map(str, command))
        report['commands'].append(command)
        save()
        result = subprocess.run(command, capture_output=True, text=True, env=env,
            timeout=60 if label.endswith('-runtime') else None)
        (OUT / (label + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode and not allow_failure:
            report.update(result='failed', failed_phase=label, returncode=result.returncode)
            save()
            raise RuntimeError((result.stdout + result.stderr)[-6000:])
        return result

    xcode = run(['xcodebuild', '-version'], 'xcode').stdout.strip()
    assert xcode.startswith('Xcode 16.4\n')
    report['xcode'] = xcode
    sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], 'sdk').stdout.strip()
    report['sdk'] = sdk
    tests = []
    for name in ('exception_handler_test', 'exception_dispatch_test'):
        binary = OUT / name
        run(['xcrun', '--sdk', 'macosx', 'clang++', '-std=c++17', '-O2', '-g', '-fobjc-arc',
             '-Wall', '-Wextra', '-Werror', '-I', INPUT, INPUT / (name + '.mm'),
             '-framework', 'Foundation', '-o', binary], name + '-compile')
        if name == 'exception_dispatch_test':
            for case in ('objc', 'cpp'):
                result = run([binary], name + '-' + case + '-runtime',
                    env=dict(os.environ, NABU_EXCEPTION_DEBUG_CASE=case), allow_failure=True)
                tests.append(dict(name=name + '-' + case, result='passed' if result.returncode == 0 else 'failed',
                    returncode=result.returncode, scope='macOS real dispatch baseline/instrumented fatal handling'))
        else:
            result = run([binary], name + '-runtime')
            assert 'PASS:' in result.stdout
            tests.append(dict(name=name, result='passed', scope='macOS Foundation execution'))
    report['exception_tests'] = tests
    if any(test['result'] != 'passed' for test in tests):
        report.update(result='failed', failed_phase='exception_dispatch_test-runtime')
        save()
        raise RuntimeError('Actual dispatch child checks failed; both case logs retained.')
    target = 'arm64-apple-ios16.5'
    fault = OUT / 'gpu-metal-fault-trace.o'
    run(['xcrun', '--sdk', 'iphoneos', 'clang', '-target', target, '-isysroot', sdk, '-std=c11',
         '-O2', '-g', '-Wall', '-Wextra', '-Werror', '-c', INPUT / 'gpu_metal_fault_trace.c',
         '-o', fault], 'fault-compile')
    bundle = OUT / 'NativeAdrenoMetal.bundle'
    bundle.mkdir()
    binary = bundle / 'NativeAdrenoMetal'
    run(['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', target, '-isysroot', sdk,
         '-std=c++17', '-O2', '-g', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
         '-Wno-deprecated-declarations', '-fstack-protector-strong', '-I', INPUT,
         '-DNABU_METAL_SYSTEM_CLIENTS=1', '-DNABU_METAL_BACKBOARD_FAULT_DIAGNOSTICS=1',
         fault, '-bundle', INPUT / 'gpu_metal_factory.mm', '-Wl,-dead_strip',
         '-framework', 'Foundation', '-framework', 'Metal', '-o', binary], 'factory-link')
    shutil.copyfile(INPUT / 'Info.plist', bundle / 'Info.plist')
    run(['xcrun', 'dsymutil', binary, '-o', bundle / 'NativeAdrenoMetal.dSYM'], 'factory-dsym')
    symbols = run(['nm', '-an', binary], 'factory-symbols').stdout
    assert '-[NativeAdrenoMetalDevice initWithAcceleratorPort:]' in symbols
    assert b'native_bridge_metal_start_problem_reporting' in binary.read_bytes()
    info = plistlib.loads((bundle / 'Info.plist').read_bytes())
    run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
         '--identifier', info['CFBundleIdentifier'], bundle], 'factory-sign')
    run(['codesign', '--verify', '--strict', bundle], 'factory-verify')
    detail = run(['codesign', '--display', '--verbose=4', bundle], 'factory-signature').stderr
    assert re.search(r'^Page size=4096$', detail, re.M)
    data = binary.read_bytes()
    assert struct.unpack_from('<I', data)[0] == 0xfeedfacf
    assert struct.unpack_from('<I', data, 4)[0] == 0x100000c
    assert struct.unpack_from('<I', data, 12)[0] == 8
    report.update(result='signed_not_run', target=target, bundle=dict(path=bundle.name,
        executable_bytes=len(data), signature_page_bytes=4096, strict_codesign_verified=True,
        cdhash=re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)[1],
        new_global_diagnostics_entry_present=True))
    save()
    print(json.dumps(dict(result=report['result'], exception_tests=tests,
        factory_bytes=len(data), device_executed=False)))


if __name__ == '__main__':
    main()
