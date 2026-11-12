#!/usr/bin/env python3
"""Build opt-in 20F66 CA observer with Xcode16.4; never install or run on device."""
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
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if sys.platform!='darwin':p.error('Use the existing macOS Xcode16.4 CI toolchain')
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    report={'result':'building','target':'arm64-apple-ios16.5','commands':[],
        'source':'userland/nabu/src/ca_frame_trace.c','required_environment':{'NABU_CA_FRAME_TRACE':'1'},
        'process':'backboardd','device_executed':False,'executable_pages_modified':False,
        'ci':{'run_id':os.environ.get('GITHUB_RUN_ID'),'head_sha':os.environ.get('GITHUB_SHA')}}
    def run(command):
        command=list(map(str,command));report['commands'].append(command)
        r=subprocess.run(command,capture_output=True,text=True,timeout=180)
        (out/('command-%02d.log'%len(report['commands']))).write_text(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError((r.stderr or r.stdout)[-6000:])
        return r
    try:
        version=run(['xcodebuild','-version']).stdout.strip();report['xcode']=version
        if not version.startswith('Xcode 16.4\n'):raise ValueError('Select Xcode16.4')
        test=out/'ca-frame-trace-test'
        run(['xcrun','--sdk','macosx','clang','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
             '-fsanitize=address,undefined',ROOT/'userland/nabu/tests/ca_frame_trace_test.c','-o',test])
        report['host_test']=run([test]).stdout.strip()
        sdk=run(['xcrun','--sdk','iphoneos','--show-sdk-path']).stdout.strip()
        base=['xcrun','--sdk','iphoneos','clang','-target',report['target'],'-isysroot',sdk,
              '-std=c11','-Os','-Wall','-Wextra','-Werror','-fno-omit-frame-pointer']
        objects=[]
        for unit in ('ca_frame_trace','ca_frame_trace_entry'):
            obj=out/(unit+'.o');objects.append(obj)
            run([*base,'-c',ROOT/('userland/nabu/src/'+unit+'.c'),'-o',obj])
        binary=out/'libnabu.ca-frame-trace.dylib'
        run([*base,'-dynamiclib','-install_name','/redwood/lib/libnabu.ca-frame-trace.dylib',
             *objects,'-o',binary])
        macho_target(binary,6)
        run(['codesign','--force','--sign','-','--timestamp=none','--pagesize','4096',
             '--identifier','org.nabu.ca-frame-trace',binary])
        run(['codesign','--verify','--strict',binary])
        detail=run(['codesign','--display','--verbose=4',binary]).stderr
        cd=re.search(r'^CDHash=([0-9a-f]{40})$',detail,re.M)
        if not cd or not re.search(r'^Page size=4096$',detail,re.M):raise ValueError('4KiB ad hoc signature missing')
        report.update(result='signed_not_run',binary=binary.name,bytes=binary.stat().st_size,
                      cdhash=cd[1],signature_page_bytes=4096,core_object='ca_frame_trace.o',
                      constructor_object='ca_frame_trace_entry.o',events=[96,118],
                      limitations=['No direct prepare_layer0/CopyImageInfo/did_display entry hook',
                                   'Snapshots are raw selected state, not atomic transition records',
                                   'Installation and invocation require runtime verification'])
    finally:(out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
