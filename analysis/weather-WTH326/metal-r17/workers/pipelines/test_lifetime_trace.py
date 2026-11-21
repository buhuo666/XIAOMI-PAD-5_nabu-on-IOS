"""Exercise real stage emitter plus real C transport and mixed-lifetime decoder."""
from pathlib import Path
import json,subprocess,sys
H=Path(__file__).resolve().parent;R=H.parents[4]
from analyze_lifetime import analyze
O=H/'lifetime-test';O.mkdir(exist_ok=True)
text=r'''
#include "NabuCaTraceBridge.h"
#include <atomic>
#include <cassert>
#include <cstdarg>
#include <cerrno>
#include <cstdint>
#include <map>
#include <mutex>
#include <thread>
#include <vector>
#include <unistd.h>
extern "C" long marker_syscall(long,...);
#define syscall marker_syscall
#include "ca_trace_marker.h"
#undef syscall
static bool enabled=true;
static bool nabuMetalSubmitTraceEnabled(){return enabled;}
#include "NativeMetalLifetimeTrace.inc"
struct Row{uint32_t window,event;uint64_t token,a,b,c;};
static std::atomic<uint32_t> active{0};static std::atomic<unsigned> stop{0};
static std::vector<Row> rows;static std::mutex mutex;
extern "C" uint64_t thread_get_runtime_self(){return 0;}
extern "C" void absolutetime_to_nanoseconds(uint64_t,uint64_t*){}
static uint32_t window(){return active;}
static void record(uint32_t w,uint32_t e,uint64_t token,uint64_t a,uint64_t b,uint64_t c){
 std::lock_guard<std::mutex> lock(mutex);if(w==active)rows.push_back({w,e,token,a,b,c});if(stop.exchange(0))active=0;
}
extern "C" long marker_syscall(long number,...){
 assert(number==179);va_list args;va_start(args,number);auto code=va_arg(args,uint64_t);auto id=va_arg(args,uint64_t);
 auto a=va_arg(args,uint64_t);auto b=va_arg(args,uint64_t);auto c=va_arg(args,uint64_t);va_end(args);
 nabu_ca_trace_user_marker(code,id,a,b,c,209,0x123456789abcdef0);errno=EINVAL;return -1;
}
int main(){
 static NabuCaTraceCallbacks cb={window,record};nabu_ca_trace_register_callbacks(&cb);
 {NabuMetalLifetimeSpan s(640,641,0xabc,0xdef);}assert(rows.empty());
 active=1;errno=EAGAIN;{NabuMetalLifetimeSpan s(640,641,0xf123456789abcdef,0xe123456789abcdef);}assert(errno==EAGAIN&&rows.size()==4);
 assert(rows[0].event==127&&rows[0].b==640&&rows[0].c==0xf123456789abcdef);
 assert(rows[1].event==80&&rows[1].c==0xe123456789abcdef);assert(rows[2].b==641&&rows[0].a==rows[2].a);
 rows.clear();std::vector<std::thread> threads;
 for(unsigned t=0;t<4;t++)threads.emplace_back([t]{for(unsigned n=0;n<250;n++){unsigned stage=640+2*(n%4);NabuMetalLifetimeSpan s(stage,stage+1,t,n);}});
 for(auto&t:threads)t.join();assert(rows.size()==4000);
 std::map<uint64_t,unsigned> spans;for(auto&r:rows)if(r.event==127){assert(r.b>=640&&r.b<=647);spans[r.a]++;}assert(spans.size()==1000);for(auto&s:spans)assert(s.second==2);
 rows.clear();stop=1;{NabuMetalLifetimeSpan s(642,643,1,2);}assert(rows.size()==1);
 enabled=false;active=1;rows.clear();{NabuMetalLifetimeSpan s(646,647,1,2);}assert(rows.empty());
}
'''
(O/'test.cpp').write_text(text)
incs=['-I'+str(R/'patches/nabu-diagnostics'),'-I'+str(H/'source')]
cmds=[['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',*incs,'-c',R/'patches/nabu-diagnostics/NabuCaTraceBridge.c','-o',O/'bridge.o'],['clang++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-pthread',*incs,O/'test.cpp',O/'bridge.o','-o',O/'test'],[O/'test']]
for i,cmd in enumerate(cmds):
 r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True);(O/f'{i}.log').write_text(r.stdout+r.stderr)
 if r.returncode:raise RuntimeError(r.stdout+r.stderr)
def marker(t,stage,span=1,pid=209,pointer=0xabc,thread=3,detail=0xdef):return dict(time_us=t,event=127,a=stage,identity=span,pid=pid,b=pointer,c=detail,thread=thread)
calls=[dict(pid=209,id=1,category='texture_allocate',result_pointer=0xabc,end_us=5,failed=False),dict(pid=209,id=2,category='texture_allocate',result_pointer=0xabc,end_us=25,failed=False)]
ms=[marker(10,640),marker(20,641),marker(30,640,2),marker(40,641,2),marker(15,642,1,17),marker(19,643,1,17),marker(50,644,3),marker(60,645,3,thread=4),marker(70,647,4),marker(80,646,5)]
out=analyze(ms,calls);assert [x['creation_api_id'] for x in out['spans'] if x['kind']=='texture_release']==[1,2];assert out['diagnostics']==dict(mismatched_pair=1,missing_begin=1,missing_end=1)
report=dict(passed=True,emitter_transport='actual NabuCaTraceBridge.c and user marker',closed_window_inert=True,errno_preserved=True,concurrent_spans=1000,stage_range=[640,647],u64_arguments=True,window_half_record_retained=True,parser_pid_scoping=True,parser_address_reuse=True,parser_missing_and_mismatch=True,device_executed=False)
(O/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
