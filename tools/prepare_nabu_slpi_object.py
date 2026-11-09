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
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    flags=json.loads(a.compile_command.read_text(encoding='utf-8'))
    source=ROOT/'patches/nabu-sensors/NabuSlpi.cpp';obj=a.output/'NabuSlpi.o'
    command=flags+['-fno-common','-fstack-usage','-c',host_path(source),'-o',host_path(obj)]
    result=subprocess.run(host_command(command),capture_output=True)
    (a.output/'compile.log').write_bytes(result.stdout+result.stderr)
    report=dict(compiled=result.returncode==0,command=command,object=str(obj),entrypoint='nabu_slpi_start',
                target='arm64-apple-ios16.5',linked=False,device_execution=False,
                boot_argument='nabu-slpi=1',delay_seconds=60,
                limit='Root-PD census only. No FastRPC sensor_pd, registry file server, or native sensor publication. Secure-world SMC duration is outside APPS polling deadlines.')
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    if result.returncode:raise SystemExit(result.stderr.decode(errors='replace'))
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
