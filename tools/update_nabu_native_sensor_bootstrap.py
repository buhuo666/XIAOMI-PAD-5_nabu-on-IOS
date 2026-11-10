#!/usr/bin/env python3
"""Add the signed real-source HID owner to a qualified FastRPC bootstrap."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from package_nabu_userland import bootstrap_permissions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/hakios-8796/tools/apfs'))
from mkapfs import read_tree, Volume, Container


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--baseline-tree',type=Path,required=True,
                        help='Retained tree containing the baseline NabuInit root directory')
    parser.add_argument('--daemon',type=Path,required=True,help='Reviewed daemon build directory')
    parser.add_argument('--axes',required=True,help='Explicit candidate signed axis permutation, e.g. 1,2,3')
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    axes=[int(value) for value in args.axes.split(',')]
    if len(axes)!=3 or sorted(abs(value) for value in axes)!=[1,2,3]:
        parser.error('--axes must be a signed permutation of 1,2,3')
    build=json.loads((args.daemon/'build-report.json').read_text())
    if build['result']!='signed_not_run' or build['target']!='arm64-apple-ios16.5' or build['source_abi_version']!=1:
        raise ValueError('Expected the signed iOS16.5 NabuSensorSource ABI1 daemon')
    if build['entitlements']!={'com.apple.private.hid.client.event-dispatch':True}:
        raise ValueError('Daemon profile differs from the original 20F66 virtual-service gate')
    report=json.loads((args.baseline/'bootstrap-report.json').read_text())
    if report['fastrpc_archive']['missing_soc0_files']:
        raise ValueError('Use the complete original FastRPC archive')
    args.work.mkdir(parents=True,exist_ok=False)
    args.output.mkdir(parents=True,exist_ok=False)
    shutil.copytree(args.baseline_tree/'root',args.work/'root')
    binary=args.daemon/build['binary']['file']
    shutil.copyfile(binary,args.work/'root/sbin/nabu-sensor-daemon')
    label='org.nabu.sensor-daemon'
    arguments=['/redwood/sbin/nabu-sensor-daemon','--axes',','.join(str(value) for value in axes)]
    job={'Label':label,'ProgramArguments':arguments,'RunAtLoad':True,'UserName':'root',
         'StandardOutPath':'/dev/console','StandardErrorPath':'/dev/console'}
    job_path=args.work/'root/LaunchDaemons'/f'{label}.plist'
    job_path.write_bytes(plistlib.dumps(job,fmt=plistlib.FMT_BINARY))

    nodes=read_tree(str(args.work/'root'));bootstrap_permissions(nodes)
    init=args.output/'NabuInit.apfs'
    volume=Volume(0,'NabuInit',nodes,False,1683900000*1000000000,None,[])
    container=Container([volume],256,init.name);container.layout();container.write(str(init))
    checked=subprocess.run(host_command([host_path(ROOT/'build/apfsprogs/apfsck/apfsck'),
        '-c','-u','-w',host_path(init)]),capture_output=True)
    (args.output/'NabuInit-apfsck.log').write_bytes(checked.stdout+checked.stderr)
    checked.check_returncode()
    readbacks=[]
    for path,source in [('/sbin/nabu-sensor-daemon',binary),(f'/LaunchDaemons/{label}.plist',job_path)]:
        returned=subprocess.run(host_command([host_path(ROOT/'build/nabu-audio-apfs-reader/apfs-tool'),
            'cat',host_path(init),path]),capture_output=True,check=True).stdout
        if returned!=source.read_bytes():raise ValueError(f'Native APFS readback differs: {path}')
        readbacks.append({'path':path,'bytes':len(returned),'native_readback_equal':True})
    for name in ('Boot.apfs','App.apfs'):shutil.copyfile(args.baseline/name,args.output/name)
    combined=args.output/'bootstrap.apfs'
    with combined.open('wb') as output:
        for name in ('Boot.apfs','NabuInit.apfs','App.apfs'):
            with (args.output/name).open('rb') as source:shutil.copyfileobj(source,output)
    if combined.stat().st_size>256*1024*1024:raise ValueError('Bootstrap exceeds image budget')
    report.update(bytes=combined.stat().st_size,sha256=hashlib.sha256(combined.read_bytes()).hexdigest(),
                  device_execution_validated=False,deployed=False)
    for item in report['containers']:
        if item['name']=='NabuInit.apfs':
            item.update(bytes=init.stat().st_size,sha256=hashlib.sha256(init.read_bytes()).hexdigest())
    report['native_sensor_owner']={
        'source':str(args.daemon.resolve()),'build_report':build,'job':job,
        'baseline':str(args.baseline.resolve()),'baseline_tree':str(args.baseline_tree.resolve()),
        'axes':axes,'axes_six_face_verified':False,'native_readbacks':readbacks,
        'native_kernel_required':'nabu-slpi=4 with a device-supported nabu-ssc-clock domain',
        'requires_real_source':True,'hid_authority_runtime_verified':False,
        'coremotion_verified':False,'rotation_verified':False,'automatic_brightness_verified':False}
    report['filesystem_check']='NabuInit apfsck and daemon/job native readbacks passed; complete Boot/App copied from baseline'
    (args.output/'bootstrap-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'bootstrap':str(combined.resolve()),'bytes':combined.stat().st_size,
        'native_readbacks':readbacks,'axes_candidate':axes,'device_execution':False},indent=2))


if __name__=='__main__':main()
