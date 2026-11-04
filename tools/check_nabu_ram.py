#!/usr/bin/env python3
"""Exercise the actual RAM split loop and mapping initializer on an LP64 host."""
import argparse
import json
from pathlib import Path
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    source = (a.tree/'Platforms/AndromedaPkg/Driver/RamPartitionDxe/RamPartitionDxe.c').read_text()
    begin = source.index('{', source.index('SpiltAndAddRamPartitions('))
    end = source.index('\n//\n// Driver Entry Point', begin)
    body = source[begin:end]
    c = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
typedef uint64_t UINT64;
typedef int EFI_STATUS;
#define EFI_SUCCESS 0
#define EFI_INVALID_PARAMETER 2
#define MAX_UINT64 UINT64_MAX
#define SIZE_2GB 0x80000000ULL
#define EFI_PAGE_SIZE 4096
#define EFI_ERROR(s) ((s)!=0)
#define MIN(a,b) ((a)<(b)?(a):(b))
static unsigned calls, fail_at;
static uint64_t expected, total;
static EFI_STATUS AddRamPartition(UINT64 base,UINT64 length,UINT64 attributes,int type){
 assert(length&&length<=SIZE_2GB);assert(base==expected);assert(attributes==4&&type==7);
 ++calls;if(calls==fail_at)return 9;expected+=length;total+=length;return 0;}
