#!/usr/bin/env python3
"""Relink the GPU230 frontend with bounded encoding CPU totals, reusing its Rust archive."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build_nabu_gpu_metal_probe import FRONTEND
from build_nabu_gpu_vulkan_probe import TARGET, macho_target, sign
from nabu_metal_encode_profile import stage_encode_profile

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if sys.platform != 'darwin':
        p.error('Use macOS/Xcode16.4 CI')
    source, out = a.input.resolve(), a.output.resolve()
    prior = json.loads((source/'build-report.json').read_text())
    if str(prior['ci']['run_id']) != '43184629696' or not prior['runtime_submission_trace']:
        raise ValueError('Expected qualified GPU230 runtime and frontend')
    out.mkdir(parents=True, exist_ok=False)
    metal = out/'frontend-source'
    shutil.copytree(source/'frontend-source', metal)
    archive = out/'libadreno_metal_bridge.a'
    shutil.copyfile(source/archive.name, archive)
    report = dict(result='building', target=TARGET, commands=[],
        ci=dict(run_id=os.environ.get('GITHUB_RUN_ID'), head_sha=os.environ.get('GITHUB_SHA')),
        source_frontend_ci=prior['ci'], frontend_rebuilt=True, rust_rebuilt=False,
        turnip_rebuilt=False, kernel_rebuilt=False, device_executed=False,
        encoding_profile=stage_encode_profile(ROOT,metal),
        runtime_cache_note='Qualified Rust archive reused byte-for-byte; runtime shader-cache identity retained')

    def run(command):
        command = list(map(str,command)); report['commands'].append(command)
        print('+ '+' '.join(command),flush=True)
        result = subprocess.run(command,capture_output=True,text=True)
        (out/('command-%02d.log'%len(report['commands']))).write_text(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout+result.stderr)[-6000:])
        return result

    try:
        sdk = run(['xcrun','--sdk','iphoneos','--show-sdk-path']).stdout.strip()
        target = out/FRONTEND
        run(['xcrun','--sdk','iphoneos','clang++','-target',TARGET,'-isysroot',sdk,
             '-std=c++17','-O2','-g','-fobjc-arc','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations',
             '-fstack-protector-strong','-I',metal,'-DNATIVE_ADRENO_SCANOUT_COPY=0',
             '-DNATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE=0','-DNATIVE_ADRENO_A740_REPLAY=0',
             '-dynamiclib',metal/'NativeBridgeMetalFrontend.mm',archive,'-Wl,-dead_strip',
             '-Wl,-install_name,@rpath/'+FRONTEND,'-framework','Foundation','-framework','Metal',
             '-framework','IOSurface','-o',target])
        (out/'symbols').mkdir()
        shutil.copyfile(target,out/'symbols'/FRONTEND)
        run(['xcrun','dsymutil',target,'-o',out/(FRONTEND+'.dSYM')])
        run(['xcrun','--sdk','iphoneos','strip','-x',target])
        report['frontend']={**prior['frontend'],**sign(target,'org.nabu16.metal-frontend',run)}
        macho_target(target,6)
        report['frontend']['dependencies']=run(['otool','-L',target]).stdout.strip()
        exported=set(run(['nm','-gj',target]).stdout.splitlines())
        for key in ('surface_statistics_exports','resource_aliasing_exports'):
            if not set(prior['frontend'][key]).issubset(exported):
                raise ValueError('Missing '+key)
        if '_native_bridge_metal_set_ca_trace' not in exported:
            raise ValueError('Missing qualified CA trace setter')
        report['result']='signed_not_run'
    finally:
        (out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('result','frontend_rebuilt','rust_rebuilt')}))


if __name__ == '__main__':
    main()
