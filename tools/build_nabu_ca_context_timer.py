#!/usr/bin/env python3
"""Build the opt-in 20F66 CA context scheduler with Xcode16.4; no installation."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from build_nabu_gpu_vulkan_probe import macho_target

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if sys.platform!='darwin':parser.error('Use the existing macOS Xcode16.4 CI toolchain')
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    report={'result':'building','target':'arm64-apple-ios16.5','commands':[],
            'source':'userland/nabu/src/ca_context_timer.c',
            'required_environment':{'NABU_CA_CONTEXT_TIMER':'1','NABU_CA_SINGLE_FREE_PAGE':'1'},
            'optional_observer_environment':{'NABU_CA_FRAME_TRACE':'1'},'process':'backboardd',
            'quartzcore_uuid':'dc2dd4c1-7866-3443-8050-fc915a0204c1',
            'device_executed':False,'executable_pages_modified':False,
            'ci':{'run_id':os.environ.get('GITHUB_RUN_ID'),'head_sha':os.environ.get('GITHUB_SHA')}}
    def run(command):
        command=list(map(str,command));report['commands'].append(command)
        result=subprocess.run(command,capture_output=True,text=True,timeout=180)
        (out/('command-%02d.log'%len(report['commands']))).write_text(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError((result.stderr or result.stdout)[-6000:])
        return result
    try:
        version=run(['xcodebuild','-version']).stdout.strip();report['xcode']=version
        if not version.startswith('Xcode 16.4\n'):raise ValueError('Select Xcode16.4')
        test=out/'ca-context-timer-test'
        run(['xcrun','--sdk','macosx','clang','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
             '-fsanitize=address,undefined','-pthread',ROOT/'userland/nabu/tests/ca_context_timer_test.c','-o',test])
        report['host_test']=run([test]).stdout.strip()
        observer_test=out/'ca-frame-trace-test'
        run(['xcrun','--sdk','macosx','clang','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
             '-fsanitize=address,undefined',ROOT/'userland/nabu/tests/ca_frame_trace_test.c','-o',observer_test])
        report['observer_host_test']=run([observer_test]).stdout.strip()
        sdk=run(['xcrun','--sdk','iphoneos','--show-sdk-path']).stdout.strip()
        base=['xcrun','--sdk','iphoneos','clang','-target',report['target'],'-isysroot',sdk,
              '-std=c11','-Os','-Wall','-Wextra','-Werror','-fno-omit-frame-pointer']
        objects=[]
        for unit in ('ca_context_timer','ca_frame_trace','ca_context_timer_entry'):
            obj=out/(unit+'.o');objects.append(obj)
            run([*base,'-c',ROOT/('userland/nabu/src/'+unit+'.c'),'-o',obj])
        install_name='/redwood/lib/libnabu.ca-timer.dylib'
        binary=out/'libnabu.ca-timer.dylib'
        run([*base,'-dynamiclib','-install_name',install_name,*objects,'-o',binary])
        macho_target(binary,6)
        if install_name not in run(['otool','-D',binary]).stdout.splitlines():
            raise ValueError('Unexpected install_name')
        run(['codesign','--force','--sign','-','--timestamp=none','--pagesize','4096',
             '--identifier','org.nabu.ca-context-timer',binary])
        run(['codesign','--verify','--strict',binary])
        detail=run(['codesign','--display','--verbose=4',binary]).stderr
        cdhash=re.search(r'^CDHash=([0-9a-f]{40})$',detail,re.M)
        if not cdhash or not re.search(r'^Page size=4096$',detail,re.M):
            raise ValueError('4KiB ad hoc signature missing')
        report.update(result='signed_not_run',binary=binary.name,bytes=binary.stat().st_size,
                      install_name=install_name,cdhash=cdhash[1],signature_page_bytes=4096,
                      core_object='ca_context_timer.o',constructor_object='ca_context_timer_entry.o',
                      observer_object='ca_frame_trace.o',observer_bundled=True,observer_installed_first=True,
                      total_data_vtable_slots=6,scheduler_data_vtable_slots=2,can_retry_data_vtable_slots=4,
                      observer_data_vtable_slots=19,maximum_observer_capabilities=127,
                      observer_flush_event=127,observer_flush_subevents=[1,2],observer_flush_capability=64,
                      observer_flush_thread_cpu_clock='clock_gettime_nsec_np(CLOCK_THREAD_CPUTIME_ID=16)',
                      mode='original-can-false single-empty-next-page retry',
                      policy='flags0 original false, count3, non-current next with no frame/swap/render/surface/fence; original flags1 retry',
                      limitations=['Requires process-start opt-in; no runtime toggle or unload',
                                   'Resource-gated can retry, not exclusive attribution to the asynchronous context timer',
                                   'Original render flags and requested times remain unchanged',
                                   'Runtime installation and both latency targets remain unverified'])
    finally:
        (out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
