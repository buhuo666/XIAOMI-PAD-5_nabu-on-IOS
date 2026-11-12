#!/usr/bin/env python3
"""Rebuild the qualified GPU222 frontend/runtime with iOS QoS and bounded submission markers."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build_nabu_gpu_metal_probe import FRONTEND, RUST, replace_once
from build_nabu_gpu_vulkan_probe import TARGET, macho_target, sign
from nabu_metal_submit_trace import stage_submit_trace
from nabu_metal_ios_qos import stage_ios_qos

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--llvm-as', type=Path, required=True)
    a = p.parse_args()
    if sys.platform != 'darwin': p.error('Use macOS/Xcode16.4 CI')
    prior_dir, out, work = a.input.resolve(), a.output.resolve(), a.work.resolve()
    prior = json.loads((prior_dir / 'build-report.json').read_text())
    if prior['ci']['run_id'] != '43148373620' or not all(prior.get(k) for k in
            ('owned_copy_pages','family_answer_cache','ca_present_trace','surface_import_cache_recovery')):
        raise ValueError('Expected GPU222 qualified family-cache artifact')
    shutil.copytree(prior_dir, out)
    work.mkdir(parents=True, exist_ok=False)
    metal = work / 'drivers/AdrenoMetal'
    shutil.copytree(prior_dir / 'frontend-source', metal)
    report = dict(prior)
    report.update(result='building',source_frontend_ci=prior['ci'],commands=[],rust_rebuilt=True,
                  turnip_rebuilt=False,submission_trace=stage_submit_trace(ROOT,metal),
                  ci={'run_id':os.environ.get('GITHUB_RUN_ID'),'head_sha':os.environ.get('GITHUB_SHA')},
                  runtime_cache_note='Runtime source patch identity changes; cold shader cache must warm before performance qualification')

    def run(command, **kwargs):
        command = list(map(str, command)); report['commands'].append(command)
        print('+ ' + ' '.join(command), flush=True)
        r = subprocess.run(command, capture_output=True, text=True, **kwargs)
        (out / ('submit-command-%02d.log' % len(report['commands']))).write_text(r.stdout+r.stderr)
        if r.returncode: raise RuntimeError((r.stdout+r.stderr)[-6000:])
        return r

    try:
        report['ios_thread_qos'] = stage_ios_qos(ROOT,metal)
        report['runtime_patches'] = [line.strip() for line in (metal/'bridge/patches/series').read_text().splitlines()
                                     if line.strip() and not line.lstrip().startswith('#')]
        pins = {x['name']:x for x in json.loads((ROOT/'configs/sources.lock.json').read_text())['sources']}
        translator = work / '.cache/gpu-reference/metal2vulkan'
        translator.parent.mkdir(parents=True)
        run(['git','clone','--quiet','--no-hardlinks','--config','core.autocrlf=false',ROOT/pins['metal2vulkan']['path'],translator])
        run(['git','-C',translator,'checkout','--quiet','--detach',pins['metal2vulkan']['commit']])
        for name in ('scripts/build-adreno-metal-bridge.py','scripts/mesa_patch_identity.py','scripts/data/gpu-metal-vulkan-inputs.json'):
            destination = work/name; destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/'src/unixnu-turnip'/name,destination)
        bridge = work/'scripts/build-adreno-metal-bridge.py'
        for old,new in (("IPHONEOS_DEPLOYMENT_TARGET='17.0'","IPHONEOS_DEPLOYMENT_TARGET='16.5'"),
                        ("'+1.98.0'","'+' + os.environ['NABU_METAL_RUST']"),
                        ('llvm_as = next(',"llvm_as = os.environ.get('NABU_LLVM_AS') or next("),
                        ("'build', '--release', '--manifest-path'","'build', '--release', '--locked', '--manifest-path'")):
            replace_once(bridge,old,new)
        env = dict(os.environ,NABU_METAL_RUST=RUST,NABU_LLVM_AS=str(a.llvm_as.resolve()),IPHONEOS_DEPLOYMENT_TARGET='16.5')
        run([sys.executable,bridge,'--target','ios','--manifest-only'],cwd=work,env=env)
        manifest = work/'build/adreno-metal-bridge/Cargo.toml'
        shutil.copyfile(prior_dir/'Cargo.lock',manifest.with_name('Cargo.lock'))
        report['runtime_dependency_lock'] = 'Cargo.lock retained from qualified GPU222 input; cargo --locked'
        run([sys.executable,bridge,'--target','ios'],cwd=work,env=env)
        archive = out/'libadreno_metal_bridge.a'
        shutil.copyfile(work/'build/adreno-metal-bridge/ios/libadreno_metal_bridge.a',archive)
        shutil.copyfile(manifest.with_name('Cargo.lock'),out/'Cargo.lock')
        shutil.copytree(metal,out/'frontend-source',dirs_exist_ok=True)
        sdk = run(['xcrun','--sdk','iphoneos','--show-sdk-path']).stdout.strip()
        target = out/FRONTEND
        run(['xcrun','--sdk','iphoneos','clang++','-target',TARGET,'-isysroot',sdk,
             '-std=c++17','-O2','-g','-fobjc-arc','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations',
             '-fstack-protector-strong','-I',metal,'-DNATIVE_ADRENO_SCANOUT_COPY=0',
             '-DNATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE=0','-DNATIVE_ADRENO_A740_REPLAY=0',
             '-dynamiclib',metal/'NativeBridgeMetalFrontend.mm',archive,'-Wl,-dead_strip',
             '-Wl,-install_name,@rpath/'+FRONTEND,'-framework','Foundation','-framework','Metal',
             '-framework','IOSurface','-o',target])
        shutil.copyfile(target,out/'symbols'/FRONTEND)
        run(['xcrun','dsymutil',target,'-o',out/(FRONTEND+'.dSYM')])
        run(['xcrun','--sdk','iphoneos','strip','-x',target])
        report['frontend']={**prior['frontend'],**sign(target,'org.nabu16.metal-frontend',run)}
        macho_target(target,6)
        report['frontend']['dependencies']=run(['otool','-L',target]).stdout.strip()
        exported=set(run(['nm','-gj',target]).stdout.splitlines())
        if '_native_bridge_metal_set_ca_trace' not in exported: raise ValueError('Missing CA trace setter')
        for key in ('surface_statistics_exports','resource_aliasing_exports'):
            if not set(prior['frontend'][key]).issubset(exported): raise ValueError('Missing '+key)
        report['result']='signed_not_run'
    finally:
        (out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('result','rust_rebuilt','turnip_rebuilt','ios_thread_qos','submission_trace')}))


if __name__ == '__main__': main()
