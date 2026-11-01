#!/usr/bin/env python3
"""Execute the actual v2 logger with bounded UFS and failure shims."""
import argparse
from pathlib import Path
import subprocess
import tempfile

PRELUDE = r"""
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
#include <stdatomic.h>
#include "nabu_log_storage.h"
/* The banner is diagnostic only; a shim avoids host format-checking differences. */
static void nabu_host_printf(const char *fmt, ...) { (void)fmt; }
#define printf nabu_host_printf
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define PZERO 0
#define UFS_BLOCK 4096u
#define NABU_LOG_SIZE (4u << 20)
#define NABU_LOG_BLOCKS NABU_LOG_STORAGE_BLOCKS
#define BOUNCE_SIZE (1u << 20)
#define DMA_BOUNCE 0u
#define os_atomic_load(p,order) atomic_load_explicit((p),memory_order_##order)
#define os_atomic_store(p,v,order) atomic_store_explicit((p),(v),memory_order_##order)
#ifdef bzero
#undef bzero
#endif
static void nabu_host_bzero(void *p, size_t n) { __builtin_memset(p, 0, n); }
#define bzero(p,n) nabu_host_bzero((p),(n))
#define NABU_DIAG_LOG 0
#define NABU_DIAG_LOG_SLEEP 0
#define NABU_DIAG_LOG_LOCK 0
#define NABU_DIAG_LOG_WRITE 0
#define NABU_DIAG_LOG_SYNC 0
#define NABU_DIAG_LOG_HEADER 0
#define NABU_DIAG_LOG_COMMIT 0
#define nabu_gpu_diag_begin(...) ((void)0)
#define nabu_gpu_diag_end(...) ((void)0)
typedef int wait_result_t;
static char nabu_log_ring[NABU_LOG_SIZE];
static unsigned char bounce[BOUNCE_SIZE];
static uint64_t _Atomic nabu_log_total, nabu_log_committed;
static int nabu_log_chan, nabu_ufs_lock, hz=100;
static uint32_t nabu_log_secs=1;
static struct { uint64_t first_block,nblocks; uintptr_t dma; } su;
static bool held;
static unsigned sleeps,writes,syncs,fail_write,fail_sync;
static uint64_t base_lba, max_written, total_written;
static struct nabu_log_header saved_header;
static bool stream_case;
static unsigned char disk_capture[12u << 20];
static jmp_buf stop_loop;
static unsigned char pattern(uint64_t at) { return (unsigned char)((at*13u+at/4096u)%251u); }
static int tsleep(void *c,int priority,const char *name,int ticks) {
    assert(c==&nabu_log_chan && priority==PZERO && ticks==hz);
    assert(!strcmp(name,"nabulog") && !held);
    if(stream_case) {
        if(sleeps++==6) longjmp(stop_loop,1);
        uint64_t previous=nabu_log_total;
        uint64_t next=previous+1500001;
        for(uint64_t i=previous;i<next;++i) nabu_log_ring[i%NABU_LOG_SIZE]=(char)pattern(i);
        nabu_log_total=next;
        return 0;
    }
    if(sleeps++) longjmp(stop_loop,1);
    return 0;
}
static void lck_mtx_lock(int *p) { assert(p==&nabu_ufs_lock && !held); held=true; }
static void lck_mtx_unlock(int *p) { assert(p==&nabu_ufs_lock && held); held=false; }
static int ufs_write_blocks(uint64_t lba,uint32_t count) {
    assert(held && count && count<=BOUNCE_SIZE/UFS_BLOCK);
    assert(lba>=base_lba && lba+count<=su.first_block+su.nblocks);
    writes++;
    if(writes==fail_write) return 5;
    if(lba==base_lba) {
        assert(count==1 && syncs>0);
        memcpy(&saved_header,bounce,sizeof(saved_header));
    } else {
        uint64_t off=(lba-base_lba-1)*UFS_BLOCK;
        assert(off+(uint64_t)count*UFS_BLOCK<=NABU_LOG_STORAGE_BYTES);
        total_written+=(uint64_t)count*UFS_BLOCK;
        if(off+(uint64_t)count*UFS_BLOCK>max_written) max_written=off+(uint64_t)count*UFS_BLOCK;
        if(stream_case) {
            assert(off+(uint64_t)count*UFS_BLOCK<=sizeof(disk_capture));
            memcpy(disk_capture+off,bounce,(size_t)count*UFS_BLOCK);
        }
    }
    return 0;
}
static int ufs_sync_cache_range(uint64_t lba,uint64_t count) {
    assert(held && count && lba>=base_lba && lba+count<=su.first_block+su.nblocks);
    if(!stream_case) assert(nabu_log_committed==17);
    syncs++;
    return syncs==fail_sync ? 5 : 0;
}
static void nabu_gpu_diag_header(void *p,uint32_t n,uint64_t seq,uint64_t total) {
    struct nabu_log_header *h=p;
    assert(n==4096 && h->seq==seq && h->total==total);
    assert(h->checksum==nabu_log_header_checksum(h));
}
"""

