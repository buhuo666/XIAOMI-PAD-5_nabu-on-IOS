#!/usr/bin/env python3
"""Compile the opt-in SLPI root-PD census against the retained 8796 headers."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compile-command',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--slpi-mode',type=int,choices=(1,2,3),default=1,
                   help='1: service discovery, 2: live census, 3: FastRPC/registry then live census')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    flags=json.loads(a.compile_command.read_text(encoding='utf-8'))
    source=ROOT/'patches/nabu-sensors/NabuSlpi.cpp';obj=a.output/'NabuSlpi.o'
    command=flags+['-fno-common','-fstack-usage','-Wframe-larger-than=4096','-Werror=frame-larger-than',
                   '-c',host_path(source),'-o',host_path(obj)]
    result=subprocess.run(host_command(command),capture_output=True)
    (a.output/'compile.log').write_bytes(result.stdout+result.stderr)
    report=dict(compiled=result.returncode==0,command=command,object=str(obj),entrypoint='nabu_slpi_start',
                target='arm64-apple-ios16.5',linked=False,device_execution=False,
                boot_argument=f'nabu-slpi={a.slpi_mode}',delay_seconds=60,
                limit='Finite SLPI/SSC trial; mode3 initializes sensor_pd and serves archived original files. No native sensor publication. Secure-world SMC duration is outside APPS polling deadlines.')
    if result.returncode==0:
        frames=[{'function':row.rsplit('\t',2)[0],'bytes':int(row.rsplit('\t',2)[1])}
                for row in obj.with_suffix('.su').read_text().splitlines()]
        report['largest_stack_frame']=max(frames,key=lambda f:f['bytes'])
        report['stack_frame_limit_bytes']=4096
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if result.returncode:raise SystemExit(result.stderr.decode(errors='replace'))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
