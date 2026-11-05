#!/usr/bin/env python3
"""Build a deadline for the measured 20F66 Lockdown HWInfo receive wait."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    symbols=['mach_msg','__error','vsnprintf','write','getprogname',
             '_dyld_image_count','_dyld_get_image_vmaddr_slide','_dyld_get_image_name']
    stub=a.output/'libSystem.tbd'
    stub.write_text('--- !tapi-tbd\ntbd-version: 4\ntargets: [ arm64-ios ]\n'
        'install-name: /usr/lib/libSystem.B.dylib\nexports:\n'
        '  - targets: [ arm64-ios ]\n    symbols: [ dyld_stub_binder, '
        +', '.join('_'+x for x in symbols)+' ]\n...\n',newline='\n')
    source=ROOT/'userland/nabu/src/lockdown_fairplay_timeout.c'
    obj=a.output/'lockdown_fairplay_timeout.o';binary=a.output/'libnabu.lockdown-timeout.dylib'
    subprocess.run(host_command(['clang-18','-target','arm64-apple-ios16.5','-std=c11','-Os',
        '-ffreestanding','-fno-stack-protector','-fno-builtin','-Wall','-Wextra','-Werror',
        '-c',host_path(source),'-o',host_path(obj)]),check=True)
    subprocess.run(host_command(['ld64.lld-18','-arch','arm64','-platform_version','ios','16.5','16.5',
        '-dylib','-install_name','/redwood/lib/libnabu.lockdown-timeout.dylib','-adhoc_codesign',
        '-o',host_path(binary),host_path(obj),host_path(stub)]),check=True)
    report={'binary':str(binary),'target':'arm64-ios16.5','original_caller':'0x10002bdd8',
        'request_id':1203,'send_bytes':24,'receive_bytes':60,'receive_timeout_ms':5000,
        'target_process':'/usr/libexec/lockdownd','original_return_preserved':True,
        'scope':'Only matching original HWInfo receive wait; no generated replies or authentication bypass',
        'runtime_verified':False}
    (a.output/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
