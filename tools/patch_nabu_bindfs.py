#!/usr/bin/env python3
"""Select the newly linked bindfs operations without moving the qualified kernel."""
import argparse
import json
from pathlib import Path
import shutil
import struct
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from link_nabu_data_block import Object, signed
from patch_nabu_return_trace import Image


def object_size(path,name):
    obj=Object(path)
    symbol=next(s for s in obj.symbols if s['name']==name and s['kind']&0xe==0xe)
    section=obj.sections[symbol['section']-1]
    ends=[s['value'] for s in obj.symbols if s['kind']&0xe==0xe and s['section']==symbol['section'] and s['value']>symbol['value']]
    return min(ends,default=section['va']+section['size'])-symbol['value']


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel',type=Path,required=True)
    parser.add_argument('--vfs-object',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    a=parser.parse_args()
    data=bytearray(a.kernel.read_bytes()); image=Image(data)
    linked=json.loads(a.kernel.with_name('data-block-link.json').read_text())
    names=linked['jailbreak_bindfs_symbols']
    edits=[]
    def replace(name,address,replacement):
        offset=image.offset(address,len(replacement)); original=bytes(data[offset:offset+len(replacement)])
        data[offset:offset+len(replacement)]=replacement
        edits.append(dict(name=name,address=hex(address),bytes=len(replacement),before=original.hex(),after=replacement.hex()))
    size=object_size(a.vfs_object,'_nabu_bindfs_vfsops')
    assert size%8==0 and 64<=size<=256
    old=image.symbols['_bindfs_vfsops']; new=names['_nabu_bindfs_vfsops']
    original=image.read(old,size); replacement=image.read(new,size)
    # Same version of struct vfsops and the same assigned fields; every pointer
    # slot already belongs to the original kernel's relocation layout.
    before=struct.unpack('<'+'Q'*(size//8),original)
    after=struct.unpack('<'+'Q'*(size//8),replacement)
    assert [i for i,v in enumerate(before) if v]==[i for i,v in enumerate(after) if v]
    replace('bindfs_vfsops',old,replacement)
    old=image.symbols['_bindfs_vnodeop_opv_desc']; new=names['_nabu_bindfs_vnodeop_opv_desc']
    before=struct.unpack('<QQ',image.read(old,16)); after=struct.unpack('<QQ',image.read(new,16))
    assert before[0]==after[0]==image.symbols['_bindfs_vnodeop_p']
    replace('bindfs_vnodeop_descriptor',old,image.read(new,16))
    start=image.symbols['_mmap']
    end=min(address for address in image.symbols.values() if address>start)
    instructions=list(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(image.read(start,end-start),start))
    assert sum(i.size for i in instructions)==end-start
    calls=[]
    for instruction in instructions:
        word,=struct.unpack('<I',instruction.bytes)
        if word&0xfc000000==0x94000000:
            target=instruction.address+signed(word&0x3ffffff,26)*4
            if target==image.symbols['_ubc_getobject']:calls.append(instruction.address)
    assert len(calls)==1, calls
    site=calls[0]; target=names['_nabu_bindfs_mmap_getobject']; delta=target-site
    assert delta%4==0 and -(1<<27)<=delta<(1<<27)
    replacement=struct.pack('<I',0x94000000|((delta//4)&0x3ffffff))
    assert site+signed(struct.unpack('<I',replacement)[0]&0x3ffffff,26)*4==target
    replace('mmap_bindfs_backing_object',site,replacement)
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'kernel.native-apfs.macho').write_bytes(data)
    for name in ['data-block-link.json','prelink-report.json']:
        shutil.copyfile(a.kernel.with_name(name),a.output/name)
    report=dict(source_kernel=str(a.kernel),edits=edits,bindfs_symbols=names,vfsops_bytes=size,
        original_ubc_getobject_preserved=True,original_operation_vector_storage_preserved=True,
        kernel_bytes=len(data),device_executed=False)
    (a.output/'bindfs-patch.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'edits':len(edits),'vfsops_bytes':size,'device_executed':False}))


if __name__=='__main__':main()
