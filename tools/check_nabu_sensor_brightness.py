#!/usr/bin/env python3
"""Run the production ALS identity gate without IOKit or device access."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    binary=args.output/'sensor-brightness-identity'
    source=ROOT/'userland/nabu/tests/sensor_brightness_identity_test.c'
    compile_command=host_command(['clang-18','-std=c11','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined','-g',host_path(source),'-o',host_path(binary)])
    compiled=subprocess.run(compile_command,capture_output=True)
    (args.output/'compile.log').write_bytes(compiled.stdout+compiled.stderr)
    compiled.check_returncode()
    ran=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (args.output/'run.log').write_bytes(ran.stdout+ran.stderr)
    report={'passed':ran.returncode==0,'source':str(source),'command':compile_command,
        'result':ran.stdout.decode(errors='replace'),'device_executed':False,
        'limitation':'Identity policy only; Objective-C wrappers and real CF types require the macOS host test, hardware automatic brightness remains unverified'}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    ran.check_returncode();print(report['result'])

if __name__=='__main__':main()
