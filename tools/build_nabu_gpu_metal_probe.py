#!/usr/bin/env python3
"""Build a standalone iOS 16.5 Metal frontend and GPU readback probe on macOS CI.

The passed Turnip artifact is reused byte-for-byte. The pinned frontend/runtime
are staged locally; no system discovery plugin, scanout or daemon is built.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tomllib

from build_nabu_gpu_vulkan_probe import TARGET, ENTITLEMENTS, macho_target, sign

ROOT = Path(__file__).resolve().parents[1]
RUST = '1.98.1'
FRONTEND = 'libnabu-metal-frontend.dylib'
MTL_DEVICE_BYTES_20F66 = 528


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_once(path, old, new):
    source = path.read_text(encoding='utf-8')
    if source.count(old) != 1:
        raise ValueError('Update the recorded adaptation in ' + str(path) + ': ' + old)
    path.write_text(source.replace(old, new), encoding='utf-8')


def stage(root, work, instance_bytes, run):
    """Use nabu's relevant frontend patches and UniXNU's bridge build entry."""
    work.mkdir(parents=True, exist_ok=False)
    (work / '.cache').mkdir()
    source_pins = {item['name']: item for item in json.loads((root / 'configs/sources.lock.json').read_text(encoding='utf-8'))['sources']}
    metal = work / 'drivers/AdrenoMetal'
    translator = work / '.cache/gpu-reference/metal2vulkan'
    for name, destination in (('AdrenoMetal', metal), ('metal2vulkan', translator)):
        destination.parent.mkdir(parents=True, exist_ok=True)
        pin = source_pins[name]
        run(['git', 'clone', '--quiet', '--no-hardlinks', '--config', 'core.autocrlf=false',
             root / pin['path'], destination])
        run(['git', '-C', destination, 'checkout', '--quiet', '--detach', pin['commit']])
    wrapper = load_module('nabu_metal_plugin_ci', root / 'src/nabu/source-ci/nabu_metal_plugin_ci.py')
    # These are the nabu wrapper's cache and failure diagnostics. Its scanout,
    # CoreImage stitching and replacement-job paths are outside this build.
    patches = [wrapper.ADRENOMETAL_PATCHES[index] for index in (0, 1, 3)]
    for name in patches:
        run(['git', '-C', metal, 'apply', root / 'src/nabu' / name])
    frontend = metal / 'NativeBridgeMetalFrontend.mm'
    replace_once(frontend, 'class_getInstanceSize(base)!=536',
                 'class_getInstanceSize(base)!=' + str(instance_bytes))
    replace_once(frontend, "// The target's base class ABI (iPadOS 17.7.11): the dynamic subclass adds no instance variables.",
                 '// Reviewed iPadOS 16.5 base class ABI; the dynamic subclass adds no instance variables.')
    # This diagnostic is unconditional upstream: the board macros alone do not
    # remove its 21H461 stack/global offsets. Omit it from the derived frontend.
    source = frontend.read_text(encoding='utf-8')
    first = source.index("// Which of QuartzCore's paths asked for a pipeline")
    last = source.index('// What a creation cost beyond its wall time', first)
    replace_once(frontend, source[first:last],
                 '// Standalone 20F66 test: no QuartzCore private-address diagnostics.\n'
                 'static std::string quartzCoreCallers() { return "qc=disabled"; }\n')
    reference = root / 'src/unixnu-turnip'
    for name in ('scripts/build-adreno-metal-bridge.py', 'scripts/mesa_patch_identity.py',
                 'scripts/data/gpu-metal-vulkan-inputs.json'):
        destination = work / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(reference / name, destination)
    bridge = work / 'scripts/build-adreno-metal-bridge.py'
    replace_once(bridge, "IPHONEOS_DEPLOYMENT_TARGET='17.0'", "IPHONEOS_DEPLOYMENT_TARGET='16.5'")
    replace_once(bridge, "'+1.98.0'", "'+' + os.environ['NABU_METAL_RUST']")
    replace_once(bridge, "llvm_as = next(", "llvm_as = os.environ.get('NABU_LLVM_AS') or next(")
    replace_once(bridge, "'build', '--release', '--manifest-path'", "'build', '--release', '--locked', '--manifest-path'")
    rust = tomllib.loads((translator / 'rust-toolchain.toml').read_text(encoding='utf-8'))['toolchain']['channel']
    msrv = tomllib.loads((translator / 'Cargo.toml').read_text(encoding='utf-8'))['workspace']['package']['rust-version']
    assert rust == RUST and msrv == '1.98', 'Reassess the pinned bridge compiler and MSRV'
    return {'frontend': metal, 'translator': translator, 'bridge_script': bridge,
            'patches': patches, 'rust_toolchain': rust, 'rust_msrv': msrv,
            'source_commits': {name: source_pins[name]['commit'] for name in
                               ('nabu', 'UniXNU-turnip-reference', 'AdrenoMetal', 'metal2vulkan')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--turnip-input', type=Path, required=True,
                        help='Qualified Vulkan artifact directory with its build-report.json and signed library')
    parser.add_argument('--mtl-device-bytes', type=int, default=MTL_DEVICE_BYTES_20F66,
                        help='Reviewed class_getInstanceSize(_MTLDevice) for 20F66')
    parser.add_argument('--llvm-as', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Apple frontend builds run in macOS GitHub Actions')
    work, output, turnip_input = args.work.resolve(), args.output.resolve(), args.turnip_input.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'result': 'building', 'target': TARGET, 'mtl_device_instance_bytes': args.mtl_device_bytes,
              'metal_20f66_image_uuid': '88922408-fd68-3396-8465-3775ce66ff60',
              'metal_base_runtime_check_required': True,
              'construction': 'native_bridge_metal_open -> NativeBridgeMetalDevice',
              'service': 'NativeAdrenoGpuPublished', 'open_type': 0x4147,
              'gpu_exercised': False, 'runtime_qualified': False,
              'system_discovery_registered': False, 'scanout_built': False,
              'quartzcore_address_hooks_built': False, 'a740_replay_built': False,
              'quartzcore_private_caller_diagnostics_built': False, 'generic_shader_options_modified': False,
              'replacement_daemons_built': False,
              'runtime_command': './nabu-gpu-metal-probe --run-metal',
              'runtime_outputs': {'pixels': '/var/mobile/Media/nabu-metal-readback.rgba',
                                  'pixel_metadata': '/var/mobile/Media/nabu-metal-readback.json',
                                  'pixel_format': '32x32 RGBA8Unorm, tightly packed 4096 bytes'},
              'success_criteria': {'fill_bytes': 4096, 'compute_words': 1024, 'compute_guard_words': 128,
                                   'render_pixels': 1024, 'colored_pixels': 256, 'other_pixels': 0,
                                   'render_padding_bytes': 4096, 'completed_command_buffers': 3},
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
            raise RuntimeError('Command failed; see ' + str(log) + '\n' + (result.stderr or result.stdout)[-4000:])
        return result

    try:
        prior = json.loads((turnip_input / 'build-report.json').read_text())
        if prior['result'] != 'signed_not_run' or prior['target'] != TARGET:
            raise ValueError('Supply the qualified iOS 16.5 Vulkan artifact')
        if (prior['service'], prior['open_type']) != (report['service'], report['open_type']):
            raise ValueError('Turnip service/ABI transport differs')
        library = turnip_input / prior['turnip']['file']
        macho_target(library, 6)
        run(['codesign', '--verify', '--strict', library])
        detail = run(['codesign', '--display', '--verbose=4', library]).stderr
        cdhash = re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)[1]
        if cdhash != prior['turnip']['cdhash']:
            raise ValueError('Turnip CDHash differs from the input build report')
        report['turnip'] = {**prior['turnip'], 'source_ci': prior['ci'], 'copied_without_resigning': True}
        shutil.copyfile(library, output / library.name)
        shutil.copyfile(turnip_input / 'build-report.json', output / 'turnip-input-report.json')
        staged = stage(ROOT, work, args.mtl_device_bytes, run)
        report.update(frontend_patches=staged['patches'], rust_toolchain=staged['rust_toolchain'], rust_msrv=staged['rust_msrv'],
                      source_commits=staged['source_commits'],
                      frontend_adaptations=['_MTLDevice instance size 536 -> reviewed 20F66 size 528',
                                            'Remove unconditional 21H461 QuartzCore caller/global diagnostics'])
        llvm_version = run([args.llvm_as, '--version']).stdout
        version = re.search(r'LLVM version (\d+)', llvm_version)
        if not version or int(version[1]) < 21:
            raise ValueError('The bridge fixtures require LLVM 21 or newer')
        report['llvm_as'] = llvm_version.strip()
        report['rustc'] = run(['rustc', '+' + RUST, '--version']).stdout.strip()
        env = dict(os.environ, NABU_METAL_RUST=RUST, NABU_LLVM_AS=str(args.llvm_as.resolve()),
                   IPHONEOS_DEPLOYMENT_TARGET='16.5')
        run([sys.executable, staged['bridge_script'], '--target', 'ios', '--manifest-only'], cwd=work, env=env)
        manifest = work / 'build/adreno-metal-bridge/Cargo.toml'
        run(['cargo', '+' + RUST, 'generate-lockfile', '--manifest-path', manifest], env=env)
        run([sys.executable, staged['bridge_script'], '--target', 'ios'], cwd=work, env=env)
        metal = staged['frontend']
        bridge_library = work / 'build/adreno-metal-bridge/ios/libadreno_metal_bridge.a'
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        base = ['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', TARGET, '-isysroot', sdk,
                '-std=c++17', '-O2', '-g', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                '-Wno-deprecated-declarations', '-fstack-protector-strong', '-I', metal,
                '-DNATIVE_ADRENO_SCANOUT_COPY=0', '-DNATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE=0',
                '-DNATIVE_ADRENO_A740_REPLAY=0']
        frontend = output / FRONTEND
        run([*base, '-dynamiclib', metal / 'NativeBridgeMetalFrontend.mm', bridge_library,
             '-Wl,-dead_strip', '-Wl,-install_name,@rpath/' + FRONTEND,
             '-framework', 'Foundation', '-framework', 'Metal', '-framework', 'IOSurface', '-o', frontend])
        (output / 'symbols').mkdir()
        shutil.copyfile(frontend, output / 'symbols' / FRONTEND)
        run(['xcrun', '--sdk', 'iphoneos', 'strip', '-x', frontend])
        report['frontend'] = sign(frontend, 'org.nabu16.metal-frontend', run)
        macho_target(frontend, 6)
        report['frontend']['dependencies'] = run(['otool', '-L', frontend]).stdout.strip()
        shader = ROOT / 'userland/nabu/src/gpu_metal_smoke.metal'
        air = work / 'nabu-metal-smoke.air'
        metallib = output / 'nabu-metal-smoke.metallib'
        run(['xcrun', '--sdk', 'iphoneos', 'metal', '-target', 'air64-apple-ios16.5', '-std=ios-metal2.4',
             '-c', shader, '-o', air])
        run(['xcrun', '--sdk', 'iphoneos', 'metallib', air, '-o', metallib])
        probe = output / 'nabu-gpu-metal-probe'
        run([*base, '-DNABU_EXPECTED_MTL_DEVICE_BYTES=' + str(args.mtl_device_bytes),
             '-I', ROOT / 'src/nabu/gpu/upstream/Adreno6xx', ROOT / 'userland/nabu/src/gpu_metal_probe.mm',
             '-L', output, '-lnabu-metal-frontend', '-Wl,-rpath,@executable_path',
             '-framework', 'Foundation', '-framework', 'Metal', '-o', probe])
        entitlements = output / 'entitlements.plist'
        entitlements.write_bytes(plistlib.dumps(ENTITLEMENTS))
        report['probe'] = sign(probe, 'org.nabu16.gpu-metal-probe', run, entitlements)
        macho_target(probe, 2)
        report['probe']['dependencies'] = run(['otool', '-L', probe]).stdout.strip()
        report['metallib'] = {'file': metallib.name, 'bytes': metallib.stat().st_size,
                              'source': str(shader.relative_to(ROOT)), 'target': 'air64-apple-ios16.5',
                              'functions': ['nabu_compute', 'nabu_vertex', 'nabu_fragment']}
        report['result'] = 'signed_not_run'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, SystemExit) as error:
        report.update(result='failed', error=str(error))
        print(str(error), file=sys.stderr)
    finally:
        for source, name in ((work / 'build/adreno-metal-bridge/build-ios.log', 'bridge-build-ios.log'),
                             (work / 'build/adreno-metal-bridge/Cargo.lock', 'Cargo.lock'),
                             (work / 'build/adreno-metal-bridge/Cargo.toml', 'bridge-Cargo.toml')):
            if source.is_file():
                shutil.copyfile(source, output / name)
        (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('result', 'target', 'gpu_exercised', 'runtime_qualified')}))
    return 0 if report['result'] == 'signed_not_run' else 1


if __name__ == '__main__':
    sys.exit(main())
