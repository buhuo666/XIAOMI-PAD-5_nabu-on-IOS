#!/usr/bin/env python3
"""Add the Unity-observed blit selector to the qualified GPU246 frontend."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build_nabu_gpu_metal_probe import FRONTEND
from build_nabu_gpu_vulkan_probe import TARGET, macho_target, sign

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Use the macOS/Xcode workflow')
    source, out = args.input.resolve(), args.output.resolve()
    prior = json.loads((source/'build-report.json').read_text())
    assert str(prior['ci']['run_id']) == '43373747206'
    assert prior['result'] == 'signed_not_run'
    out.mkdir(parents=True, exist_ok=False)
    metal = out/'frontend-source'
    shutil.copytree(source/'frontend-source', metal)
    include = 'NabuBlitGPUOptimization.inc'
    shutil.copyfile(ROOT/'patches/nabu-metal'/include, metal/include)
    path = metal/'NativeBridgeMetalFrontend.mm'
    text = path.read_text()
    anchor = '- (void)synchronizeResource:(id<MTLResource>)r {(void)r;}\n@end'
    assert text.count(anchor) == 1
    assert 'optimizeContentsForGPUAccess:' not in text
    path.write_text(text.replace(anchor, '#include "'+include+'"\n'+anchor))
    archive = source/'libadreno_metal_bridge.a'
    report = dict(result='building', target=TARGET, commands=[],
                  ci=dict(run_id=os.environ.get('GITHUB_RUN_ID'), head_sha=os.environ.get('GITHUB_SHA')),
                  source_frontend_ci=prior['ci'], frontend_rebuilt=True, rust_rebuilt=False,
                  turnip_rebuilt=False, kernel_rebuilt=False, device_executed=False,
                  added_selector='-[NBBlitEncoder optimizeContentsForGPUAccess:]',
                  semantics='Keep the canonical texture representation and existing resource/IOSurface tracking; no new performance claim')

    def run(command):
        command = list(map(str, command))
        report['commands'].append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        (out/('command-%02d.log' % len(report['commands']))).write_text(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout+result.stderr)[-6000:])
        return result

    try:
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        target = out/FRONTEND
        run(['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', TARGET, '-isysroot', sdk,
             '-std=c++17', '-O2', '-g', '-fobjc-arc', '-Wall', '-Wextra', '-Werror', '-Wno-deprecated-declarations',
             '-fstack-protector-strong', '-I', metal, '-DNATIVE_ADRENO_SCANOUT_COPY=0',
             '-DNATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE=0', '-DNATIVE_ADRENO_A740_REPLAY=0',
             '-dynamiclib', path, archive, '-Wl,-dead_strip', '-Wl,-install_name,@rpath/'+FRONTEND,
             '-framework', 'Foundation', '-framework', 'Metal', '-framework', 'IOSurface', '-o', target])
        (out/'symbols').mkdir()
        shutil.copyfile(target, out/'symbols'/FRONTEND)
        symbols = run(['nm', '-an', target]).stdout
        assert '-[NBBlitEncoder optimizeContentsForGPUAccess:]' in symbols
        report['selector_in_binary'] = True
        run(['xcrun', 'dsymutil', target, '-o', out/(FRONTEND+'.dSYM')])
        run(['xcrun', '--sdk', 'iphoneos', 'strip', '-x', target])
        report['frontend'] = {**prior['frontend'], **sign(target, 'org.nabu16.metal-frontend', run)}
        macho_target(target, 6)
        report['frontend']['dependencies'] = run(['otool', '-L', target]).stdout.strip()
        exported = set(run(['nm', '-gj', target]).stdout.splitlines())
        for key in ('surface_statistics_exports', 'resource_aliasing_exports'):
            assert set(prior['frontend'][key]).issubset(exported)
        assert '_native_bridge_metal_set_ca_trace' in exported
        report['result'] = 'signed_not_run'
    finally:
        (out/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ['result', 'added_selector', 'device_executed']}))


if __name__ == '__main__':
    main()