MAIN = r"""
static void run_case(uint64_t total,unsigned fail_w,unsigned fail_s) {
    su.first_block=108652288ULL; su.nblocks=15728640ULL; su.dma=(uintptr_t)bounce;
    base_lba=su.first_block+su.nblocks-NABU_LOG_BLOCKS;
    assert((base_lba-su.first_block)*4096ULL>(20ULL<<30)+8192);
    nabu_log_total=total; nabu_log_committed=17;
    held=false; sleeps=writes=syncs=0; max_written=total_written=0;
    fail_write=fail_w; fail_sync=fail_s; memset(&saved_header,0,sizeof(saved_header));
    if(!setjmp(stop_loop)) nabu_log_thread(NULL,0);
    assert(!held && total_written<=NABU_LOG_SIZE+4096ULL);
    if(fail_w||fail_s||!total) { assert(nabu_log_committed==17); }
    else {
        assert(nabu_log_committed==total && saved_header.version==2);
        assert(saved_header.size==(1u<<30) && saved_header.ram_size==(4u<<20));
        assert(total-saved_header.valid_from<=NABU_LOG_STORAGE_BYTES);
        assert(saved_header.checksum==nabu_log_header_checksum(&saved_header));
    }
}
int main(void) {
    assert(NABU_LOG_STORAGE_BYTES==(1u<<30) && NABU_LOG_BLOCKS==262145);
    for(uint64_t pos=0;pos<(2ULL<<30);pos+=7919) {
        uint64_t total=pos+6000000;
        struct nabu_log_chunk p=nabu_log_plan(pos,total,256);
        assert(p.blocks>0 && p.blocks<=256);
        assert(p.ram_block+p.blocks<=NABU_LOG_RAM_BYTES/4096);
        assert(p.disk_block+p.blocks<=NABU_LOG_STORAGE_BYTES/4096);
        assert(p.next>pos && p.next<=total+4095);
    }
    assert(!nabu_log_plan(1,1,256).blocks && !nabu_log_plan(0,1,0).blocks);
    run_case(123,0,0);
    assert(syncs==2 && total_written==4096 && saved_header.valid_from==0);
    run_case(123,1,0); assert(!syncs);
    run_case(123,2,0); assert(syncs==1);
    run_case(123,0,1); assert(writes==1);
    run_case(123,0,2); assert(writes==2);
    run_case(0,0,0); assert(!writes && !syncs);
    run_case(9ULL*1024*1024+37,0,0);
    assert(saved_header.ram_lost>0 && saved_header.valid_from==saved_header.ram_lost);
    run_case(NABU_LOG_STORAGE_BYTES+20000ULL,0,0);
    assert(syncs==3 && max_written==NABU_LOG_STORAGE_BYTES);
    stream_case=true;
    fail_write=fail_sync=0; held=false; sleeps=writes=syncs=0;
    nabu_log_total=nabu_log_committed=0;
    if(!setjmp(stop_loop)) nabu_log_thread(NULL,0);
    assert(!held && nabu_log_committed==9000006 && saved_header.total==9000006);
    assert(saved_header.valid_from==0 && saved_header.ram_lost==0);
    for(uint64_t i=0;i<9000006;++i) assert(disk_capture[i]==pattern(i));
    puts("v2 logger: 1GiB disk/4MiB RAM, wrap mapping, bounded dirty writes, sync failures and commit gates passed");
    return 0;
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    source = (args.xnu_source / "bsd/dev/nabu_ufs.c").read_text(encoding="utf-8")
    start = source.index("static void\nnabu_log_thread(")
    end = source.index("static void\nnabu_log_start(", start)
    with tempfile.TemporaryDirectory(prefix="log-storage-v2-") as td:
        root = Path(td)
        (root / "nabu_log_storage.h").write_bytes(
            (args.xnu_source / "bsd/dev/nabu_log_storage.h").read_bytes())
        harness, binary = root / "test.c", root / "test.exe"
        harness.write_text(PRELUDE + source[start:end] + MAIN, encoding="utf-8", newline="\n")
        subprocess.run([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-I", str(root), str(harness), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30)


if __name__ == "__main__":
    main()
