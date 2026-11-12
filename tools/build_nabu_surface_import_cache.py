#!/usr/bin/env python3
"""Relink only the qualified Objective-C frontend with a selected narrow patch."""
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
FAMILY_PATCH='NativeMetalFamilyAnswers.inc'
FAMILY_SOURCE_CI='43142617452'
FAMILY_INSTALL_OLD='  case NMB_ANSWER_FLAG_ARG: class_addMethod(cls,sel,(IMP)flagArgAnswer,"B24@0:8Q16");break;'
FAMILY_INSTALL_NEW='  case NMB_ANSWER_FLAG_ARG: class_addMethod(cls,sel,!strcmp(name,"supportsFamily:")?(IMP)familyArgAnswer:(IMP)flagArgAnswer,"B24@0:8Q16");break;'


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


def stage_family_answers(root, metal):
    """Change only supportsFamily:'s installed IMP; use the existing Rust ABI."""
    path=metal/'NativeBridgeMetalFrontend.mm'
    source=path.read_text(encoding='utf-8')
    anchor='static void installAnswers(Class cls) {'
    if FAMILY_PATCH in source:
        raise ValueError('Family answer cache is already staged')
    for old in (anchor,FAMILY_INSTALL_OLD):
        if source.count(old)!=1:
            raise ValueError('Qualified family answer site changed: '+old)
    source=source.replace(anchor,'#include "'+FAMILY_PATCH+'"\n\n'+anchor,1)
    source=source.replace(FAMILY_INSTALL_OLD,FAMILY_INSTALL_NEW,1)
    path.write_text(source,encoding='utf-8',newline='\n')
    shutil.copyfile(root/'patches/nabu-metal'/FAMILY_PATCH,metal/FAMILY_PATCH)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    mode=p.add_mutually_exclusive_group()
    mode.add_argument('--ca-trace',action='store_true')
    mode.add_argument('--family-cache',action='store_true',
                      help='Cache supportsFamily: on the qualified GPU221 frontend; preserve its CA trace')
    args=p.parse_args()
    if sys.platform!='darwin':p.error('The frontend relink requires macOS/Xcode')
    prior_dir=args.input.resolve();out=args.output.resolve()
    prior=json.loads((prior_dir/'build-report.json').read_text())
    expected=FAMILY_SOURCE_CI if args.family_cache else ('43040953235' if args.ca_trace else '42757503932')
    if prior['ci']['run_id']!=expected or not prior['owned_copy_pages']:
        raise ValueError('Expected qualified frontend input CI'+expected)
    if args.family_cache:
        if not prior.get('ca_present_trace') or not prior.get('surface_import_cache_recovery'):
            raise ValueError('Family cache requires the qualified CA trace and IOSurface cache')
        source=(prior_dir/'frontend-source/NativeBridgeMetalFrontend.mm').read_text(encoding='utf-8')
        for name in ('NativeMetalCaPresentTrace.inc',PATCH):
            if source.count('#include "'+name+'"')!=1:
                raise ValueError('Qualified frontend include missing or repeated: '+name)
    shutil.copytree(prior_dir,out)
    metal=out/'frontend-source'
    if args.family_cache:stage_family_answers(ROOT,metal)
    elif args.ca_trace:stage_ca_present_trace(ROOT,metal)
    else:stage_surface_import_cache(ROOT,metal)
    report=dict(prior)
    report.update(result='building',surface_import_cache_recovery=True,
                  surface_import_cache_scope='Prune before import; one exact Device OOM retry after dropping only cache strong references outside mutex',
                  source_frontend_ci=prior['ci'],rust_rebuilt=False,turnip_rebuilt=False,
                  ci={'run_id':os.environ.get('GITHUB_RUN_ID'),'head_sha':os.environ.get('GITHUB_SHA')},
                  commands=[])
    report['ca_present_trace']=args.ca_trace or bool(prior.get('ca_present_trace'))
    report['family_answer_cache']=args.family_cache
    if args.family_cache:
        report['family_answer_cache_scope']='Per Objective-C device and full NSUInteger family; cache successful YES/NO only, retry failures; no device ivars or Rust ABI changes'
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
        if report['ca_present_trace'] and '_native_bridge_metal_set_ca_trace' not in exported:
            raise ValueError('CA marker setter export missing')
        for group in ('surface_statistics_exports','resource_aliasing_exports'):
            if not set(prior['frontend'][group]).issubset(exported):
                raise ValueError('Relink lost qualified frontend exports: '+group)
        report['result']='signed_not_run'
    finally:
        (out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('result','surface_import_cache_recovery','ca_present_trace',
                                          'family_answer_cache','rust_rebuilt','turnip_rebuilt')}))


if __name__=='__main__':main()
