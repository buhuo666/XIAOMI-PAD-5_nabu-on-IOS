#!/usr/bin/env python3
"""Relink only the qualified Objective-C frontend with the IOSurface cache fix."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build_nabu_gpu_metal_probe import FRONTEND
from build_nabu_gpu_vulkan_probe import TARGET, macho_target, sign

ROOT=Path(__file__).resolve().parents[1]
PATCH='NativeMetalSurfaceImports.inc'


def stage_surface_import_cache(root, metal):
    path=metal/'NativeBridgeMetalFrontend.mm'
    source=path.read_text(encoding='utf-8')
    begin=source.index('static NSMapTable<NSValue *,NBBuffer *> *gSurfaceImports;')
    end=source.index('static uint64_t textureRotation(',begin)
    source=source[:begin]+'#include "'+PATCH+'"\n\n'+source[end:]
    path.write_text(source,encoding='utf-8')
    shutil.copyfile(root/'patches/nabu-metal'/PATCH,metal/PATCH)


def stage_ca_present_trace(root, metal):
    path=metal/'NativeBridgeMetalFrontend.mm'
    source=path.read_text(encoding='utf-8')
    anchor='extern "C" void sys_dcache_flush(void *start, size_t length);'
    source=source.replace(anchor, '#include "NativeMetalCaPresentTrace.inc"\n\n'+anchor, 1)
    for old,new in (('   [drawable present];','   nabuCaPresent(drawable,false,0);'),
                    ('   [drawable presentAtTime:time];','   nabuCaPresent(drawable,true,time);')):
        if source.count(old)!=1:raise ValueError('Qualified present site changed: '+old)
        source=source.replace(old,new,1)
    path.write_text(source,encoding='utf-8')
    shutil.copyfile(root/'patches/nabu-metal/NativeMetalCaPresentTrace.inc',metal/'NativeMetalCaPresentTrace.inc')
    shutil.copyfile(root/'userland/nabu/src/ca_trace_marker.h',metal/'ca_trace_marker.h')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--ca-trace',action='store_true')
    args=p.parse_args()
    if sys.platform!='darwin':p.error('The frontend relink requires macOS/Xcode')
    prior_dir=args.input.resolve();out=args.output.resolve()
    prior=json.loads((prior_dir/'build-report.json').read_text())
    expected='43040953235' if args.ca_trace else '42757503932'
    if prior['ci']['run_id']!=expected or not prior['owned_copy_pages']:
        raise ValueError('Expected qualified frontend input CI'+expected)
    shutil.copytree(prior_dir,out)
    metal=out/'frontend-source'
    if args.ca_trace:stage_ca_present_trace(ROOT,metal)
    else:stage_surface_import_cache(ROOT,metal)
    report=dict(prior)
    report.update(result='building',surface_import_cache_recovery=True,
                  surface_import_cache_scope='Prune before import; one exact Device OOM retry after dropping only cache strong references outside mutex',
                  source_frontend_ci=prior['ci'],rust_rebuilt=False,turnip_rebuilt=False,
                  ci={'run_id':os.environ.get('GITHUB_RUN_ID'),'head_sha':os.environ.get('GITHUB_SHA')},
                  commands=[])
    report['ca_present_trace']=args.ca_trace
    def run(command,**kw):
        command=list(map(str,command));report['commands'].append(command)
        r=subprocess.run(command,capture_output=True,text=True,**kw)
        (out/('cache-command-%02d.log'%len(report['commands']))).write_text(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError((r.stdout+r.stderr)[-6000:])
        return r
    try:
        sdk=run(['xcrun','--sdk','iphoneos','--show-sdk-path']).stdout.strip()
        target=out/FRONTEND
        command=['xcrun','--sdk','iphoneos','clang++','-target',TARGET,'-isysroot',sdk,
                 '-std=c++17','-O2','-g','-fobjc-arc','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations',
                 '-fstack-protector-strong','-I',metal,'-DNATIVE_ADRENO_SCANOUT_COPY=0',
                 '-DNATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE=0','-DNATIVE_ADRENO_A740_REPLAY=0',
                 '-dynamiclib',metal/'NativeBridgeMetalFrontend.mm',out/'libadreno_metal_bridge.a',
                 '-Wl,-dead_strip','-Wl,-install_name,@rpath/'+FRONTEND,
                 '-framework','Foundation','-framework','Metal','-framework','IOSurface','-o',target]
        run(command)
        shutil.copyfile(target,out/'symbols'/FRONTEND)
        run(['xcrun','dsymutil',target,'-o',out/(FRONTEND+'.dSYM')])
        run(['xcrun','--sdk','iphoneos','strip','-x',target])
        report['frontend']={**prior['frontend'],**sign(target,'org.nabu16.metal-frontend',run)}
        macho_target(target,6)
        report['frontend']['dependencies']=run(['otool','-L',target]).stdout.strip()
        exported=set(run(['nm','-gj',target]).stdout.splitlines())
        if args.ca_trace and '_native_bridge_metal_set_ca_trace' not in exported:
            raise ValueError('CA marker setter export missing')
        for group in ('surface_statistics_exports','resource_aliasing_exports'):
            if not set(prior['frontend'][group]).issubset(exported):
                raise ValueError('Relink lost qualified frontend exports: '+group)
        report['result']='signed_not_run'
    finally:
        (out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('result','surface_import_cache_recovery','rust_rebuilt','turnip_rebuilt')}))


if __name__=='__main__':main()
