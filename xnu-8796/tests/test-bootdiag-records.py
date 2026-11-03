#!/usr/bin/env python3
"""Exercise actual diagnostic publication and live wait capture helpers on CI."""
import argparse
from pathlib import Path
import re
import subprocess
import tempfile


def extract(source, name):
    at = source.index('\n' + name + '(') + 1
    start = source.rfind('\n', 0, at - 1) + 1
    brace = source.index('{', at)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


PUB = r'''
#include <assert.h>
#include <stdint.h>
#include <stdatomic.h>
#include <pthread.h>
#include <sched.h>
#include <stdio.h>
#include <string.h>
#define NABU_LOG_SIZE (4u << 20)
#define MIN(a,b) ((a)<(b)?(a):(b))
#define os_atomic_load(p,o) atomic_load_explicit((p),memory_order_##o)
#define os_atomic_store(p,v,o) atomic_store_explicit((p),(v),memory_order_##o)
static char nabu_log_ring[NABU_LOG_SIZE];
static uint64_t _Atomic nabu_log_total;
static unsigned int nabu_log_lock;
static uint64_t nabu_log_dropped_bytes, nabu_log_dropped_calls, nabu_log_read_retries;
'''

PUB_MAIN = r'''
struct packet { uint64_t magic, producer, ordinal, checksum; };
static atomic_uint finished;
static void *writer(void *arg) {
    uint64_t producer=(uintptr_t)arg;
    for(unsigned i=0;i<2000;i++) {
        struct packet p={UINT64_C(0xface12345678),producer,i,producer^i^0xabcdu};
        (void)nabu_log_publish((const char *)&p,sizeof(p));
    }
    atomic_fetch_add(&finished,1u);
    return NULL;
}
int main(void) {
    char out[4096]; uint64_t position=0;
    nabu_log_lock=1;
    assert(!nabu_log_publish("bad",3));
    assert(nabu_log_total==0 && nabu_log_dropped_bytes==3 && nabu_log_dropped_calls==1);
    assert(!nabu_log_copy_block(0,out,4096));
    nabu_log_lock=0;
    assert(nabu_log_record("complete\n",9));
    assert(nabu_log_copy(&position,out,sizeof(out))==10);
    assert(!memcmp(out,"\ncomplete\n",10));
    assert(!nabu_log_record("no-newline",10));
    nabu_log_total=0; nabu_log_dropped_bytes=nabu_log_dropped_calls=0; position=0;
    pthread_t producers[8];
    for(uintptr_t i=0;i<8;i++) assert(!pthread_create(&producers[i],NULL,writer,(void *)i));
    unsigned packets=0;
    do {
        uint32_t n=nabu_log_copy(&position,out,sizeof(out));
        assert(n%sizeof(struct packet)==0);
        for(unsigned i=0;i<n;i+=sizeof(struct packet)) {
            struct packet p; memcpy(&p,out+i,sizeof(p));
            assert(p.magic==UINT64_C(0xface12345678));
            assert(p.producer<8 && p.ordinal<2000);
            assert(p.checksum==(p.producer^p.ordinal^0xabcdu));
            packets++;
        }
        sched_yield();
    } while(atomic_load(&finished)<8 || position<atomic_load(&nabu_log_total));
    for(unsigned i=0;i<8;i++) assert(!pthread_join(producers[i],NULL));
    assert(packets>0 && nabu_log_total==(uint64_t)packets*sizeof(struct packet));
    assert(nabu_log_total+nabu_log_dropped_bytes==16000*sizeof(struct packet));
    nabu_log_total=NABU_LOG_SIZE+1ULL;
    assert(nabu_log_copy_block(0,out,4096)==-1);
    puts("actual publisher: complete records, concurrent readers/writers, explicit contention and stale RAM rejection passed");
    return 0;
}
'''

WAIT = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef int spl_t;
typedef struct thread { int sched_lock,state,block_hint,wait_result;
    uint64_t wait_event; void (*continuation)(void); } *thread_t;
static int thread_lck_grp, held, interrupts, busy;
static unsigned int nabu_sample_seq=60;
static uint64_t nabu_smp_session=UINT64_MAX;
static char result[512];
static spl_t splsched(void) { assert(!interrupts && !held); interrupts=1; return 0; }
static void splx(spl_t level) { assert(!level && interrupts && !held); interrupts=0; }
static int simple_lock_try(int *lock,int *grp) {
    assert(lock && grp==&thread_lck_grp && interrupts && !held);
    if(busy) return 0;
    held=1; return 1;
}
static void thread_unlock(thread_t t) { assert(t && held); held=0; }
static uint64_t mach_absolute_time(void) { assert(!interrupts && !held); return UINT64_MAX; }
static void absolutetime_to_nanoseconds(uint64_t value,uint64_t *out) { *out=value; }
static int nabu_smp3_emit_line(char *line,int n,int charged) {
    assert(!interrupts && !held && !charged && n>0 && n<NABU_SMP3_LINE_BYTES);
    memcpy(result,line,(size_t)n); result[n]=0; return 1;
}
'''

WAIT_MAIN = r'''
static void next_dispatch(void) { }
int main(void) {
    struct thread t={0,1,2,0,UINT64_MAX,next_dispatch};
    nabu_smp3_wait(&t,UINT64_MAX,UINT64_MAX);
    assert(strstr(result,"ok=1 st=0x1 hint=2"));
    assert(strstr(result,"ev=0xffffffffffffffff"));
    busy=1;
    nabu_smp3_wait(&t,9,31);
    assert(strstr(result,"ok=0 st=0x0 hint=0 ev=0x0 ct=0x0"));
    assert(!interrupts && !held);
    puts("actual wait snapshot: one try-lock, balanced interrupt state, no formatting under lock and max-width identity passed");
    return 0;
}
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--xnu-source',type=Path,required=True)
    parser.add_argument('--cc',default='clang')
    args=parser.parse_args()
    ufs=(args.xnu_source/'bsd/dev/nabu_ufs.c').read_text()
    exception=(args.xnu_source/'osfmk/kern/exception.c').read_text()
    helpers='\n'.join(extract(ufs,name) for name in (
        'nabu_log_try_lock','nabu_log_unlock','nabu_log_publish','nabu_log_record',
        'nabu_log_copy_block','nabu_log_copy'))
    limit=re.search(r'^#define NABU_SMP3_LINE_BYTES \d+',exception,re.M)[0]
    cases={'publication':PUB+helpers+PUB_MAIN,
           'wait':limit+'\n'+WAIT+extract(exception,'nabu_smp3_wait')+WAIT_MAIN}
    with tempfile.TemporaryDirectory(prefix='nabu-bootdiag-') as directory:
        for name,source in cases.items():
            path=Path(directory)/(name+'.c')
            path.write_text(source,newline='\n')
            binary=path.with_suffix('.exe')
            subprocess.run([args.cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',
                            '-pthread',str(path),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True,timeout=30)


if __name__=='__main__':
    main()
