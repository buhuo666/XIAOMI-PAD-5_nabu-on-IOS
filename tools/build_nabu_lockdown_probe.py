#!/usr/bin/env python3
"""Build the local stock-lockdownd query probe against libSystem's C ABI."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    symbols=['printf','snprintf','fflush','malloc','free','strlen','sleep','alarm','socket','connect','close','read','write','setsockopt','__error']
    tbd=a.output/'libSystem.tbd';tbd.write_text('--- !tapi-tbd\ntbd-version: 4\ntargets: [ arm64-ios ]\ninstall-name: /usr/lib/libSystem.B.dylib\nexports:\n  - targets: [ arm64-ios ]\n    symbols: [ dyld_stub_binder, '+', '.join('_'+s for s in symbols)+' ]\n...\n',newline='\n')
    source=ROOT/'userland/nabu/src/lockdown_probe.c';obj=a.output/'lockdown_probe.o';binary=a.output/'lockdown-probe'
    subprocess.run(host_command(['clang-18','-target','arm64-apple-ios16.5','-std=c11','-Os','-ffreestanding','-fno-stack-protector','-fno-builtin','-Wall','-Wextra','-Werror','-c',host_path(source),'-o',host_path(obj)]),check=True)
    subprocess.run(host_command(['ld64.lld-18','-arch','arm64','-platform_version','ios','16.5','16.5','-e','_main','-adhoc_codesign','-o',host_path(binary),host_path(obj),host_path(tbd)]),check=True)
    (a.output/'build-report.json').write_text(json.dumps({'source':str(source),'bytes':binary.stat().st_size,'target':'arm64-apple-ios16.5','requests':['QueryType','GetValue ProductType','GetValue DeviceName','GetValue ActivationState'],'runtime_verified':False},indent=2)+'\n')
    print('Built',binary)

if __name__=='__main__':main()
