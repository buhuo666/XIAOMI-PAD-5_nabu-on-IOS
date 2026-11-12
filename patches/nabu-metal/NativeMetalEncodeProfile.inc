// SPDX-License-Identifier: MIT
// Per-command CPU totals. Emit a bounded summary at commit instead of recording
// two kernel markers for every resource binding or draw call.
enum NabuMetalEncodeCategory {
 NabuEncodePass, NabuEncodeEnd, NabuEncodeDraw, NabuEncodeBind,
 NabuEncodePipeline, NabuEncodeUsage, NabuEncodeDispatch, NabuEncodeState,
 NabuEncodeCategoryCount
};

static bool nabuMetalEncodeProfileEnabled() {
 const int saved=errno;
 static const bool enabled=[] {
  const char *value=std::getenv("NABU_METAL_ENCODE_PROFILE");
  return value && value[0]=='1' && value[1]=='\0';
 }();
 errno=saved;
 return enabled;
}

struct NabuMetalEncodeCounter {
 std::atomic<uint64_t> calls{0},wallUs{0},cpuNs{0},maxWallUs{0};
 std::atomic<uint64_t> firstUs{0},lastUs{0},thread{0};
 std::atomic<bool> mixedThreads{false},cpuUnavailable{false};
};
struct NabuMetalEncodeStats {
 NabuMetalEncodeCounter categories[NabuEncodeCategoryCount];
};

static void nabuEncodeMaximum(std::atomic<uint64_t> &target,uint64_t value) {
 uint64_t seen=target.load(std::memory_order_relaxed);
 while(value>seen && !target.compare_exchange_weak(seen,value,std::memory_order_relaxed)){}
}

class NabuMetalEncodeScope {
 NabuMetalEncodeCounter *counter=nullptr;
 uint64_t beganUs=0,beganCpu=0,thread=0;
 static uint64_t cpuNs() {
  struct timespec value={};
  return clock_gettime(CLOCK_THREAD_CPUTIME_ID,&value)==0 ?
   (uint64_t)value.tv_sec*1000000000ull+value.tv_nsec : 0;
 }
public:
 NabuMetalEncodeScope(NabuMetalEncodeStats &stats,NabuMetalEncodeCategory category) {
  if(!nabuMetalEncodeProfileEnabled())return;
  const int saved=errno;
  counter=&stats.categories[category];
  pthread_threadid_np(nullptr,&thread);
  beganUs=nowUs();beganCpu=cpuNs();
  errno=saved;
 }
 ~NabuMetalEncodeScope() {
  if(!counter)return;
  const int saved=errno;
  const uint64_t endedCpu=cpuNs(),endedUs=nowUs(),wall=endedUs-beganUs;
  counter->calls.fetch_add(1,std::memory_order_relaxed);
  counter->wallUs.fetch_add(wall,std::memory_order_relaxed);
  if(beganCpu && endedCpu>=beganCpu)counter->cpuNs.fetch_add(endedCpu-beganCpu,std::memory_order_relaxed);
  else counter->cpuUnavailable.store(true,std::memory_order_relaxed);
  nabuEncodeMaximum(counter->maxWallUs,wall);
  uint64_t first=counter->firstUs.load(std::memory_order_relaxed);
  while((!first || beganUs<first) && !counter->firstUs.compare_exchange_weak(first,beganUs,std::memory_order_relaxed)){}
  nabuEncodeMaximum(counter->lastUs,endedUs);
  uint64_t firstThread=0;
  if(!counter->thread.compare_exchange_strong(firstThread,thread,std::memory_order_relaxed) && firstThread!=thread)
   counter->mixedThreads.store(true,std::memory_order_relaxed);
  errno=saved;
 }
 NabuMetalEncodeScope(const NabuMetalEncodeScope &)=delete;
 NabuMetalEncodeScope &operator=(const NabuMetalEncodeScope &)=delete;
};

static void nabuMetalEncodeProfileEmit(const NabuMetalEncodeStats &stats,uint64_t commit,uint64_t pointer) {
 if(!nabuMetalEncodeProfileEnabled())return;
 const int saved=errno;
 nabu_ca_trace_marker(127,commit,64,pointer,NabuEncodeCategoryCount);
 for(unsigned i=0;i<NabuEncodeCategoryCount;i++) {
  const auto &c=stats.categories[i];
  nabu_ca_trace_marker(127,commit,65+i,c.wallUs.load(),c.cpuNs.load());
  nabu_ca_trace_marker(127,commit,73+i,c.calls.load(),c.maxWallUs.load());
  nabu_ca_trace_marker(127,commit,81+i,c.firstUs.load(),c.lastUs.load());
  const uint64_t flags=(c.mixedThreads.load()?1:0)|(c.cpuUnavailable.load()?2:0);
  nabu_ca_trace_marker(127,commit,89+i,c.thread.load(),flags);
 }
 errno=saved;
}
