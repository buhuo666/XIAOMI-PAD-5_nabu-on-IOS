#!/usr/bin/env python3
"""Wire a linked exec-injection object into the qualified kernel, offline only."""
import argparse
import json
from pathlib import Path
import shutil
import struct

from build_nabu_exec_injection import full_symbols


def segments(data):
    assert struct.unpack_from('<I',data)[0] == 0xfeedfacf
    at=32; result=[]
    for _ in range(struct.unpack_from('<I',data,16)[0]):
        cmd,size=struct.unpack_from('<II',data,at)
        if cmd==0x19:
            va,length,offset,filesize=struct.unpack_from('<4Q',data,at+24)
            result.append((va,length,offset,filesize))
        at+=size
    return result


def file_offset(data,address,size):
    values=[offset+address-va for va,length,offset,filesize in segments(data)
            if va<=address and address+size<=va+filesize]
    assert len(values)==1, (hex(address),size,values)
    return values[0]


def read(data,address,size):
    offset=file_offset(data,address,size)
    return data[offset:offset+size]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kernel',type=Path,required=True,help='New DataBlock link output')
    p.add_argument('--qualified-kernel',type=Path,required=True,help='Currently qualified unmodified core')
    p.add_argument('--objects',type=Path,required=True,help='build_nabu_exec_injection output')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    data=bytearray(a.kernel.read_bytes()); qualified=a.qualified_kernel.read_bytes()
    binding=json.loads((a.objects/'binding-report.json').read_text())
    old=full_symbols(qualified); existing=full_symbols(data)
    for name,address in binding['original_symbols'].items():
        assert old[name]==existing[name]==address, name
    linked=json.loads(a.kernel.with_name('data-block-link.json').read_text())
    names={name:linked['imports'][name] for name in
           ('_nabu_exec_extract_strings','_nabu_exec_inject_conf','_nabu_exec_injection_abi')}
    abi=struct.unpack('<10I',read(data,names['_nabu_exec_injection_abi'],40))
    oid_size,arg1,arg2,name_at,handler_at,capacity,imgsize,ndp,argspace,envc=abi
    assert (oid_size,arg1,arg2,name_at,handler_at,capacity)==(80,24,32,40,48,4096),abi
    oid=old['_sysctl__kern_exec_inject']
    assert struct.unpack('<Q',read(data,oid+arg1,8))[0]==old['_exec_inject_conf']
    assert struct.unpack('<I',read(data,oid+arg2,4))[0]==512
    name=struct.unpack('<Q',read(data,oid+name_at,8))[0]
    assert read(data,name,12)==b'exec_inject\0'
    handler=struct.unpack('<Q',read(data,oid+handler_at,8))[0]
    assert handler==old['_sysctl_handle_string']
    assert read(data,names['_nabu_exec_inject_conf'],capacity)==bytes(capacity)
    start=old['_exec_extract_strings']
    end=min(value for value in old.values() if value>start)
    assert read(data,start,end-start)==read(qualified,start,end-start)
    target=names['_nabu_exec_extract_strings']; delta=target-start
    assert delta%4==0
    if -(1<<27)<=delta<(1<<27):
        word=0x14000000|((delta//4)&0x3ffffff)
        decoded=word&0x3ffffff
        if decoded&(1<<25): decoded-=1<<26
        assert start+decoded*4==target
        entry=struct.pack('<I',word); entry_kind='B'
    else:
        # Tail transfer at a function entry: x16 is the AAPCS64 scratch
        # register, arguments and the caller's link register stay intact.
        pages=((target&~4095)-(start&~4095))//4096
        assert -(1<<20)<=pages<(1<<20)
        adrp=0x90000010|((pages&3)<<29)|(((pages>>2)&0x7ffff)<<5)
        add=0x91000210|((target&4095)<<10)
        entry=struct.pack('<3I',adrp,add,0xd61f0200); entry_kind='ADRP x16; ADD x16; BR x16'
        decoded=((adrp>>5&0x7ffff)<<2)|(adrp>>29&3)
        if decoded&(1<<20): decoded-=1<<21
        assert (start&~4095)+decoded*4096+((add>>10)&4095)==target
    edits=[]
    def replace(label,address,value):
        offset=file_offset(data,address,len(value))
        original=bytes(data[offset:offset+len(value)])
        data[offset:offset+len(value)]=value
        edits.append(dict(name=label,address=hex(address),file_offset=offset,
                          before=original.hex(),after=value.hex()))
    replace('exec_extract_strings_entry',start,entry)
    replace('exec_inject_configuration_storage',oid+arg1,struct.pack('<Q',names['_nabu_exec_inject_conf']))
    replace('exec_inject_configuration_capacity',oid+arg2,struct.pack('<I',capacity))
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'kernel.native-apfs.macho').write_bytes(data)
    for name in ['data-block-link.json','prelink-report.json']:
        shutil.copyfile(a.kernel.with_name(name),a.output/name)
    for name in ['return-trace-patch.json','return-trace-disassembly.txt']:
        if a.kernel.with_name(name).is_file():
            shutil.copyfile(a.kernel.with_name(name),a.output/name)
    report=dict(edits=edits,original_symbols=binding['original_symbols'],linked_symbols=names,
                source_argument_body_preserved=True,original_core_function_bytes_verified=end-start,
                sysctl_handler_and_flags_preserved=True,config_initially_empty=True,
                configuration_capacity=capacity,injected_environment_capacity=512,
                entry_transfer=entry_kind,
                compiled_image_params_abi=dict(size=imgsize,ndp=ndp,argspace=argspace,envc=envc),
                device_executed=False,loader_checks_still_required=True)
    (a.output/'exec-injection-patch.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(edits=len(edits),configuration_capacity=capacity,device_executed=False)))


if __name__=='__main__': main()
