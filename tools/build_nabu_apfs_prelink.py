#!/usr/bin/env python3
"""Locally prelink the original 20F66 APFS dependency closure into a source kernel."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/XnuPrelink'))
from emit_prelink import emit
from native_prelink import macho

def place_prelink_info_last(image,report):
    # 8796 derives vm_kernel_slid_top from the end of __PRELINK_INFO. The
    # upstream emitter places it after the source kernel, below appended kexts.
    # Relocate this data-only segment to encompass the complete static image.
    b=bytearray(image);parsed=macho(b)
    info=next(s for s in parsed['segments'] if s['name']=='__PRELINK_INFO')
    end=max(s['va']+s['size'] for s in parsed['segments'] if s['name']!='__PRELINK_INFO' and s['size'])
    new=(end+0x3fff)&~0x3fff;old=info['va']
    struct.pack_into('<Q',b,info['command_offset']+24,new)
    for section in info['sections']:
        struct.pack_into('<Q',b,section['command_offset']+32,section['va']+new-old)
    report['prelink_info_relocation']={'old_va':hex(old),'new_va':hex(new),'bytes':info['size'],
        'reason':'8796 static slide range must cover every prelinked component'}
    report['candidate_sha256']=hashlib.sha256(b).hexdigest()
    return bytes(b)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel',type=Path,required=True)
    ap.add_argument('--original',type=Path,default=ROOT/'OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.arm64.macho')
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args()
    original=a.original.read_bytes();native=a.kernel.read_bytes()
    assert hashlib.sha256(original).hexdigest()=='600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2'
    source=ROOT/'src/XnuPrelink'
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()=='2b6ffb50117eee820b98aca9bd51b5c7dfb2970e'
    assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain'])
    n,o=macho(native),macho(original)
    end=max(s['va']+s['size'] for s in n['segments'] if s['size'])
    base=next(s['va'] for s in o['segments'] if s['name']=='__PRELINK_TEXT')
    slide=((end+0x400000+0x3fff)&~0x3fff)-base
    image,report=emit(native,original,['com.apple.filesystems.apfs'],slide)
    image=place_prelink_info_last(image,report)
    assert not a.output.exists();a.output.mkdir(parents=True)
    target=a.output/'kernel.native-apfs.macho';target.write_bytes(image)
    report.update(kernel_source_path=str(a.kernel.resolve()),original_path=str(a.original.resolve()),
        bootarg='nabu-native-apfs=1',candidate_bytes=len(image),runtime_qualified=False,
        scope='Original executable bytes retained; explicit relocations and closure checks only; no APFS write or device claim')
    (a.output/'prelink-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['bindings','extents','appended_segments']},indent=2))

if __name__=='__main__':main()
