#!/usr/bin/env python3
"""Build iOS 16.5 Turnip and a signed standalone A640 Vulkan probe on macOS CI.

Use the pinned Mesa producer and smoke shaders in project-owned staging. This
does not build a Metal frontend, install files, dispatch CI or access a device.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'arm64-apple-ios16.5'
ENTITLEMENTS = {
    'com.apple.private.security.no-container': True,
    'com.apple.security.iokit-user-client-class': ['AGXDeviceUserClient'],
    'com.apple.security.ts.opengl-or-metal': True,
}
SHADERS = ('smoke_fill.comp', 'smoke_triangle.vert', 'smoke_triangle.frag')


def stage_turnip(reference, device, work):
    """Adapt only the copied build script; keep all pinned checkouts unchanged."""
    work.mkdir(parents=True, exist_ok=False)
    (work / '.cache').mkdir()
    pins_file = Path('scripts/data/adreno-compiler-inputs.json')
    pins = json.loads((reference / pins_file).read_text(encoding='utf-8'))
    for name in ['scripts/build-turnip-darwin.py', 'scripts/mesa_patch_identity.py', *pins['patches']]:
        target = work / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(reference / name, target)
    nabu_patch = 'patches/mesa/mesa-turnip-a640-trace-guard.patch'
    shutil.copyfile(device / 'patches/mesa-turnip-a640-trace-guard.patch', work / nabu_patch)
    pins['patches'].append(nabu_patch)
    (work / pins_file).parent.mkdir(parents=True, exist_ok=True)
    (work / pins_file).write_text(json.dumps(pins, indent=2) + '\n', encoding='utf-8')
    script = work / 'scripts/build-turnip-darwin.py'
    original = script.read_text(encoding='utf-8')
    if original.count("'arm64-apple-ios17.0'") != 1:
        raise ValueError('Turnip build target changed; update the iOS 16.5 adaptation')
    script.write_text(original.replace("'arm64-apple-ios17.0'", repr(TARGET)), encoding='utf-8')
    return pins


def generate_shaders(smoke, generated, run):
    generated.mkdir(parents=True, exist_ok=True)
    lines = ['// Generated GLSL compiler output.', '#pragma once', '#include <stdint.h>']
    for name in SHADERS:
        binary = generated / (name + '.spv')
        run(['glslangValidator', '-V', '--target-env', 'vulkan1.1', smoke / 'shaders' / name, '-o', binary])
        if shutil.which('spirv-val'):
            run(['spirv-val', '--target-env', 'vulkan1.1', binary])
        data = binary.read_bytes()
        words = struct.unpack('<%dI' % (len(data) // 4), data)
        lines.append('static const uint32_t kSpv_%s[] = {' % name.replace('.', '_'))
        lines += ['    ' + ', '.join('0x%08x' % word for word in words[i:i + 8]) + ','
                  for i in range(0, len(words), 8)]
        lines.append('};')
    (generated / 'NativeTurnipShaders.h').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def macho_target(path, file_type):
    """Confirm the produced ARM64 Mach-O has the required deployment target."""
    data = path.read_bytes()
    if struct.unpack_from('<4I', data) != (0xfeedfacf, 0x100000c, 0, file_type):
        raise ValueError(path.name + ' is not the expected ARM64 Mach-O type')
    commands, extent = struct.unpack_from('<II', data, 16)
    cursor = 32
    minimum = None
    for _ in range(commands):
        kind, size = struct.unpack_from('<II', data, cursor)
        if kind == 0x32:
            platform, minimum = struct.unpack_from('<II', data, cursor + 8)
            if platform != 2:
                raise ValueError(path.name + ' is not an iOS image')
        cursor += size
    if cursor != 32 + extent or minimum != 0x100500:
        raise ValueError(path.name + ' must declare iOS 16.5 as its minimum')


def sign(path, identifier, run, entitlements=None):
    command = ['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
               '--identifier', identifier]
    if entitlements:
        command += ['--entitlements', entitlements]
    run([*command, path])
    run(['codesign', '--verify', '--strict', path])
    detail = run(['codesign', '--display', '--verbose=4', path]).stderr
    match = re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)
    if not match or not re.search(r'^Page size=4096$', detail, re.M):
        raise ValueError(path.name + ' lacks the required CDHash or 4 KiB signature pages')
    if entitlements:
        signed = run(['codesign', '--display', '--xml', '--entitlements', '-', path]).stdout
        if plistlib.loads(signed.encode()) != ENTITLEMENTS:
            raise ValueError('Signed Vulkan probe entitlements differ')
    return {'file': path.name, 'bytes': path.stat().st_size, 'cdhash': match[1],
            'identifier': identifier, 'signature_page_bytes': 4096}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True, help='New project-owned staging directory')
    parser.add_argument('--output', type=Path, required=True, help='New artifact directory')
    parser.add_argument('--reference', type=Path, default=ROOT / 'src/unixnu-turnip')
    parser.add_argument('--device', type=Path, default=ROOT / 'src/nabu')
    parser.add_argument('--smoke', type=Path, default=ROOT / 'src/AdrenoMetal')
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Apple GPU builds run in macOS GitHub Actions')
    work, output = args.work.resolve(), args.output.resolve()
    reference, device, smoke = args.reference.resolve(), args.device.resolve(), args.smoke.resolve()
    output.mkdir(parents=True, exist_ok=False)
    abi = device / 'gpu/upstream/Adreno6xx'
    source = ROOT / 'userland/nabu/src/gpu_vulkan_probe.cpp'
    selected = {'nabu', 'UniXNU-turnip-reference', 'AdrenoMetal'}
    lock = json.loads((ROOT / 'configs/sources.lock.json').read_text(encoding='utf-8'))
    report = {
        'result': 'building', 'target': TARGET, 'service': 'NativeAdrenoGpuPublished', 'open_type': 0x4147,
        'source_commits': {item['name']: item['commit'] for item in lock['sources'] if item['name'] in selected},
        'probe_source': str(source.relative_to(ROOT)), 'entitlements': ENTITLEMENTS,
        'runtime_command': './nabu-gpu-vulkan-probe --run-vulkan',
        'success_criteria': {'fill_words': 1024, 'compute_words': 1024,
                             'triangle_pixels_min': 480, 'triangle_pixels_max': 544, 'other_pixels': 0},
        'gpu_exercised': False, 'runtime_qualified': False, 'owner_trust_installed': False,
        'ci': {'run_id': os.environ.get('GITHUB_RUN_ID'), 'head_sha': os.environ.get('GITHUB_SHA')},
        'commands': [],
    }

    def run(command, **kwargs):
        command = list(map(str, command))
        report['commands'].append(command)
        print('+ ' + ' '.join(command), flush=True)
        result = subprocess.run(command, capture_output=True, text=True, **kwargs)
        log = output / ('command-%02d.log' % len(report['commands']))
        log.write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Command failed; see ' + str(log) + '\n' + (result.stderr or result.stdout)[-2500:])
        return result

    try:
        pins = stage_turnip(reference, device, work)
        report.update(mesa_commit=pins['mesa']['commit'], patches=pins['patches'],
                      staging_adaptation='arm64-apple-ios17.0 -> arm64-apple-ios16.5')
        # Reuse the pinned producer's Bison/Mesa setup without its iOS 17 userprobe or Metal build.
        spec = importlib.util.spec_from_file_location('nabu_turnip_ci', device / 'source-ci/nabu_turnip_ci.py')
        producer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(producer)
        run([sys.executable, '-m', 'venv', work / '.cache/mesa-venv'])
        run([work / '.cache/mesa-venv/bin/pip', 'install', '-q', *producer.PYTHON_PACKAGES])
        producer.bison(work, pins)
        producer.mesa(work, pins)
        # No builtin pack is used; existing downloaded sources do not need a new hash inventory.
        env = dict(os.environ, UNIXNU_RECORD_HASHES='0',
                   PATH=str(work / '.cache/mesa-tools/bin') + os.pathsep + os.environ['PATH'])
        run([sys.executable, work / 'scripts/build-turnip-darwin.py', '--target', 'ios',
             '--abi-directory', abi], cwd=work, env=env)
        library = work / 'build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib'
        macho_target(library, 6)
        symbols = output / 'symbols'
        symbols.mkdir()
        shutil.copyfile(library, symbols / library.name)
        runtime_library = output / library.name
        shutil.copyfile(library, runtime_library)
        run(['xcrun', '--sdk', 'iphoneos', 'strip', '-x', runtime_library])
        report['turnip'] = sign(runtime_library, 'org.nabu16.turnip-vulkan', run)
        macho_target(runtime_library, 6)
        report['turnip']['dependencies'] = run(['otool', '-L', runtime_library]).stdout.strip()
        generated = output / 'shaders'
        generate_shaders(smoke, generated, run)
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        executable = output / 'nabu-gpu-vulkan-probe'
        run(['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', TARGET, '-isysroot', sdk,
             '-std=c++17', '-O2', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
             '-fstack-protector-strong', '-DNATIVE_ADRENO_A740_REPLAY=0', '-DNATIVE_ADRENO_SCANOUT_COPY=0',
             '-DNATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE=0', '-I', abi, '-I', smoke,
             '-I', work / '.cache/mesa-work/include', '-I', generated, source,
             '-framework', 'CoreFoundation', '-o', executable])
        entitlement_file = output / 'entitlements.plist'
        entitlement_file.write_bytes(plistlib.dumps(ENTITLEMENTS))
        report['probe'] = sign(executable, 'org.nabu16.gpu-vulkan-probe', run, entitlement_file)
        macho_target(executable, 2)
        report['probe']['dependencies'] = run(['otool', '-L', executable]).stdout.strip()
        report['result'] = 'signed_not_run'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, SystemExit) as error:
        report.update(result='failed', error=str(error))
        print(str(error), file=sys.stderr)
    finally:
        for name in ('mesa-tu-ios-configure.log', 'mesa-tu-ios-build.log'):
            log = work / '.cache' / name
            if log.is_file():
                shutil.copyfile(log, output / name)
        profile = work / 'build/mesa-tu-ios/builtin-build-profile.json'
        if profile.is_file():
            shutil.copyfile(profile, output / profile.name)
        (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('result', 'target', 'gpu_exercised', 'runtime_qualified')}))
    return 0 if report['result'] == 'signed_not_run' else 1


if __name__ == '__main__':
    sys.exit(main())
