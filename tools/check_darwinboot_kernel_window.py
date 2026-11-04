#!/usr/bin/env python3
"""Exercise the actual loader parser and final layout guard, without booting."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from check_nabu_handoff import function
from check_darwinboot_8796 import host_command, host_path


def fixture(data_size=512*1024*1024, base=0xfffffff007004000):
    def segment(name, va, size, offset, backed, prot):
        return struct.pack('<II16sQQQQiiII', 0x19, 72, name, va, size,
                           offset, backed, prot, prot, 0, 0)
    thread = bytearray(288)
    struct.pack_into('<IIII', thread, 0, 5, 288, 6, 68)
    struct.pack_into('<Q', thread, 272, base+1024)
    commands = (segment(b'__TEXT', base, 16384, 0, 16384, 5) +
                segment(b'__DATA', base+16384, data_size, 16384, 0, 3) + thread)
    header = struct.pack('<8I', 0xfeedfacf, 0x100000c, 0, 2, 3, len(commands), 0, 0)
    return bytearray((header+commands).ljust(16384, b'\0'))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--kernel', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    source = (a.tree/'DarwinBootPkg/Driver/DarwinBoot.c').read_text()
    window = (a.tree/'DarwinBootPkg/Driver/WindowSize.h').read_text()
    types = source[source.index('#define WINDOW_SIZE'):source.index('STATIC EFI_HANDLE')]
    layout = source[source.index('  ArgsAddress = ALIGN_VALUE'):source.index('  ZeroMem ((VOID *)(UINTN)Address')]
    prelude = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <inttypes.h>
typedef uint64_t UINT64;
typedef uint32_t UINT32;
typedef uint8_t UINT8;
typedef size_t UINTN;
typedef int BOOLEAN, EFI_STATUS;
#define STATIC static
#define CONST const
#define VOID void
#define TRUE 1
#define FALSE 0
#define EFI_SUCCESS 0
#define EFI_UNSUPPORTED 3
#define EFI_LOAD_ERROR 1
#define EFI_BAD_BUFFER_SIZE 4
#define MAX_UINT64 UINT64_MAX
#define SIZE_256MB 0x10000000ULL
#define SIZE_2MB 0x200000ULL
#define SIZE_16KB 0x4000ULL
#define EFI_PAGE_SIZE 4096ULL
#define EFI_PAGE_MASK 4095ULL
#define NABU_KERNEL_REPORT_RESERVE 16384U
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define ALIGN_VALUE(x,a) (((x)+(a)-1)&~((a)-1))
#define ZeroMem(p,n) memset((p),0,(n))
#define Print(...) ((void)0)
static UINT32 U32(const void *p){UINT32 v;memcpy(&v,p,4);return v;}
static UINT64 U64(const void *p){UINT64 v;memcpy(&v,p,8);return v;}
'''
    code = prelude + window + types + function(source, 'ParseKernel')
    code += r'''
static int fits(KERNEL Kernel, UINT64 WindowSize, UINT64 *used) {
  UINT64 Address=0x180004000ULL, ArgsAddress,TreeAddress,RamdiskAddress;
  UINT64 RamdiskBytes,TrustCacheAddress,AddonAddress,Used;
  UINT64 TreeSize=16384,RamdiskExpandedSize=8*1024*1024,TrustCacheSize=0,AddonSize=0;
  BOOLEAN KeepPacked=FALSE;
  struct { UINT64 RamdiskSize; } request={8*1024*1024}, *Request=&request;
  struct { BOOLEAN Enabled; UINT64 ReportAddress; } Nabu={TRUE,0};
  EFI_STATUS Status=EFI_SUCCESS;
'''
    code += layout + r'''
  *used=Used;return EFI_SUCCESS;
Fail:
  *used=Used;return Status;
}
int main(int argc,char **argv){
  assert(argc==3);FILE *f=fopen(argv[1],"rb");assert(f);
  assert(!fseek(f,0,SEEK_END));long length=ftell(f);assert(length>=0);
  rewind(f);UINT8 *bytes=malloc((size_t)length+1);assert(bytes);
  assert(fread(bytes,1,(size_t)length,f)==(size_t)length);fclose(f);
  KERNEL k;int status=ParseKernel(bytes,(size_t)length,&k);free(bytes);
  assert(status==atoi(argv[2]));
  if(status){printf("{\"status\":%d}\n",status);return 0;}
  UINT64 used=0;assert(fits(k,0x1f9000000ULL,&used)==EFI_SUCCESS);
  UINT64 rounded=ALIGN_VALUE(used,SIZE_2MB);
  assert(fits(k,rounded+SIZE_2MB,&used)==EFI_SUCCESS);
  assert(fits(k,rounded,&used)==EFI_BAD_BUFFER_SIZE);
  if(k.End-k.Base>SIZE_256MB)assert(fits(k,SIZE_256MB,&used)==EFI_BAD_BUFFER_SIZE);
  printf("{\"status\":0,\"base\":\"0x%" PRIx64 "\",\"span_bytes\":%" PRIu64 ",\"used_bytes\":%" PRIu64 "}\n",k.Base,k.End-k.Base,used);
  return 0;
}
'''
    c, exe = a.output/'actual-kernel-window.c', a.output/'actual-kernel-window'
    c.write_text(code, newline='\n')
    subprocess.run(host_command(['clang', '-std=c11', '-O1', '-g', '-fsanitize=address,undefined',
                                host_path(c), '-o', host_path(exe)]), check=True)
    cases = [('small', fixture(16*1024*1024), 0), ('512m-bss', fixture(), 0)]
    cases += [('segment-too-large', fixture(0x300000001), 1),
              ('span-too-large', fixture(0x300000000), 1),
              ('address-overflow', fixture(512*1024*1024, 0xffffffffff000000), 1)]
    b = fixture();struct.pack_into('<Q', b, 104+24, 0xfffffff007006000)
    cases.append(('overlap', b, 1))
    b = fixture();struct.pack_into('<Q', b, 176+272, 0xfffffff007008000)
    cases.append(('non-executable-entry', b, 1))
    b = fixture();struct.pack_into('<Q', b, 104+48, 512*1024*1024+1)
    cases.append(('backed-exceeds-size', b, 1))
    b = fixture();struct.pack_into('<Q', b, 104+40, 16385)
    cases.append(('file-offset', b, 1))
    cases += [('truncated-header', fixture()[:31], 3),
              ('truncated-command', fixture()[:128], 1)]
    rows = []
    for name, data, expected in cases:
        path = a.output/(name+'.macho');path.write_bytes(data)
        result = subprocess.check_output(host_command([host_path(exe), host_path(path), str(expected)]), text=True)
        rows.append({'name': name, **json.loads(result)})
    if a.kernel:
        result = subprocess.check_output(host_command([host_path(exe), host_path(a.kernel), '0']), text=True)
        rows.append({'name': 'candidate', 'sha256': hashlib.sha256(a.kernel.read_bytes()).hexdigest(),
                     **json.loads(result)})
    report = {'passed': True, 'scope': 'actual parser and final layout guard under ASan/UBSan; no firmware allocation or device boot',
              'loader_sha256': hashlib.sha256(source.encode()).hexdigest(),
              'harness_sha256': hashlib.sha256(code.encode()).hexdigest(), 'cases': rows}
    (a.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
