#!/usr/bin/env python3
"""CI-only contract checks for bounded Metal saved-operand observation."""
import argparse
from pathlib import Path
import subprocess
import tempfile

PRELUDE = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t user_addr_t;
static int copyin(user_addr_t, void *, size_t);
static int PE_parse_boot_argn(const char *, void *, int);
'''
MAIN = r'''
static const uint64_t base=0x100000, slide=0x9000000;
static unsigned char stack[1024];
static uint64_t deny, corrupt;
static unsigned int reads, enabled, emitted;
static char record[224];
static void put(unsigned int off, uint64_t value) {
    assert(off+8<=sizeof(stack)); memcpy(stack+off,&value,8);
}
static int copyin(user_addr_t address, void *out, size_t length) {
    reads++;
    if(deny && address<=deny && deny-address<length) return 1;
    if(address>=base && address-base<=sizeof(stack) && length<=sizeof(stack)-(address-base)) {
        memcpy(out,stack+(address-base),length); return 0;
    }
    for(unsigned i=0;i<sizeof(nabu_mtl_code)/sizeof(nabu_mtl_code[0]);i++) {
        if(address==nabu_mtl_code[i].address+slide && length==4) {
            uint32_t word=nabu_mtl_code[i].word^(address==corrupt);
            memcpy(out,&word,4); return 0;
        }
    }
    return 1;
}
static int PE_parse_boot_argn(const char *name, void *out, int length) {
    assert(!strcmp(name,"nabumtlprobe") && length==(int)sizeof(enabled));
    memcpy(out,&enabled,sizeof(enabled)); return 1;
}
int nabu_log_record(const char *line,int n) {
    assert(n>0 && n<(int)sizeof(record) && line[n-1]=='\n');
    memcpy(record,line,n); record[n]=0; emitted++; return 1;
}
static void fixture(unsigned line,unsigned index,uint64_t function) {
    memset(stack,0,sizeof(stack)); deny=corrupt=0; reads=0; emitted=0; enabled=1;
    /* Two preceding frames, then cold=+128, report=+336, setter=+400,
     * setup=+528. Distances are independently derived from the ARM64 code. */
    put(0,base+64); put(8,0x200004);
    put(64,base+128); put(72,0x200008);
    put(128,base+336); put(136,0x181d29fd4ULL+slide);
    put(336,base+400); put(344,0x181c1c4d4ULL+slide);
    put(400,base+528); put(408,0x1c22f1d7cULL+slide);
    put(120,line); put(328,function); put(280,index*8);
    put(432,0); put(440,0x300000); /* pipeline nil, MTLLibrary non-nil */
}
static void expect_status(unsigned value) {
    struct nabu_mtl_result result;
    nabu_mtl_observe(base,slide,&result);
    assert(result.status==value && reads<128);
    if(value) assert(!result.line && !result.function_null && !result.index);
}
int main(void) {
    struct nabu_mtl_result result;
    fixture(692,0,0); nabu_mtl_observe(base,slide,&result);
    assert(!result.status && result.line==692 && result.function_null && !result.index);
    assert(!result.library_null && result.pipeline_null);
    fixture(697,11,0x400000); nabu_mtl_observe(base,slide,&result);
    assert(!result.status && result.line==697 && !result.function_null && result.index==11);
    fixture(692,3,0); put(440,0); nabu_mtl_observe(base,slide,&result);
    assert(!result.status && result.library_null && result.index==3);
    fixture(692,0,0); put(136,0x181d29fd0ULL+slide); expect_status(1);
    fixture(692,0,0); put(344,0x181c1c4b0ULL+slide); expect_status(1);
    fixture(692,0,0); put(400,base+544); expect_status(1);
    fixture(692,0,0); put(0,base); expect_status(1);
    fixture(692,0,0); deny=base+128; expect_status(1);
    fixture(692,0,0); deny=base+120; expect_status(3);
    fixture(692,0,1); expect_status(4);
    fixture(697,0,0); expect_status(4);
    fixture(696,0,1); expect_status(4);
    fixture(692,12,0); expect_status(4);
    fixture(692,0,0); put(280,7); expect_status(4);
    for(unsigned i=0;i<sizeof(nabu_mtl_code)/sizeof(nabu_mtl_code[0]);i++) {
        fixture(692,0,0); corrupt=nabu_mtl_code[i].address+slide; expect_status(2);
    }
    fixture(692,0,0); enabled=0;
    nabu_mtl_crash("mediaserverd",12,6,base,slide); assert(!reads && !emitted);
    enabled=1; nabu_mtl_crash("assetsd",12,6,base,slide); assert(!reads && !emitted);
    nabu_mtl_crash("mediaserverd",12,11,base,slide); assert(!reads && !emitted);
    nabu_mtl_crash("mediaserverd",12,6,base,slide); assert(emitted==1);
    assert(strstr(record,"status=0 line=692 fn_null=1 index=0 lib_null=0 pipe_null=1"));
    assert(!nabu_mtl_read(UINT64_MAX,stack,8));
    assert(!nabu_mtl_read(base,stack,257));
    puts("Metal observation: nil/type branches, shader index, short reads, inconsistent frames, each code mismatch and opt-in gates passed");
    return 0;
}
'''

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--xnu-source',required=True,type=Path)
    p.add_argument('--cc',default='clang')
    args=p.parse_args()
    source=(args.xnu_source/'osfmk/kern/exception.c').read_text()
    start=source.index('/* NABU_MTL1_BEGIN')
    end=source.index('\nvoid\nnabu_crash_log(',start)
    with tempfile.TemporaryDirectory(prefix='nabu-metal-observation-') as directory:
        c=Path(directory)/'observe.c'
        c.write_text(PRELUDE+source[start:end]+MAIN,newline='\n')
        binary=c.with_suffix('.exe')
        subprocess.run([args.cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',
                        str(c),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True,timeout=30)

if __name__=='__main__':
    main()
