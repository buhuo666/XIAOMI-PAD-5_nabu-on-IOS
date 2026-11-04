// SPDX-License-Identifier: BSD-2-Clause-Patent
// The runtime is included unchanged. Only its capture, persistent writer and
// kernel scheduling interfaces below are fixture endpoints.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
#include <cerrno>
#include <array>
#include <string>
#include <vector>
#include <functional>
#include <algorithm>
#define __unused __attribute__((unused))
using thread_call_param_t=void *;
struct Call { void (*callback)(void *,void *); };
using thread_call_t=Call *;
constexpr unsigned NSEC_PER_SEC=1000000000;
enum thread_call_priority_t { THREAD_CALL_PRIORITY_HIGH=0, THREAD_CALL_PRIORITY_KERNEL=1 };
constexpr unsigned kNabuLogFull=8;
static void *gNabuReadLock=reinterpret_cast<void *>(1);
static Call call;
static bool allocateOk,startOk,endOk,writerOpen,writerEnded,captureSealed;
static unsigned lockDepth,allocations,starts,appends,ends,schedules,reportCalls,sealCalls;
static unsigned appendFailure,appendError,writerError,finalStatus;
static uint64_t captureLost,finalLost,writerRecords;
static int sealResult;
static uint32_t published;
static std::array<char,3*1024*1024> capture;
static std::vector<char> saved;
static std::vector<std::string> events;
static std::string arguments,reports;
static std::function<void()> afterUnlock,onSeal;
static bool growOnAppend;

static const char *PE_boot_args(void) { return arguments.c_str(); }
static void IOLockLock(void *p) { assert(p && !lockDepth);lockDepth=1;events.push_back("lock"); }
static void IOLockUnlock(void *p)
{
  assert(p && lockDepth==1);lockDepth=0;events.push_back("unlock");
  if(afterUnlock) {auto callback=std::move(afterUnlock);afterUnlock=nullptr;callback();}
}
static thread_call_t thread_call_allocate_with_priority(void (*callback)(void *,void *),void *,thread_call_priority_t priority)
{
  assert(priority==THREAD_CALL_PRIORITY_KERNEL);
  ++allocations;call.callback=callback;return allocateOk?&call:nullptr;
}
static void clock_interval_to_deadline(uint32_t n,unsigned scale,uint64_t *out)
{ *out=uint64_t(n)*scale; }
static void thread_call_enter_delayed(thread_call_t c,uint64_t deadline)
{ assert(c==&call && deadline==2ULL*NSEC_PER_SEC && !lockDepth);++schedules;events.push_back("schedule"); }
static void publish(const char *p,size_t n)
{
  if(captureSealed)return;
  assert(n<=capture.size()-published);memcpy(capture.data()+published,p,n);published+=uint32_t(n);
}
static void loader_log_line(const char *line)
{ reports+=line;publish(line,strlen(line));events.push_back("console"); }
static bool nabuLogStart(unsigned);
static bool nabuLogAppend(const void *,uint32_t);
static bool nabuLogEnd(uint64_t,uint32_t);
static bool nabuLogIsOpen(void) { return writerOpen; }
static bool nabuLogHasEnded(void) { return writerEnded; }
static uint32_t nabuLogLastError(void) { return writerError; }
static uint32_t nabuLogFinalStatus(void) { return finalStatus; }
static uint64_t nabuLogFinalLost(void) { return finalLost; }
static uint64_t nabuLogCommittedRecords(void) { return writerRecords; }
#include "NabuLogRuntime.inc"

