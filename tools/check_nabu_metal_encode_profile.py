#!/usr/bin/env python3
"""Exercise the production encoding counters through returns, failures and thread changes."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path
from nabu_metal_encode_profile import stage_encode_profile

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <atomic>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstdio>
#include <thread>
#include <time.h>
#include <vector>
static thread_local uint64_t wall=100,cpu=1000000,tid=101;
static std::atomic<unsigned> clocks{0};
static uint64_t nowUs(){++clocks;errno=EINVAL;return wall;}
static int sampleCpu(clockid_t,struct timespec *value){++clocks;value->tv_sec=cpu/1000000000;value->tv_nsec=cpu%1000000000;errno=EINVAL;return 0;}
static int pthread_threadid_np(void *,uint64_t *value){*value=tid;errno=EINVAL;return 0;}
struct Row{uint64_t id,stage,b,c;};
static std::vector<Row> rows;
static void nabu_ca_trace_marker(uint32_t event,uint64_t id,uint64_t stage,uint64_t b,uint64_t c){assert(event==127);rows.push_back({id,stage,b,c});errno=EINVAL;}
#define clock_gettime sampleCpu
#include "NativeMetalEncodeProfile.inc"
#undef clock_gettime
static unsigned originals;
static bool encode(NabuMetalEncodeStats &stats,bool result){
 NabuMetalEncodeScope observation(stats,NabuEncodeDraw);
 assert(errno==ENOENT);++originals;wall+=7;cpu+=3000;errno=EIO;return result;
}
int main(int argc,char **){
 if(argc>1){
  unsetenv("NABU_METAL_ENCODE_PROFILE");NabuMetalEncodeStats stats;
  errno=ENOENT;assert(encode(stats,false)==false && errno==EIO && originals==1);
  nabuMetalEncodeProfileEmit(stats,7,0x123);
  assert(clocks==0 && rows.empty() && stats.categories[NabuEncodeDraw].calls==0);
  puts("PASS: disabled observer reads no clocks, emits no markers and preserves the call result");return 0;
 }
 setenv("NABU_METAL_ENCODE_PROFILE","1",1);NabuMetalEncodeStats stats;
 for(bool result:{true,false}){errno=ENOENT;assert(encode(stats,result)==result && errno==EIO);}
 const auto &draw=stats.categories[NabuEncodeDraw];
 assert(originals==2 && draw.calls==2 && draw.wallUs==14 && draw.cpuNs==6000 && draw.maxWallUs==7);
 assert(draw.firstUs==100 && draw.lastUs==114 && draw.thread==101 && !draw.mixedThreads);
 errno=ENOENT;nabuMetalEncodeProfileEmit(stats,7,0x123);assert(errno==ENOENT && rows.size()==33);
 assert(rows[0].id==7 && rows[0].stage==64 && rows[0].b==0x123 && rows[0].c==8);
 for(const auto &r:rows)assert(r.id==7);
 assert(rows[1+4*NabuEncodeDraw].stage==67 && rows[1+4*NabuEncodeDraw].b==14 && rows[1+4*NabuEncodeDraw].c==6000);
 NabuMetalEncodeStats threaded;
 std::thread a([&]{tid=202;NabuMetalEncodeScope scope(threaded,NabuEncodeBind);wall+=4;cpu+=2000;});
 std::thread b([&]{tid=203;NabuMetalEncodeScope scope(threaded,NabuEncodeBind);wall+=9;cpu+=5000;});
 a.join();b.join();const auto &binding=threaded.categories[NabuEncodeBind];
 assert(binding.calls==2 && binding.wallUs==13 && binding.cpuNs==7000 && binding.maxWallUs==9 && binding.mixedThreads);
 rows.clear();nabuMetalEncodeProfileEmit(threaded,8,0x456);
 assert(rows.size()==33 && rows[4+4*NabuEncodeBind].stage==92 && rows[4+4*NabuEncodeBind].c==1);
 puts("PASS: exact per-command category totals, early true/false returns, errno, 33-marker bound and mixed-thread flag");
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    staged=out/'frontend';staged.mkdir(exist_ok=True)
    shutil.copyfile(a.input/'frontend-source/NativeBridgeMetalFrontend.mm',staged/'NativeBridgeMetalFrontend.mm')
    schema=stage_encode_profile(ROOT,staged)
    source=out/'encode.cpp';source.write_text(HARNESS,encoding='utf-8',newline='\n')
    binary=out/'encode'
    command=['clang++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-pthread',
             '-fsanitize=address,undefined','-I'+host_path(staged),host_path(source),'-o',host_path(binary)]
    checks=[]
    for label,args in [('compile',command),('enabled',[host_path(binary)]),('disabled',[host_path(binary),'--disabled'])]:
        r=subprocess.run(host_command(args),capture_output=True)
        (out/(label+'.log')).write_bytes(r.stdout+r.stderr)
        if r.returncode:
            raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
        if label!='compile':checks.append(r.stdout.decode().strip())
    (out/'report.json').write_text(json.dumps(dict(result='pass',schema=schema,checks=checks),indent=2)+'\n')
    print('\n'.join(checks))


if __name__=='__main__':
    main()
