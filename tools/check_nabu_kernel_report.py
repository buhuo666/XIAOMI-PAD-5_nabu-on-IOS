#!/usr/bin/env python3
"""Exercise the actual slot binder and compiled screen callback without hardware."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import zlib
from check_darwinboot_8796 import host_command, host_path
from check_nabu_handoff import function

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'build/host-tools/capacity'))
import unicorn
from unicorn import arm64_const as arm


def png(path, pixels, width, height):
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag+data))
    raw = b''.join(b'\0'+pixels[i*width*3:(i+1)*width*3] for i in range(height))
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
                     +chunk(b'IDAT', zlib.compress(raw))+chunk(b'IEND', b''))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--blob-work', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((a.blob_work/'report.json').read_text())
    blob = (a.blob_work/'report.bin').read_bytes()
    assert hashlib.sha256(blob).hexdigest() == metadata['blob_sha256']
    for item in metadata['inputs']:
        assert hashlib.sha256((ROOT/'patches/darwinboot'/Path(item['path']).name).read_bytes()).hexdigest() == item['sha256']
    font = [int(n, 16) for n in re.findall(r'0x([0-9A-Fa-f]{16})',
             (ROOT/'src/DarwinBoot/DarwinBootPkg/Driver/DiagFont.h').read_text())][:95]
    assert len(font) == 95
    fb, width, height, stride = 0x9c000000, 1600, 2560, 6400
    frame_size = stride * height
    results = []
    for i, (base, reason, code, valid_video) in enumerate([
            (0x181448000, 2, 12, True), (0x204000, 1, 0x96000004, True),
            (0x281448000, 2, 5, False)]):
        uc = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        uc.mem_map(base-4096, 16384+8192)
        uc.mem_write(base-4096, b'G'*4096)
        uc.mem_write(base+16384, b'G'*4096)
        uc.mem_write(base, blob)
        uc.mem_map(fb-4096, frame_size+8192)
        uc.mem_write(fb-4096, b'F'*4096)
        uc.mem_write(fb+frame_size, b'F'*4096)
        config = base + metadata['symbols']['kernel_report_config']
        video = [fb, 1, stride, width, height, 32 if valid_video else 16]
        uc.mem_write(config+64, struct.pack('<6Q95Q', *video, *font))
        incoming = [0x180bc0000, 0, reason, code, 0x180448518, 0xdead0000, 0x18044ffff, 0xfffffff008001000]
        for n, value in enumerate(incoming):
            uc.reg_write(getattr(arm, f'UC_ARM64_REG_X{n}'), value)
        uc.reg_write(arm.UC_ARM64_REG_PSTATE, 0x3c5)
        # An inaccessible old virtual stack catches accidental pre-switch use.
        uc.reg_write(arm.UC_ARM64_REG_SP, 0xfffffff008001000)
        uc.emu_start(base, base+metadata['symbols']['kernel_report_halt'], timeout=30000000, count=100000000)
        assert uc.reg_read(arm.UC_ARM64_REG_PC) == base+metadata['symbols']['kernel_report_halt']
        assert bytes(uc.mem_read(config, 64)) == struct.pack('<8Q', *incoming)
        assert bytes(uc.mem_read(base-4096,4096)) == bytes(uc.mem_read(base+16384,4096)) == b'G'*4096
        assert bytes(uc.mem_read(fb-4096,4096)) == bytes(uc.mem_read(fb+frame_size,4096)) == b'F'*4096
        frame = bytes(uc.mem_read(fb, frame_size))
        if valid_video:
            assert struct.unpack_from('<I',frame, (height*3//16)*stride)[0] == 0xffff00ff
            assert struct.unpack_from('<I',frame, (height//4)*stride)[0] == 0xff000000
            y0, rows = height//4, 672
            crop=frame[y0*stride:(y0+rows)*stride]
            rgb=bytearray(width*rows*3)
            rgb[0::3]=crop[2::4]; rgb[1::3]=crop[1::4]; rgb[2::3]=crop[0::4]
            png(a.output/f'callback-{i}.png',bytes(rgb),width,rows)
        else:
            assert frame == bytes(frame_size)
        results.append({'base':hex(base),'reason':reason,'code':hex(code),'video_valid':valid_video,'passed':True})
    # Compile the exact production binder, with bounded host-owned stand-ins.
    prelude = r'''
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
typedef uint64_t UINT64; typedef uint32_t UINT32; typedef uint8_t UINT8;
typedef size_t UINTN; typedef int EFI_STATUS;
#define STATIC static
#define CONST const
#define VOID void
#define SIZE_16KB 16384
#define EFI_SUCCESS 0
#define EFI_INVALID_PARAMETER 2
#define EFI_COMPROMISED_DATA 33
#define CompareMem memcmp
#define CopyMem memcpy
static UINT64 U64(const void *p){UINT64 v;memcpy(&v,p,8);return v;}
typedef struct {UINT64 Address,FileSize;} SEGMENT;
typedef struct {UINT64 Base; UINTN Count; SEGMENT Segments[2];} KERNEL;
static const UINT64 mDiagFont[95]={42};
'''
    header = (ROOT/'patches/darwinboot/NabuHandoff.h').read_text()
    binder = function(header, 'NabuInstallKernelReport')
    defines = header[:header.index('typedef struct')]
    test = prelude + defines + (a.blob_work/'NabuKernelReportBlob.h').read_text() + binder + r'''
int main(void){
 unsigned char *ram=aligned_alloc(16384,65536);assert(ram);memset(ram,0,65536);
 UINT64 pa=(UINT64)(uintptr_t)ram, dst=pa+16384, video[6]={1,2,3,4,5,6};
 KERNEL k={.Base=0xfffffff007004000ULL,.Count=1,.Segments={{0xfffffff007004000ULL,4096}}};
 UINT64 *slot=(UINT64 *)(ram+4096-32);
 assert(NabuInstallKernelReport(&k,pa,dst,5,video)==33);
 memcpy(slot,"XNULDRST",8);
 assert(NabuInstallKernelReport(&k,pa,dst,0,video)==2);
 assert(NabuInstallKernelReport(&k,pa,dst,6,video)==2);
 assert(NabuInstallKernelReport(&k,pa,dst+8,5,video)==2);
 memcpy(ram,"XNULDRST",8);
 assert(NabuInstallKernelReport(&k,pa,dst,5,video)==33);memset(ram,0,8);
 slot[1]=1;assert(NabuInstallKernelReport(&k,pa,dst,5,video)==33);slot[1]=0;
 assert(NabuInstallKernelReport(&k,pa,dst,5,video)==0);
 assert(slot[1]==dst&&slot[2]==5&&slot[3]==pa-k.Base);
 UINT64 *cfg=(UINT64 *)(uintptr_t)(dst+NABU_KERNEL_REPORT_CONFIG);
 assert(memcmp(cfg+8,video,sizeof(video))==0&&cfg[14]==42);
 assert(memcmp((void *)(uintptr_t)dst,mNabuKernelReport,NABU_KERNEL_REPORT_CONFIG)==0);
 slot[1]=slot[2]=slot[3]=0;
 assert(NabuInstallKernelReport(&k,pa,dst,12,video)==0&&slot[2]==12);
 slot[1]=slot[2]=slot[3]=0;
 assert(NabuInstallKernelReport(&k,pa,dst,45,video)==2);
 free(ram);puts("9 slot binding cases passed");return 0;
}
'''
    src, exe = a.output/'binder.c', a.output/'binder'
    src.write_text(test)
    subprocess.run(host_command(['clang','-std=c11','-O1','-g','-fsanitize=address,undefined',host_path(src),'-o',host_path(exe)]),check=True)
    binder_output = subprocess.check_output(host_command([host_path(exe)]),text=True).strip()
    report = {'passed':True,'blob_sha256':metadata['blob_sha256'],'emulator_cases':results,
              'binder':binder_output,'scope':'callback and slot binder only; no claim of device MMU behavior'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