static bool nabuLogStart(unsigned slot)
{
  assert(lockDepth==1 && slot<16);++starts;events.push_back("BEGIN");
  writerOpen=startOk;if(startOk)writerRecords=1;return startOk;
}
static bool nabuLogAppend(const void *p,uint32_t n)
{
  assert(lockDepth==1 && writerOpen && n && n<=65536);
  assert(static_cast<const char *>(p)==capture.data()+saved.size());
  assert(n<=published-saved.size());
  ++appends;events.push_back("DATA");
  if(appendFailure && appends==appendFailure) {
    writerError=appendError;
    if(appendError!=kNabuLogFull)writerOpen=false;
    return false;
  }
  const char *bytes=static_cast<const char *>(p);saved.insert(saved.end(),bytes,bytes+n);++writerRecords;
  if(growOnAppend) {growOnAppend=false;publish("later",5);}
  return true;
}
static bool nabuLogEnd(uint64_t lost,uint32_t status)
{
  assert(lockDepth==1 && writerOpen && captureSealed && gNabuLogFinishing);
  ++ends;events.push_back("END");
  if(!endOk) {writerOpen=false;writerError=7;return false;}
  finalLost=lost;finalStatus=status;writerEnded=true;writerOpen=false;++writerRecords;return true;
}
extern "C" const char *nabu_log_capture_data(void) { return capture.data(); }
extern "C" uint32_t nabu_log_capture_length(void) { return published; }
extern "C" uint64_t nabu_log_capture_lost(void) { return captureLost; }
extern "C" int nabu_log_capture_seal(void)
{
  assert(!lockDepth && gNabuLogFinishing);++sealCalls;events.push_back("seal");
  if(onSeal) {auto callback=std::move(onSeal);onSeal=nullptr;callback();}
  if(!sealResult)captureSealed=true;
  return sealResult;
}
extern "C" void nabu_storage_append_report(void)
{
  assert(!lockDepth);++reportCalls;events.push_back("storage-report");
  loader_log_line("storage progress before seal\n");
}
static void reset(const std::string &args="nabu-log-slot=0",unsigned initialBytes=0)
{
  gNabuLogCall=nullptr;gNabuLogSelected=gNabuLogFinishing=gNabuLogFinalized=false;
  gNabuLogSlot=gNabuLogFlushed=0;gNabuLogRuntimeError=0;
  gNabuReadLock=reinterpret_cast<void *>(1);
  allocateOk=startOk=endOk=true;writerOpen=writerEnded=captureSealed=false;
  allocations=starts=appends=ends=schedules=reportCalls=sealCalls=lockDepth=0;
  appendFailure=appendError=writerError=finalStatus=0;captureLost=finalLost=writerRecords=0;
  sealResult=0;published=initialBytes;
  for(unsigned i=0;i<initialBytes;++i)capture[i]=char(i*11);
  arguments=args;reports.clear();saved.clear();events.clear();afterUnlock=nullptr;onSeal=nullptr;growOnAppend=false;
}
static void assertSavedPrefix()
{ assert(saved.size()==gNabuLogFlushed && std::equal(saved.begin(),saved.end(),capture.begin())); }
static void testArguments()
{
  reset("");assert(nabuLogBeginConfigured()==0 && !gNabuLogSelected);
  nabu_log_finish();assert(!allocations && !starts && !appends && !ends && !sealCalls && !schedules);
  for(const char *s:{"nabu-log-slot", "nabu-log-slot=", "nabu-log-slot=-1", "nabu-log-slot=+1",
                    "nabu-log-slot=16", "nabu-log-slot=0x1", "nabu-log-slot=1x", "nabu-log-slot=4294967296",
                    "nabu-log-slot=0 nabu-log-slot=1", "nabu-log-slot=0 nabu-log-slot=0"}) {
    reset(s);assert(nabuLogBeginConfigured()==EINVAL);nabu_log_finish();
    assert(!allocations && !starts && !appends && !ends && !schedules);
  }
  reset("unrelated-nabu-log-slot=1 nabu-log-slot-other=3");
  assert(nabuLogBeginConfigured()==0 && !gNabuLogSelected && !starts);
  reset(std::string("nabu-log-slot=0 ")+std::string(608,'x'));
  assert(nabuLogBeginConfigured()==EINVAL && !starts);
  for(unsigned slot:{0U,15U}) {
    reset("-v\tnabu-log-slot="+std::to_string(slot)+" cpus=8");
    assert(nabuLogBeginConfigured()==0 && starts==1 && gNabuLogSlot==slot && schedules==1);
  }
  reset();allocateOk=false;assert(nabuLogBeginConfigured()==ENOMEM && !starts && !schedules);
  nabu_log_finish();assert(!appends && !ends);
  reset();startOk=false;assert(nabuLogBeginConfigured()==EIO && starts==1 && !schedules);
  nabuLogPump(nullptr,nullptr);nabu_log_finish();assert(!appends && !ends);
  puts("PASS strict log-slot arguments, absent/invalid/duplicate/length cases, KERNEL call priority, allocation/start failure and no unstarted writer I/O");
}
static void testPumps()
{
  reset("nabu-log-slot=0",24*65536);assert(nabuLogBeginConfigured()==0);
  nabuLogPump(nullptr,nullptr);assert(appends==16 && saved.size()==16*65536 && schedules==2);assertSavedPrefix();
  nabuLogPump(nullptr,nullptr);assert(appends<=32 && saved.size()==published && schedules==3);assertSavedPrefix();
  reset("nabu-log-slot=0",100);assert(nabuLogBeginConfigured()==0);
  auto before=published;growOnAppend=true;nabuLogPump(nullptr,nullptr);
  assert(saved.size()==before && published==before+5);assertSavedPrefix();
  nabuLogPump(nullptr,nullptr);assert(saved.size()==published);assertSavedPrefix();
  reset("nabu-log-slot=0",100);assert(nabuLogBeginConfigured()==0);
  appendFailure=1;appendError=6;nabuLogPump(nullptr,nullptr);
  assert(gNabuLogRuntimeError==EIO && !gNabuLogFlushed && schedules==1 && !writerOpen);
  nabu_log_finish();assert(!ends && !gNabuLogFinalized && reports.find("complete=1")==std::string::npos);
  puts("PASS pump at most 16 DATA records, immutable published-prefix snapshots, advance only after commit, write failure stops scheduling");
}
static void testFinish()
{
  reset("nabu-log-slot=0",20*65536);assert(nabuLogBeginConfigured()==0);nabuLogPump(nullptr,nullptr);
  events.clear();onSeal=[] {
    auto a=appends,s=schedules;nabuLogPump(nullptr,nullptr);assert(appends==a && schedules==s);
  };
  nabu_log_finish();assert(captureSealed && writerEnded && gNabuLogFinalized && !finalStatus && !finalLost);
  assertSavedPrefix();assert(saved.size()==published);
  auto sealed=std::find(events.begin(),events.end(),"seal"),ended=std::find(events.begin(),events.end(),"END");
  assert(sealed!=events.end() && ended!=events.end() && sealed<ended);
  assert(std::find(events.begin(),sealed,"storage-report")!=sealed);
  assert(std::find(sealed,ended,"DATA")!=ended);
  unsigned oldAppends=appends,oldEnds=ends,oldSchedules=schedules;
  nabuLogPump(nullptr,nullptr);nabu_log_finish();
  assert(appends==oldAppends && ends==oldEnds && schedules==oldSchedules && sealCalls==1);
  assert(reports.find("complete=1")!=std::string::npos);
  reset("nabu-log-slot=0",100);assert(nabuLogBeginConfigured()==0);sealResult=EBUSY;
  nabu_log_finish();assert(!captureSealed && !ends && !appends && !gNabuLogFinalized && gNabuLogRuntimeError==EBUSY);
  assert(reports.find("complete=1")==std::string::npos);
  reset("nabu-log-slot=0",100);assert(nabuLogBeginConfigured()==0);endOk=false;
  nabu_log_finish();assert(ends==1 && !gNabuLogFinalized && gNabuLogRuntimeError==EIO);
  assert(reports.find("complete=1")==std::string::npos);
  reset("nabu-log-slot=0",100);assert(nabuLogBeginConfigured()==0);captureLost=13;
  nabu_log_finish();assert(gNabuLogFinalized && finalStatus==ENOSPC && finalLost==13);
  assert(reports.find("complete=1")==std::string::npos);
  reset();assert(nabuLogBeginConfigured()==0);gNabuReadLock=nullptr;nabu_log_finish();assert(!sealCalls && !ends);
  puts("PASS finish marks pump stopped before seal, drains sealed prefix, END last, idempotence, EBUSY/no END, END failure/no complete, capture loss");
}
static void testCapacityAndLateQueue()
{
  for(bool duringFinish:{false,true}) {
    reset("nabu-log-slot=0",2*65536);assert(nabuLogBeginConfigured()==0);
    appendFailure=2;appendError=kNabuLogFull;
    if(!duringFinish) {nabuLogPump(nullptr,nullptr);assert(gNabuLogRuntimeError==ENOSPC && nabuLogIsOpen());}
    nabu_log_finish();assert(writerEnded && gNabuLogFinalized && finalStatus==ENOSPC && !finalLost);
    assert(gNabuLogFlushed==65536 && gNabuLogFlushed<published && appends==2 && ends==1);
    assert(reports.find("complete=1")==std::string::npos);assertSavedPrefix();
  }
  // A pump may have decided to reschedule before finish acquires the lock.
  // Even this late queued callback must perform no post-END disk writes.
  reset("nabu-log-slot=0",100);assert(nabuLogBeginConfigured()==0);
  afterUnlock=[] {nabu_log_finish();};nabuLogPump(nullptr,nullptr);
  assert(writerEnded && schedules==2);auto oldAppends=appends,oldEnds=ends;
  nabuLogPump(nullptr,nullptr);assert(appends==oldAppends && ends==oldEnds && schedules==2);
  puts("PASS capacity failure still commits incomplete END; late requeue after finalization performs no I/O");
}
int main()
{
  testArguments();testPumps();testFinish();testCapacityAndLateQueue();
  puts("PASS actual NabuLogRuntime scheduling and termination control flow");
}
