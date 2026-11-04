#!/usr/bin/env python3
"""Execute the actual ADT parser and allocator against adversarial host maps."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from check_darwinboot_8796 import host_command, host_path
from make_nabu_adt import make_tree


def function(source, name):
    start = source.index('\n' + name + ' (')
    start = source.rfind('\nSTATIC', 0, start)
    body = source.index('{', start)
    depth = 1
    end = body + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    source = (a.tree/'DarwinBootPkg/Driver/DarwinBoot.c').read_text()
    header = (a.tree/'DarwinBootPkg/Driver/NabuHandoff.h').read_text().split('STATIC EFI_STATUS')[0]
    window = (a.tree/'DarwinBootPkg/Driver/WindowSize.h').read_text()
    blob = make_tree(bytes(range(64))).encode()
    prelude = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <assert.h>
typedef uint64_t UINT64,EFI_PHYSICAL_ADDRESS;
typedef uint32_t UINT32;
typedef uint8_t UINT8;
typedef size_t UINTN;
typedef char CHAR8;
typedef wchar_t CHAR16;
typedef int BOOLEAN,EFI_STATUS;
#define STATIC static
#define CONST const
#define VOID void
#define TRUE 1
#define FALSE 0
#define EFI_SUCCESS 0
#define EFI_OUT_OF_RESOURCES 9
#define EFI_ERROR(x) ((x)!=0)
#define MAX_UINTN SIZE_MAX
#define MAX_UINT64 UINT64_MAX
#define EFI_PAGE_SIZE 4096ULL
#define BLOCK_SIZE 0x200000ULL
#define EFI_SIZE_TO_PAGES(x) (((x)+4095)/4096)
#define EFI_PAGES_TO_SIZE(x) ((x)*4096ULL)
#define EfiConventionalMemory 7
#define EfiLoaderCode 1
#define AllocateAddress 2
#define ALIGN_VALUE(x,a) (((x)+(a)-1)&~((a)-1))
#define MIN(x,y) ((x)<(y)?(x):(y))
#define AsciiStrCmp strcmp
#define CompareMem memcmp
#define ScanMem8(p,n,c) memchr((p),(c),(n))
#define FreePool free
#define UnicodeSPrint(...) ((void)0)
#define DiagDraw(...) ((void)0)
static UINT32 U32(const void*p){UINT32 v;memcpy(&v,p,4);return v;}
static UINT64 U64(const void*p){UINT64 v;memcpy(&v,p,8);return v;}
typedef struct {UINT32 Type,Pad;UINT64 PhysicalStart,VirtualStart,NumberOfPages,Attribute;} EFI_MEMORY_DESCRIPTOR;
typedef struct {UINT64 Base;} KERNEL;
static EFI_MEMORY_DESCRIPTOR test_map[8];
static unsigned map_count,alloc_calls;
static int fail_alloc;
static UINT64 allocated_base,allocated_bytes;
static EFI_STATUS GetMap(EFI_MEMORY_DESCRIPTOR **m,UINTN*c,UINTN*s,UINTN*k,UINTN*t){
 *s=map_count*sizeof(test_map[0]);*c=*s;*t=sizeof(test_map[0]);*k=1;*m=malloc(*s);memcpy(*m,test_map,*s);return 0;}
static EFI_STATUS allocate(unsigned kind,unsigned type,UINTN pages,EFI_PHYSICAL_ADDRESS*base){
 assert(kind==AllocateAddress&&type==EfiLoaderCode);++alloc_calls;
 if(fail_alloc)return 9;allocated_base=*base;allocated_bytes=pages*4096ULL;return 0;}
static struct {EFI_STATUS(*AllocatePages)(unsigned,unsigned,UINTN,EFI_PHYSICAL_ADDRESS*);} services={allocate},*gBS=&services;
static void region(unsigned i,UINT32 type,UINT64 base,UINT64 bytes){test_map[i]=(EFI_MEMORY_DESCRIPTOR){.Type=type,.PhysicalStart=base,.NumberOfPages=bytes/4096};}
'''
    code = prelude + window + function(source, 'AdtNode') + header
    code += function(source, 'RunEnd') + function(source, 'AllocateWindow')
    code += '\nstatic unsigned char blob[]={' + ','.join(map(str, blob)) + '};\n'
    code += r'''
static int adt(unsigned char*b,size_t size,NABU_HANDOFF*out){
 UINTN pos=0,rd=MAX_UINTN,tc=MAX_UINTN,addon=MAX_UINTN;UINT64 win=0;BOOLEAN packed=0;
 if(!AdtNode(b,size,&pos,0,3,&rd,&tc,&addon,&win,&packed)||pos!=size)return 0;
 pos=0;return NabuFindChosen(b,size,&pos,0,out)&&pos==size;
}
int main(void){
 NABU_HANDOFF info={0};assert(adt(blob,sizeof(blob),&info));
 assert(info.Enabled&&info.AutoMemory&&U64(blob+info.DramBase)==0&&U64(blob+info.DramSize)==0);
 for(size_t n=0;n<sizeof(blob);n++){NABU_HANDOFF bad={0};assert(!adt(blob,n,&bad));}
 blob[info.DramBase]=1;NABU_HANDOFF bad={0};assert(!adt(blob,sizeof(blob),&bad));blob[info.DramBase]=0;
 KERNEL kernel={.Base=0xfffffff007004000ULL};UINT64 size,address;
 // Adjacent free descriptors combine; a reserved PStore splits the lower run.
 region(0,7,0xc0300000,0xbfb00000);region(1,0,0x17fe00000,0x200000);
 region(2,7,0x180000000,0x100000000);region(3,7,0x280000000,0x100000000);
 map_count=4;size=0x300000000ULL;assert(AllocateWindow(&kernel,&size,1,&address)==0);
 assert(address==0x180004000&&size==0x1ffe00000&&allocated_base==address&&allocated_bytes==size);
 // A runtime allocation cuts the run and must not be included in XNU ownership.
 region(3,6,0x280000000,0x1000000);region(4,7,0x281000000,0xff000000);map_count=5;
 size=0x300000000ULL;assert(AllocateWindow(&kernel,&size,1,&address)==0);
 assert(address==0x180004000&&size==0xffe00000);
 // Failure to reserve the whole span never becomes successful evidence.
 fail_alloc=1;size=0x300000000ULL;assert(AllocateWindow(&kernel,&size,1,&address)==9&&address==0&&size==0x300000000ULL);
 fail_alloc=0;size=0x300000000ULL;unsigned calls=alloc_calls;
 assert(AllocateWindow(&kernel,&size,0,&address)==9&&alloc_calls==calls);
 // Fixed mode still reserves exactly the requested size.
 size=0x10000000;assert(AllocateWindow(&kernel,&size,0,&address)==0&&size==0x10000000&&allocated_bytes==size);
 printf("{\"passed\":true,\"truncated_adt_cases\":%zu,\"allocation_scenarios\":5}\n",sizeof(blob));
}
'''
    c = a.output/'actual-handoff.c'
    exe = a.output/'actual-handoff'
    c.write_text(code)
    subprocess.run(host_command(['clang', '-std=c11', '-O1', '-g', '-fsanitize=address,undefined',
                                 host_path(c), '-o', host_path(exe)]), check=True)
    result = subprocess.check_output(host_command([host_path(exe)]), text=True)
    (a.output/'report.json').write_text(result)
    print(result)


if __name__ == '__main__':
    main()
