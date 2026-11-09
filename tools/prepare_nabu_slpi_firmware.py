#!/usr/bin/env python3
"""Package nabu's original relocatable slpi_nb image; never write a device."""
import argparse
import json
from pathlib import Path
import shutil
import struct


def inspect(firmware):
    data=(firmware/'slpi_nb.mdt').read_bytes()
    if len(data)<52 or data[:7]!=b'\x7fELF\x01\x01\x01':
        raise ValueError('Expected original ELF32 little-endian MDT')
    h=struct.unpack_from('<16sHHIIIIIHHHHHH',data)
    if h[8]!=52 or h[9]!=32 or not 1<=h[10]<=32 or h[5]+h[10]*32>len(data) or len(data)>16384:
        raise ValueError('Invalid MDT program-header table')
    records=[]
    for i in range(h[10]):
        kind,off,va,pa,filesz,memsz,flags,align=struct.unpack_from('<8I',data,h[5]+i*32)
        if kind!=1 or not memsz or (flags>>24)&7==2:
            continue
        if filesz>memsz or pa+memsz>0xffffffff:
            raise ValueError(f'Invalid segment {i}')
        records.append(dict(index=i,original_physical=pa,file_bytes=filesz,memory_bytes=memsz,flags=flags))
    if not records:
        raise ValueError('No load segments')
    base,limit=0x97b00000,0x98f00000
    low=min(s['original_physical'] for s in records)
    relocated=any(s['flags']&0x08000000 for s in records)
    for s in records:
        s['physical']=base+s['original_physical']-low if relocated else s['original_physical']
        if not base<=s['physical']<limit or s['physical']+s['memory_bytes']>limit:
            raise ValueError(f'Segment {s["index"]} does not fit original SLPI reserved memory')
        s['file']=f'slpi_nb.b{s["index"]:02}' if s['file_bytes'] else None
        if s['file'] and (firmware/s['file']).stat().st_size!=s['file_bytes']:
            raise ValueError(f'Wrong segment length: {s["file"]}')
    ordered=sorted(records,key=lambda s:s['physical'])
    for a,b in zip(ordered,ordered[1:]):
        if a['physical']+a['memory_bytes']>b['physical']:
            raise ValueError('Overlapping load segments')
    return dict(schema=1,metadata='slpi_nb.mdt',pas_id=12,base=base,reserved_bytes=limit-base,
                original_link_base=low,relocated=relocated,relocation_delta=base-low if relocated else 0,
                segments=records,file_bytes=sum(s['file_bytes'] for s in records),
                memory_end=max(s['physical']+s['memory_bytes'] for s in records),
                source=str(firmware),runtime_verified=False,sensor_pd_started=False,
                limit='Root-PD boot inputs only; FastRPC sensor_pd and registry services remain required.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();report=inspect(a.firmware)
    a.output.mkdir(parents=True,exist_ok=False)
    shutil.copy2(a.firmware/'slpi_nb.mdt',a.output/'slpi_nb.mdt')
    for s in report['segments']:
        if s['file']:shutil.copy2(a.firmware/s['file'],a.output/s['file'])
    (a.output/'firmware.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
