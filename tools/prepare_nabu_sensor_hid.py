#!/usr/bin/env python3
"""Compile the real sensor-source IOService and resolve imports in the saved kernel.

This does not link/deploy a kernel or claim native HID functionality. The name
retains the planned HID boundary; current 8796 lacks the IOHIDEventService base.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from check_darwinboot_8796 import host_command, host_path
from link_nabu_data_block import Object, macho, exports, unserialize_xml

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compile-command',type=Path,required=True)
    parser.add_argument('--kernel',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    obj=output/'NabuSensorHid.o'
    flags=json.loads(args.compile_command.read_text(encoding='utf-8'))
    command=flags+['-Wall','-Wextra','-Werror','-mgeneral-regs-only','-fno-common','-fstack-usage',
        '-Wframe-larger-than=4096','-Werror=frame-larger-than',
        '-c',host_path(ROOT/'patches/nabu-sensors/NabuSensorHid.cpp'),'-o',host_path(obj)]
    result=subprocess.run(host_command(command),capture_output=True)
    (output/'compile.log').write_bytes(result.stdout+result.stderr)
    report={'compiled':result.returncode==0,'command':command,'object':str(obj),
        'target':'arm64-apple-ios16.5','linked':False,'device_execution':False,
        'native_hid_published':False,'service_class':'NabuSensorSource',
        'shared_abi':'patches/nabu-sensors/NabuSensorHid.h','shared_structure_bytes':
            {'description':104,'record':64,'status':224,'control':16}}
    try:
        if result.returncode:raise RuntimeError(result.stderr.decode(errors='replace'))
        kernel=args.kernel.read_bytes();image=macho(kernel)
        names={name:address for address,group in exports(kernel,image).items() for name in group}
        reference=Object(obj)
        undefined=sorted({symbol['name'] for symbol in reference.symbols if symbol['kind']&0x0e==0 and symbol['kind']&1})
        unresolved=[name for name in undefined if name not in names]
        report['imports']={name:hex(names[name]) for name in undefined if name in names}
        report['unresolved_imports']=unresolved
        info=next(segment for segment in image['segments'] if segment['name']=='__PRELINK_INFO')
        metadata=unserialize_xml(kernel[info['fileoff']:info['fileoff']+info['filesize']])
        report['available_kernel_hid_bases']=[name for name in names if 'IOHIDEventService' in name]
        report['loaded_hid_modules']=[entry['CFBundleIdentifier'] for entry in metadata['_PrelinkInfoDictionary']
            if 'hid' in entry['CFBundleIdentifier'].lower()]
        report['module_constructor_symbol_present']=any(symbol['name']=='__GLOBAL__sub_I_NabuSensorHid.cpp' for symbol in reference.symbols)
        report['class_initialization']='Explicit preModLoad/static_init/postModLoad on the SSC worker'
        report['largest_stack_frame']=max(({'function':row.rsplit('\t',2)[0],'bytes':int(row.rsplit('\t',2)[1])}
            for row in obj.with_suffix('.su').read_text().splitlines()),key=lambda row:row['bytes'])
        assembly=subprocess.run(host_command(['llvm-objdump-18','-d',host_path(obj)]),capture_output=True,check=True).stdout.decode()
        (output/'NabuSensorHid.asm').write_text(assembly,encoding='utf-8')
        fp_lines=[line for line in assembly.splitlines() if '\t' in line and re.search(r'\b[vsdq][0-9]+\b',line.split('\t')[-1])]
        report['floating_point_instructions']=fp_lines
        report['passed']=not unresolved and not fp_lines and report['module_constructor_symbol_present']
        if not report['passed']:raise RuntimeError('Sensor-source import/constructor/general-register check failed')
    except Exception as error:
        report.update(passed=False,error=str(error))
        raise
    finally:
        (output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:report[key] for key in ['passed','compiled','unresolved_imports','largest_stack_frame','loaded_hid_modules','native_hid_published']},indent=2))


if __name__=='__main__':main()