static EFI_STATUS SpiltAndAddRamPartitions(UINT64 Base,UINT64 Length,UINT64 ArmAttributes,int EfiMemoryType)
'''+body+r'''
static void reset(void){calls=fail_at=0;expected=0x180000000ULL;total=0;}
int main(void){
 reset();assert(SpiltAndAddRamPartitions(expected,0,4,7)==2&&calls==0);
 reset();assert(SpiltAndAddRamPartitions(UINT64_MAX-4095,8192,4,7)==2&&calls==0);
 reset();assert(SpiltAndAddRamPartitions(expected+1,4096,4,7)==2&&calls==0);
 reset();assert(SpiltAndAddRamPartitions(expected,4095,4,7)==2&&calls==0);
 reset();assert(SpiltAndAddRamPartitions(expected,0x100000000ULL,4,7)==0&&calls==2&&total==0x100000000ULL);
 reset();assert(SpiltAndAddRamPartitions(expected,0x200000000ULL,4,7)==0&&calls==4&&total==0x200000000ULL);
 reset();assert(SpiltAndAddRamPartitions(expected,0x80001000ULL,4,7)==0&&calls==2&&total==0x80001000ULL);
 reset();fail_at=2;assert(SpiltAndAddRamPartitions(expected,0x200000000ULL,4,7)==9&&calls==2&&total==SIZE_2GB);
 puts("{\"passed\":true,\"cases\":8}");
}
'''
    a.output.mkdir(parents=True, exist_ok=True)
    file = a.output/'actual-ram-loop.c'
    exe = a.output/'actual-ram-loop'
    file.write_text(c)
    subprocess.run(['clang', '-std=c11', '-O1', '-fsanitize=address,undefined', str(file), '-o', str(exe)], check=True)
    result = subprocess.check_output([str(exe.resolve())], text=True)
    split_report = json.loads(result)
    start = source.index('{', source.index('RamPartitionDxeInitialize('))
    init = source[start:]
    memory_map = (a.tree/'Platforms/AndromedaPkg/Driver/RamPartitionDxe/ExtendedMemoryMap.h').read_text()
    memory_map = '\n'.join(line for line in memory_map.splitlines() if not line.startswith('#include'))
    c = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
typedef uint64_t UINT64;
typedef uint32_t UINT32;
typedef int EFI_STATUS;
typedef struct { const char *Name; UINT64 Address,Length; int Hob,Resource,Capability,MemoryType; UINT64 ArmAttributes; } ARM_MEMORY_REGION_DESCRIPTOR_EX;
typedef struct { UINT64 Base,AvailableLength; } RamPartitionEntry;
#define FixedPcdGet64(x) 0xa0000000ULL
#define GENERIC_RAM_BASE 0x80000000ULL
#define NoHob 0
#define SYS_MEM 0
#define SYS_MEM_CAP 0
#define Reserv 0
#define Conv 7
#define WRITE_BACK_XN 4
#define EFI_COMPROMISED_DATA 33
#define EFI_INVALID_PARAMETER 2
#define EFI_SUCCESS 0
#define EFI_ERROR(s) ((s)!=0)
#define MAX_UINT64 UINT64_MAX
#define SIZE_2GB 0x80000000ULL
#define EFI_PAGE_SIZE 4096
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define DEBUG(x) ((void)0)
''' + memory_map + r'''
static RamPartitionEntry entries[32], *RamPartitionEntries;
static UINT32 count, calls, fail_at, freed;
static EFI_STATUS get_status;
static UINT64 bases[64], lengths[64], attributes[64];
static int types[64];
static EFI_STATUS GetRamPartitions(RamPartitionEntry **out,UINT32 *n){
 if(get_status)return get_status; *out=entries;*n=count;return 0;}
static void FreePool(void *p){assert(p==entries);++freed;}
static EFI_STATUS AddRamPartition(UINT64 base,UINT64 length,UINT64 attr,int type){
 assert(calls<64); bases[calls]=base;lengths[calls]=length;attributes[calls]=attr;types[calls]=type;
 return ++calls==fail_at?9:0;}
static EFI_STATUS SpiltAndAddRamPartitions(UINT64 Base,UINT64 Length,UINT64 ArmAttributes,int EfiMemoryType)
''' + body + '\nstatic EFI_STATUS RamPartitionDxeInitialize(void)\n' + init + r'''
static void reset(void){count=calls=fail_at=freed=0;get_status=0;RamPartitionEntries=NULL;}
int main(void){
 // Low DDR belongs to PEI and must not be registered a second time.
 reset();count=1;entries[0]=(RamPartitionEntry){0x80000000,0x3cc00000};
 assert(RamPartitionDxeInitialize()==0&&calls==0&&freed==1&&!RamPartitionEntries);
 // A bank crossing the PEI boundary exposes only high conventional RAM.
 reset();count=1;entries[0]=(RamPartitionEntry){0x140000000ULL,0x2c0000000ULL};
 assert(RamPartitionDxeInitialize()==0&&calls==5&&freed==1);
 for(unsigned i=0;i<calls;i++)assert(bases[i]==0x180000000ULL+i*SIZE_2GB&&lengths[i]==SIZE_2GB&&types[i]==Conv&&attributes[i]==WRITE_BACK_XN);
 // More banks than the old fixed descriptor array supports, with no overflow.
 reset();count=16;for(unsigned i=0;i<count;i++)entries[i]=(RamPartitionEntry){0x180000000ULL+i*0x200000ULL,0x200000};
 assert(RamPartitionDxeInitialize()==0&&calls==16&&freed==1);
 for(unsigned i=0;i<calls;i++)assert(types[i]==Conv&&bases[i]==entries[i].Base&&lengths[i]==entries[i].AvailableLength);
 reset();count=1;entries[0]=(RamPartitionEntry){0xc0000000,0x80000000};
 assert(RamPartitionDxeInitialize()==0&&calls==0&&freed==1);
 reset();count=1;entries[0]=(RamPartitionEntry){UINT64_MAX-4095,8192};
 assert(RamPartitionDxeInitialize()==EFI_COMPROMISED_DATA&&calls==0&&freed==1);
 reset();get_status=17;assert(RamPartitionDxeInitialize()==17&&calls==0&&freed==0);
 reset();count=1;fail_at=1;entries[0]=(RamPartitionEntry){0x180000000ULL,0x100000000ULL};
 assert(RamPartitionDxeInitialize()==9&&calls==1&&freed==1);
 reset();count=1;entries[0]=(RamPartitionEntry){0x180000001ULL,4096};
 assert(RamPartitionDxeInitialize()==EFI_INVALID_PARAMETER&&calls==0&&freed==1);
 puts("{\"passed\":true,\"cases\":8}");
}
'''
    file = a.output/'actual-ram-initialize.c'
    exe = a.output/'actual-ram-initialize'
    file.write_text(c)
    subprocess.run(['clang', '-std=c11', '-O1', '-fsanitize=address,undefined', str(file), '-o', str(exe)], check=True)
    init_report = json.loads(subprocess.check_output([str(exe.resolve())], text=True))
    result = json.dumps({'passed': True, 'split': split_report, 'initialize': init_report})+'\n'
    (a.output/'report.json').write_text(result)
    print(result)


if __name__ == '__main__':
    main()
