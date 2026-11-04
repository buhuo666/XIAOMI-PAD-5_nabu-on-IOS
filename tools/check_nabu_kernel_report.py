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
    for i, (base, reason, code, valid_video, log_case) in enumerate([
            (0x181448000, 2, 12, True, 'empty'), (0x204000, 1, 0x96000004, True, 'valid'),
            (0x281448000, 2, 5, False, 'empty'), (0x181448000, 0, 0, True, 'long'),
            (0x181448000, 0, 0, True, 'below-window'),
            (0x181448000, 0, 0, True, 'past-window'),
            (0x181448000, 0, 0, True, 'oversize'),
            (0x181448000, 0, 0, True, 'overflow'),
            (0x181448000, 0, 0, True, 'desktop'),
            (0x181448000, 0, 0, True, 'desktop-empty'),
            (0x181448000, 0, 0, True, 'desktop-wrap'),
            (0x181448000, 0, 0, True, 'desktop-stacks'),
            (0x181448000, 0, 0, True, 'desktop-twelve-stacks'),
            (0x181448000, 0, 0, True, 'desktop-stack-overflow'),
            (0x181448000, 0, 0, True, 'desktop-two-process-stacks'),
            (0x181448000, 0, 0, True, 'desktop-multiprocess-stacks'),
            (0x181448000, 0, 0, True, 'desktop-repeat-sample-stacks'),
            (0x181448000, 0, 0, True, 'desktop-header-capacity-stacks'),
            (0x181448000, 0, 0, True, 'desktop-multiheader-overflow-stacks'),
            (0x181448000, 0, 0, True, 'desktop-no-header-stacks')]):
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
        owned, owned_bytes, log_address, log_length = 0x180000000, 0x2000000, 0x180bc0000, 0
        log_data = b''
        expected_stack_rows = None
        if log_case in ('valid', 'long'):
            prefix = b'line\r\n' * (12000 if log_case == 'long' else 80)
            if log_case == 'long':
                prefix = (b'--- loader_return_after expired ---\n--- panic buffer ---\n'
                          b'return_panic: the panic that was asked for, on cpu 7\n') + prefix
            log_data = prefix + b'wrapped: ' + b'x' * 400 + b'\x01\r\nPANIC: root device not available\n'
            if log_case == 'valid':
                # Incomplete patterns at the mapped end must not match or overread.
                log_data += b'--- loader_return_after expire'
            log_length = len(log_data)
            uc.mem_map(log_address, (log_length+4095) & ~4095)
            uc.mem_write(log_address, log_data)
        elif log_case == 'below-window': log_address,log_length = owned-1,1
        elif log_case == 'past-window': log_address,log_length = owned+owned_bytes-8,9
        elif log_case == 'oversize': log_length = 1536*1024+1
        elif log_case == 'overflow': owned,owned_bytes,log_length = (1<<64)-0x1000,0x2000,16
        elif log_case.startswith('desktop'):
            log_data=b'--- loader_return_after expired ---\n'
            if 'stack' in log_case:
                log_data+=(b'nabu_diag init args=ustacks=SpringBoard backboardd\n'
                           b'com.apple.xpc.launchd <Notice>: boot-args = -v ustacks=SpringBoard backboardd\n')
            if log_case != 'desktop-empty':
                log_data+=(b'SpringBoard: first event\nbackboardd: first event\nrunningboardd: first event\n'
                           b'MiniIOMobileFramebuffer: first display\ndyld: cache is available\n')
                log_data+=b'process lsd denied CPU monitor request\n'*2000
                if log_case=='desktop-wrap':log_data+=b'SpringBoard: '+b'x'*400+b'\x01\r\n'
                log_data+=(b'SpringBoard: last event\nbackboardd: last event\nrunningboardd: last event\n'
                           b'MiniIOSurface: last display\n')
            if log_case=='desktop-stacks':
                log_data+=(b'ustacks: backboardd[8] 2 threads, shared cache slide 0x10000\n'
                           b'[ 113.428460]: ustacks: backboardd[8] 2 threads, shared cache slide 0x10000\n'
                           b'ustacks: thread render-server: 0x111 0x222\n'
                           b'[ 113.428503]: ustacks: thread render-server: 0x111 0x222\n'
                           b'ustacks: thread sync: 0x333 0x444\n'
                           b'nabu_diag expired args=ustacks=SpringBoard backboardd\n')
            elif log_case in ('desktop-twelve-stacks', 'desktop-stack-overflow'):
                stack_header='ustacks: SpringBoard[5] 12 threads, shared cache slide 0x12340000'
                stack_text=[f'ustacks:  thread 0x{0x100+t:x}: '+
                            ' '.join(f'0x{0x180000000+t*0x1000+j*4:x}' for j in range(16))
                            for t in range(12 if log_case=='desktop-twelve-stacks' else 16)]
                log_data+=b'ustacks: SpringBoard[5] 12 threads, shared cache slide 0xaaaa0000\n'
                # A header without threads must not change another sample's
                # attribution; repeated plain/kprintf copies consume no slots.
                log_data+=(stack_header+'\n'+'\n'.join(stack_text)+'\n').encode()
                log_data+=('[ 113.428460]: '+stack_header+'\n').encode()
                log_data+=''.join('[ 113.428503]: '+line+'\n' for line in stack_text).encode()
                log_data+=b'ustacks: lsd[99] 0 threads, shared cache slide 0xbbbb0000\n'
                log_data+=(b'nabu_diag expired args=ustacks=SpringBoard backboardd\n'
                           b'com.apple.xpc.launchd <Notice>: boot-args = -v ustacks=SpringBoard backboardd\n')
            elif log_case.endswith('-stacks'):
                header_a='ustacks: lsd[22] 2 threads, shared cache slide 0x10000, uptime 113.100, at 113100000'
                header_b='ustacks: lsd[31] 2 threads, shared cache slide 0x20000, uptime 113.200, at 113200000'
                thread_a='ustacks: thread 0x101: 0x111 0x222'
                thread_b='ustacks: thread 0x102: 0x333 0x444'
                thread_c='ustacks: thread 0x103: 0x555 0x666'
                expected_omitted=False
                between_copies=b''
                if log_case=='desktop-two-process-stacks':
                    # Identical thread text belongs to two different processes.
                    sample_lines=[header_a,thread_a,header_b,thread_a]
                    expected_groups=[(header_a,[thread_a]),(header_b,[thread_a])]
                    expected_expanded=False
                elif log_case=='desktop-multiprocess-stacks':
                    sample_lines=[header_a,thread_a,thread_b,header_b,thread_a,thread_c]
                    expected_groups=[(header_a,[thread_a,thread_b]),(header_b,[thread_a,thread_c])]
                    expected_expanded=True
                elif log_case=='desktop-repeat-sample-stacks':
                    # PID and slide alone are insufficient: sampling time differs.
                    headers=[header_a.replace('113.100',f'{113+t}.100').replace('113100000',str(113100000+t*1000000))
                             for t in range(3)]
                    sample_lines=[line for h in headers for line in (h,thread_a)]
                    expected_groups=[(h,[thread_a]) for h in headers]
                    expected_expanded=True
                elif log_case=='desktop-header-capacity-stacks':
                    # Twelve contexts fit in storage, but only nine complete
                    # two-row headers + two-row threads fit on the screen.
                    headers=[f'ustacks: lsd[{22+t}] 1 threads, shared cache slide 0x{0x10000+t*0x1000:x}, '
                             f'uptime 113.{100+t:03d}, at {113100000+t*1000}, details='+('h'*70) for t in range(12)]
                    long_thread='ustacks: thread 0x101: '+' '.join(f'0x{0x180000000+j*4:x}' for j in range(16))
                    assert all(128<len(h)<=256 for h in headers) and 128<len(long_thread)<=256
                    sample_lines=[line for h in headers for line in (h,long_thread)]
                    expected_groups=[(h,[long_thread]) for h in headers[:9]]
                    expected_expanded=expected_omitted=True
                elif log_case=='desktop-multiheader-overflow-stacks':
                    headers=[f'ustacks: lsd[{22+t}] 1 threads, shared cache slide 0x{0x10000+t*0x1000:x}, '
                             f'uptime 113.{100+t:03d}, at {113100000+t*1000}' for t in range(13)]
                    sample_lines=[line for h in headers for line in (h,thread_a)]
                    expected_groups=[(h,[thread_a]) for h in headers[:12]]
                    expected_expanded=expected_omitted=True
                else:
                    assert log_case=='desktop-no-header-stacks'
                    sample_lines=[header_a,thread_a]
                    # Both real loader boundaries can remove the first part of
                    # a sample. Neither orphan may inherit the previous PID,
                    # nor receive a header encountered later in the fragment.
                    log_data+=(header_b+'\n[... the log between the first 256 KB and the last 1 MB was dropped ...]\n'+
                               thread_a+'\n').encode()
                    between_copies=(header_b+'\n--- kernel message buffer ---\n'+thread_a+'\n').encode()
                    expected_groups=[(None,[thread_a]),(header_a,[thread_a])]
                    expected_expanded=False
                log_data+=('\n'.join(sample_lines)+'\n').encode()
                log_data+=between_copies
                log_data+=''.join('[ 113.999999]: '+line+'\n' for line in sample_lines).encode()
                # This last header deliberately has no thread. It is not the
                # context of any preceding retained sample.
                log_data+=b'ustacks: lsd[99] 0 threads, shared cache slide 0xdead0000, uptime 114.000, at 114000000\n'
                expected_stack_rows=[]
                for h,threads in expected_groups:
                    if h is None:
                        expected_stack_rows.append(('THREAD SAMPLE HEADER NOT CAPTURED',0xffff8000))
                    else:
                        expected_stack_rows.extend((h[at:at+128],0xffffffff) for at in range(0,len(h),128))
                    for line in threads:
                        expected_stack_rows.extend((line[at:at+128],0xffffffff) for at in range(0,len(line),128))
                if expected_omitted:
                    expected_stack_rows.append(('MORE THREAD STACK LINES OMITTED',0xffff8000))
            log_data+=b'NABU USERLAND: phase=7 errno=0\nIO reads=15502 failures=0\nSpringBoar'
            log_length=len(log_data)
            uc.mem_map(log_address,(log_length+4095)&~4095)
            uc.mem_write(log_address,log_data)
        uc.mem_write(config+109*8, struct.pack('<2Q',owned,owned_bytes))
        incoming = [log_address, log_length, reason, code, 0x180448518, 0xdead0000, 0x18044ffff, 0xfffffff008001000]
        reads = {'count':0,'min':1<<64,'max':0}
        if log_data:
            def log_read(_uc, _access, address, size, _value, _data):
                reads['count']+=1
                reads['min']=min(reads['min'],address)
                reads['max']=max(reads['max'],address+size)
            # Include mapped padding so a read just past the declared log is
            # caught even when it remains inside the last mapped page.
            uc.hook_add(unicorn.UC_HOOK_MEM_READ, log_read, begin=log_address,
                        end=log_address+((len(log_data)+4095) & ~4095)-1)
        for n, value in enumerate(incoming):
            uc.reg_write(getattr(arm, f'UC_ARM64_REG_X{n}'), value)
        uc.reg_write(arm.UC_ARM64_REG_PSTATE, 0x3c5)
        # An inaccessible old virtual stack catches accidental pre-switch use.
        uc.reg_write(arm.UC_ARM64_REG_SP, 0xfffffff008001000)
        uc.emu_start(base, base+metadata['symbols']['kernel_report_halt'], timeout=30000000, count=150000000)
        assert uc.reg_read(arm.UC_ARM64_REG_PC) == base+metadata['symbols']['kernel_report_halt']
        assert bytes(uc.mem_read(config, 64)) == struct.pack('<8Q', *incoming)
        assert bytes(uc.mem_read(base-4096,4096)) == bytes(uc.mem_read(base+16384,4096)) == b'G'*4096
        assert bytes(uc.mem_read(fb-4096,4096)) == bytes(uc.mem_read(fb+frame_size,4096)) == b'F'*4096
        frame = bytes(uc.mem_read(fb, frame_size))
        if valid_video:
            assert struct.unpack_from('<I',frame, (height*3//16)*stride)[0] == 0xffff00ff
            assert struct.unpack_from('<I',frame, (height//4)*stride)[0] == 0xff000000
            if log_data:
                assert reads['count'] and reads['min'] >= log_address
                assert reads['max'] <= log_address+log_length
                log_y = height//4 + 12*56
                assert b'\xff\xff\xff\xff' in frame[(log_y+28)*stride:]
                def glyphs_match(label, x, y, scale, color):
                    # Compare every foreground/background pixel of the literal
                    # expected labels; a white pixel alone cannot prove text.
                    for i, char in enumerate(label):
                        glyph = font[ord(char)-32]
                        for gy in range(12):
                            bits = (glyph >> 32) >> (gy*5) if gy < 6 else (glyph & 0xffffffff) >> ((gy-6)*5)
                            for gx in range(6):
                                expected = color if gx < 5 and (bits >> gx) & 1 else 0xff000000
                                for dy in range(scale):
                                    for dx in range(scale):
                                        at = (y+gy*scale+dy)*stride + (x+i*6*scale+gx*scale+dx)*4
                                        assert struct.unpack_from('<I',frame,at)[0] == expected
                suffix = 'YES' if log_case == 'long' or log_case.startswith('desktop') else 'NOT SEEN'
                glyphs_match('TIMER MARKER: '+suffix,24,height//4+10*56,4,0xffffffff)
                glyphs_match('PANIC BUFFER: '+('YES' if log_case=='long' else 'NOT SEEN'),800,height//4+10*56,4,0xffffffff)
                if log_case == 'long':
                    glyphs_match('return_panic: the panic that was asked for, on cpu 7',12,log_y,2,0xffffff00)
                elif log_case.startswith('desktop'):
                    glyphs_match('DESKTOP LOG SUMMARY - HALTED',24,height//4+11*56,4,0xffffffff)
                    glyphs_match('NABU USERLAND: phase=7 errno=0',12,log_y+28,2,0xffffffff)
                    glyphs_match('IO reads=15502 failures=0',12,log_y+56,2,0xffffffff)
                    if expected_stack_rows is not None:
                        stack_y=log_y+(84 if expected_expanded else 252)
                        glyphs_match('THREAD STACK SAMPLES: FIRST 12 DISTINCT LINES',12,stack_y,2,0xffffff00)
                        for row,(line,color) in enumerate(expected_stack_rows):
                            glyphs_match(line,12,stack_y+28*(row+1),2,color)
                        service_y=stack_y+28*(len(expected_stack_rows)+1)
                        if service_y+24<=log_y+40*28:
                            glyphs_match(('SPRINGBOARD' if expected_expanded else 'DISPLAY / SURFACES')+
                                         ': SELECTED LOG LINES',12,service_y,2,0xffffff00)
                        if expected_expanded and service_y+52<=log_y+40*28:
                            glyphs_match('SpringBoard: last event',12,service_y+28,2,0xffffffff)
                        if not expected_expanded:
                            glyphs_match('SPRINGBOARD: SELECTED LOG LINES',12,log_y+84,2,0xffffff00)
                            glyphs_match('SpringBoard: first event',12,log_y+112,2,0xffffffff)
                    elif log_case in ('desktop-twelve-stacks','desktop-stack-overflow'):
                        glyphs_match('THREAD STACK SAMPLES: FIRST 12 DISTINCT LINES',12,log_y+84,2,0xffffff00)
                        glyphs_match(stack_header,12,log_y+112,2,0xffffffff)
                        for t, line in enumerate(stack_text[:12]):
                            assert 128 < len(line) <= 256
                            glyphs_match(line[:128],12,log_y+140+t*56,2,0xffffffff)
                            glyphs_match(line[128:],12,log_y+168+t*56,2,0xffffffff)
                        service_y=log_y+812
                        if log_case=='desktop-stack-overflow':
                            glyphs_match('MORE THREAD STACK LINES OMITTED',12,service_y,2,0xffff8000)
                            service_y+=28
                        glyphs_match('SPRINGBOARD: SELECTED LOG LINES',12,service_y,2,0xffffff00)
                        glyphs_match('SpringBoard: last event',12,service_y+28,2,0xffffffff)
                        glyphs_match('backboardd: last event',12,service_y+84,2,0xffffffff)
                    elif log_case=='desktop-empty':
                        glyphs_match('SPRINGBOARD: SELECTED LOG LINES',12,log_y+84,2,0xffffff00)
                        glyphs_match('NO MATCH IN CAPTURED LOG',12,log_y+112,2,0xffffffff)
                    else:
                        glyphs_match('SPRINGBOARD: SELECTED LOG LINES',12,log_y+84,2,0xffffff00)
                        # This first event is over 64 KiB before the tail.
                        glyphs_match('SpringBoard: first event',12,log_y+112,2,0xffffffff)
                        if log_case in ('desktop','desktop-stacks'):
                            glyphs_match('SpringBoard: last event',12,log_y+140,2,0xffffffff)
                            glyphs_match('backboardd: first event',12,log_y+196,2,0xffffffff)
                            if log_case=='desktop':
                                glyphs_match('dyld: cache is available',12,log_y+448,2,0xffffffff)
                            else:
                                glyphs_match('THREAD STACK SAMPLES: FIRST 12 DISTINCT LINES',12,log_y+252,2,0xffffff00)
                                glyphs_match('ustacks: backboardd[8] 2 threads, shared cache slide 0x10000',12,log_y+280,2,0xffffffff)
                                glyphs_match('ustacks: thread sync: 0x333 0x444',12,log_y+336,2,0xffffffff)
                        else:
                            glyphs_match('>',12+127*12,log_y+168,2,0xffffffff)
                            glyphs_match('SpringBoard: last event',12,log_y+196,2,0xffffffff)
                else:
                    glyphs_match('REQUESTED PANIC LINE NOT SEEN',12,log_y,2,0xffffffff)
            y0, rows = height//4, height-height//4
            crop=frame[y0*stride:(y0+rows)*stride]
            rgb=bytearray(width*rows*3)
            rgb[0::3]=crop[2::4]; rgb[1::3]=crop[1::4]; rgb[2::3]=crop[0::4]
            png(a.output/f'callback-{i}.png',bytes(rgb),width,rows)
        else:
            assert frame == bytes(frame_size)
        results.append({'base':hex(base),'reason':reason,'code':hex(code),'video_valid':valid_video,'log_case':log_case,'passed':True})
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
#define MAX_UINT64 UINT64_MAX
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
 assert(NabuInstallKernelReport(&k,pa,65536,dst,5,video)==33);
 memcpy(slot,"XNULDRST",8);
 assert(NabuInstallKernelReport(&k,pa,65536,dst,0,video)==0&&slot[2]==0&&slot[1]==dst);
 slot[1]=slot[2]=slot[3]=0;
 assert(NabuInstallKernelReport(&k,pa,65536,dst,6,video)==2);
 assert(NabuInstallKernelReport(&k,pa,65536,dst+8,5,video)==2);
 memcpy(ram,"XNULDRST",8);
 assert(NabuInstallKernelReport(&k,pa,65536,dst,5,video)==33);memset(ram,0,8);
 slot[1]=1;assert(NabuInstallKernelReport(&k,pa,65536,dst,5,video)==33);slot[1]=0;
 assert(NabuInstallKernelReport(&k,pa,65536,dst,5,video)==0);
 assert(slot[1]==dst&&slot[2]==5&&slot[3]==pa-k.Base);
 UINT64 *cfg=(UINT64 *)(uintptr_t)(dst+NABU_KERNEL_REPORT_CONFIG);
 assert(memcmp(cfg+8,video,sizeof(video))==0&&cfg[14]==42);
 assert(cfg[109]==pa&&cfg[110]==65536);
 assert(memcmp((void *)(uintptr_t)dst,mNabuKernelReport,NABU_KERNEL_REPORT_CONFIG)==0);
 slot[1]=slot[2]=slot[3]=0;
 assert(NabuInstallKernelReport(&k,pa,65536,dst,12,video)==0&&slot[2]==12);
 slot[1]=slot[2]=slot[3]=0;
 assert(NabuInstallKernelReport(&k,pa,65536,dst,45,video)==2);
 assert(NabuInstallKernelReport(&k,pa,0,dst,12,video)==2);
 assert(NabuInstallKernelReport(&k,pa,65536,pa+65536,12,video)==2);
 assert(NabuInstallKernelReport(&k,UINT64_MAX-16384,65536,dst,12,video)==2);
 free(ram);puts("12 slot binding cases passed");return 0;
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
