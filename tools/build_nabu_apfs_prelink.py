#!/usr/bin/env python3
"""Locally prelink the original 20F66 APFS dependency closure into a source kernel."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/XnuPrelink'))
from emit_prelink import emit
from native_prelink import macho

def reserve_usb_driver_data(image,report,extra=0x20000):
    # Including the stock mux leaves only 44 KiB after its DATA extent. The
    # Data/Power/USB module needs more space; keep every original VA fixed.
    b=bytearray(image);parsed=macho(b)
    data=next(s for s in parsed['segments'] if s['name']=='__PRELINK_DATA')
    assert extra > 0 and extra % 0x4000 == 0
    cut=data['fileoff']+data['filesize']
    assert data['size']==data['filesize']
    assert data['va']+data['size']==max(s['va']+s['size'] for s in parsed['segments'] if s['size'] and s['name']!='__PRELINK_INFO')
    b[cut:cut]=bytes(extra)
    for segment in parsed['segments']:
        if segment['filesize'] and segment['fileoff']>=cut:
            struct.pack_into('<Q',b,segment['command_offset']+40,segment['fileoff']+extra)
        for section in segment['sections']:
            if section['fileoff']>=cut and section['fileoff']:
                struct.pack_into('<I',b,section['command_offset']+48,section['fileoff']+extra)
    struct.pack_into('<Q',b,data['command_offset']+32,data['size']+extra)
    struct.pack_into('<Q',b,data['command_offset']+48,data['filesize']+extra)
    tail=data['sections'][-1]
    assert tail['va']+tail['size']==data['va']+data['size']
    struct.pack_into('<Q',b,tail['command_offset']+40,tail['size']+extra)
    previous=report.get('usb_driver_data_reservation',{}).get('additional_bytes',0)
    report['usb_driver_data_reservation']={'additional_bytes':previous+extra,'existing_virtual_addresses_changed':False}
    return bytes(b)


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
    ap.add_argument('--apple-usb',action='store_true',help='Include the stock USB device family and AppleUSBDeviceMux dependency closure')
    ap.add_argument('--fairplay',action='store_true',help='Include the stock FairPlayIOKit service required by fairplayd.A2')
    a=ap.parse_args()
    original=a.original.read_bytes();native=a.kernel.read_bytes()
    n,o=macho(native),macho(original)
    end=max(s['va']+s['size'] for s in n['segments'] if s['size'])
    base=next(s['va'] for s in o['segments'] if s['name']=='__PRELINK_TEXT')
    slide=((end+0x400000+0x3fff)&~0x3fff)-base
    roots=['com.apple.filesystems.apfs']
    if a.apple_usb: roots.append('com.apple.driver.AppleUSBDeviceMux')
    if a.fairplay: roots.append('com.apple.driver.FairPlayIOKit')
    if a.fairplay:
        from nabu_fairplay_bindings import emit_with_fairplay
        image,report=emit_with_fairplay(native,original,roots,slide)
    else:
        image,report=emit(native,original,roots,slide)
    if a.apple_usb: image=reserve_usb_driver_data(image,report)
    image=place_prelink_info_last(image,report)
    assert not a.output.exists();a.output.mkdir(parents=True)
    target=a.output/'kernel.native-apfs.macho';target.write_bytes(image)
    report.update(kernel_source_path=str(a.kernel.resolve()),original_path=str(a.original.resolve()),
        requested_roots=roots,stock_apple_usb_included=a.apple_usb,stock_fairplay_included=a.fairplay,
        bootarg='nabu-native-apfs=1',candidate_bytes=len(image),runtime_qualified=False,
        scope='Original executable bytes retained; explicit relocations and closure checks only; no APFS write or device claim')
    (a.output/'prelink-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['bindings','extents','appended_segments']},indent=2))

if __name__=='__main__':main()
