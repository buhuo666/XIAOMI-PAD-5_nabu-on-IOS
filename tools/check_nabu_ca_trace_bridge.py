#!/usr/bin/env python3
"""Exercise the real C bridge, concurrent marker pairing and raw syscall ABI."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path
from prepare_nabu_ca_trace_bridge import install

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include "NabuCaTraceBridge.h"
#include <atomic>
#include <cassert>
#include <cstdarg>
#include <cerrno>
#include <map>
#include <mutex>
#include <thread>
#include <vector>
#include <unistd.h>
extern "C" long marker_syscall(long number, ...) noexcept;
#define syscall marker_syscall
#include "ca_trace_marker.h"
#undef syscall
struct Row {uint32_t window,event;uint64_t id,a,b,c;};
static std::atomic<uint32_t> active{0};
static std::atomic<unsigned> stopAfterRecord{0};
static std::mutex guard;
static std::vector<Row> rows;
static uint64_t cpuTicks=0;
extern "C" uint64_t thread_get_runtime_self(void){return ++cpuTicks;}
extern "C" void absolutetime_to_nanoseconds(uint64_t t,uint64_t *ns){*ns=t*125/3;}
static uint32_t window(){return active.load();}
static void record(uint32_t w,uint32_t e,uint64_t id,uint64_t a,uint64_t b,uint64_t c){
 std::lock_guard<std::mutex> lock(guard);
 if(w==active.load())rows.push_back({w,e,id,a,b,c});
 if(stopAfterRecord.exchange(0))active=0;
}
extern "C" long marker_syscall(long number, ...) noexcept {
 assert(number==179);
 va_list args;va_start(args,number);
 uint64_t code=va_arg(args,uint64_t),id=va_arg(args,uint64_t);
 uint64_t a=va_arg(args,uint64_t),b=va_arg(args,uint64_t),c=va_arg(args,uint64_t);va_end(args);
 nabu_ca_trace_user_marker((uint32_t)code,id,a,b,c,123,0xfedcba9876543210ull);
 errno=EINVAL;return -1;
}
int main(){
 nabu_ca_trace_user_marker(0x31ca8144,1,2,3,4,5,6);assert(rows.empty());
 static const NabuCaTraceCallbacks callbacks={window,record};
 nabu_ca_trace_register_callbacks(&callbacks);
 nabu_ca_trace_user_marker(0x31ca8144,1,2,3,4,5,6);assert(rows.empty());
 active=7;
 for(uint32_t code:{0u,0x31ca8140u,0x31ca8145u,0x31ca8200u})
  nabu_ca_trace_user_marker(code,1,2,3,4,5,6);
 assert(rows.empty());
 errno=EAGAIN;
 nabu_ca_trace_marker(81,0xf123456789abcdefull,0x8123456789abcdefull,0x923456789abcdef0ull,0xa3456789abcdef01ull);
 assert(errno==EAGAIN&&rows.size()==2);
 assert(rows[0].event==81&&rows[0].a==0xf123456789abcdefull&&rows[0].b==0x8123456789abcdefull&&rows[0].c==0x923456789abcdef0ull);
 assert(rows[1].event==80&&rows[1].a==123&&rows[1].b==0xfedcba9876543210ull&&rows[1].c==0xa3456789abcdef01ull&&rows[0].id==rows[1].id);
 rows.clear();
 for(uint32_t event=98;event<=101;++event){
  rows.clear();const uint64_t before=cpuTicks;
  nabu_ca_trace_user_marker(0x31ca8000u|(event<<2),12,13,14,15,16,17);
  assert(rows.size()==3&&cpuTicks==before+1);
  assert(rows[2].event==76&&rows[2].id==rows[0].id&&rows[2].a==cpuTicks*125/3&&rows[2].b==event);
 }
 rows.clear();
 std::vector<std::thread> threads;
 for(unsigned t=0;t<8;t++)threads.emplace_back([t]{for(unsigned i=0;i<1000;i++)nabu_ca_trace_user_marker(0x31ca81fc,t*1000+i,i,t,44,55,66);});
 for(auto &t:threads)t.join();
 std::map<uint64_t,unsigned> joined;
 for(auto &r:rows){assert(r.event==127||r.event==80);joined[r.id]|=r.event==127?1:2;}
 assert(rows.size()==16000&&joined.size()==8000);
 for(auto &pair:joined)assert(pair.second==3);
 rows.clear();stopAfterRecord=1;
 nabu_ca_trace_user_marker(0x31ca8144,1,2,3,4,5,6);
 assert(rows.size()==1&&rows[0].event==81); // real window boundary: one half only
 active=8;nabu_ca_ipc_trace_record(7,64,1,2,3,4);assert(rows.size()==1);
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--tree',type=Path)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    source=out/'bridge.cpp';source.write_text(HARNESS)
    includes=['-I'+host_path(ROOT/'patches/nabu-diagnostics'),'-I'+host_path(ROOT/'userland/nabu/src')]
    commands=[('bridge-compile',['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',*includes,'-c',host_path(ROOT/'patches/nabu-diagnostics/NabuCaTraceBridge.c'),'-o',host_path(out/'bridge.o')]),
              ('test-compile',['clang++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-pthread',*includes,host_path(source),host_path(out/'bridge.o'),'-o',host_path(out/'bridge')]),
              ('test-run',[host_path(out/'bridge')])]
    for label,argv in commands:
        r=subprocess.run(host_command(argv),capture_output=True,timeout=120)
        (out/(label+'.log')).write_bytes(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace')[-5000:])
    fixture=out/'tree';(fixture/'bsd/kern').mkdir(parents=True,exist_ok=True);(fixture/'bsd/conf').mkdir(parents=True,exist_ok=True)
    original=(a.tree/'bsd/kern/kdebug.c').read_text() if a.tree else 'kdebug_trace64(__unused struct proc *p,\n{\n\tif (__probable(kdebug_enable == 0)) {\nreturn 0;\n}\n'
    (fixture/'bsd/kern/kdebug.c').write_text(original)
    (fixture/'bsd/conf/files').write_text('')
    install(fixture);first=(fixture/'bsd/kern/kdebug.c').read_text();install(fixture)
    assert first==(fixture/'bsd/kern/kdebug.c').read_text()
    assert first.count('nabu_ca_trace_user_marker(uap->code')==1
    if a.tree:
        syscall=(a.tree/'bsd/kern/syscalls.master').read_text()
        line=next(l for l in syscall.splitlines() if 'kdebug_trace64(' in l)
        assert line.split()[0]=='179'
    report=dict(passed=True,concurrent_markers=8000,full_u64_arguments=True,errno_preserved=True,
                closed_window_inert=True,window_half_pair_preserved=True,installer_idempotent=True,device_executed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
