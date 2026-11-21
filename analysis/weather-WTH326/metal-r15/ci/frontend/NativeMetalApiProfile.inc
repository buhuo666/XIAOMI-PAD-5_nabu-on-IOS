// SPDX-License-Identifier: MIT
// Diagnostic API boundaries; enabled once at process startup. No API result,
// allocation strategy, cache policy or synchronization is changed here.
#include <cstring>

enum NabuMetalApiCategory {
 NabuApiCommandBuffer=1, NabuApiBuffer, NabuApiBufferCopy, NabuApiBufferImport,
 NabuApiTexture, NabuApiSurfaceTexture, NabuApiHeap, NabuApiHeapBuffer,
 NabuApiHeapTexture, NabuApiRenderPipeline, NabuApiComputePipeline,
 NabuApiLibrary, NabuApiFunction, NabuApiTextureView, NabuApiBufferTexture, NabuApiRenderEncoder
};
static bool nabuMetalApiProfileEnabled() {
 const int saved=errno;
 static const bool enabled=[] {
#if NABU_METAL_GLOBAL_DIAGNOSTICS
  return true;
#else
  const char *value=std::getenv("NABU_METAL_API_PROFILE");
  return value && value[0]=='1' && value[1]=='\0';
#endif
 }();
 errno=saved;return enabled;
}
class NabuMetalApiScope;
static thread_local NabuMetalApiScope *nabuMetalActiveApi=nullptr;
static std::atomic<uint64_t> nabuMetalApiSequence{0};

class NabuMetalApiScope {
 bool enabled=false,resultKnown=false,errorCodeKnown=false,errorTruncated=false;
 uint64_t identity=0,beganUs=0,beganCpu=0,resultPointer=0;
 int64_t errorCode=0;
 NabuMetalApiScope *parent=nullptr;
 char errorText[256]={};
 static uint64_t cpuNs() {
  struct timespec value={};
  return clock_gettime(CLOCK_THREAD_CPUTIME_ID,&value)==0 ?
   (uint64_t)value.tv_sec*1000000000ull+value.tv_nsec : 0;
 }
public:
 bool active() const {return enabled;}
 uint64_t sequence() const {return identity;}
 NabuMetalApiScope(uint64_t category,uint64_t object) {
  if(!nabuMetalApiProfileEnabled())return;
  const int saved=errno;enabled=true;
  identity=nabuMetalApiSequence.fetch_add(1,std::memory_order_relaxed)+1;
  parent=nabuMetalActiveApi;nabuMetalActiveApi=this;
  beganUs=nowUs();beganCpu=cpuNs();
  mark(192,category,object);
  mark(193,parent?parent->identity:0,beganCpu);
  mark(194,beganUs,0);
  errno=saved;
 }
 void mark(uint64_t stage,uint64_t b,uint64_t c) const {
  if(!enabled)return;
  const int saved=errno;nabu_ca_trace_marker(127,identity,stage,b,c);errno=saved;
 }
 void result(uint64_t pointer) {resultPointer=pointer;resultKnown=true;}
 void problem(const char *text,int64_t code,bool codeKnown) {
  if(!enabled)return;
  const int saved=errno;
  if(text) {
   size_t i=0;
   for(;i<sizeof(errorText)-1 && text[i];++i)errorText[i]=text[i];
   errorText[i]=0;errorTruncated=text[i]!=0;
  }
  if(codeKnown){errorCode=code;errorCodeKnown=true;}
  errno=saved;
 }
 ~NabuMetalApiScope() {
  if(!enabled)return;
  const int saved=errno;
  const uint64_t endedCpu=cpuNs(),endedUs=nowUs();
  // Both clocks precede emission, so output cost is outside this API interval.
  mark(198,endedUs,endedCpu);
  mark(199,resultPointer,(resultKnown?1:0)|(errorCodeKnown?2:0)|(errorTruncated?4:0));
  mark(216,(uint32_t)saved,(uint64_t)errorCode);
  const size_t length=std::strlen(errorText);
  mark(217,length,0);
  for(size_t offset=0;offset<length;offset+=16) {
   uint64_t words[2]={};
   std::memcpy(words,errorText+offset,std::min(size_t(16),length-offset));
   mark(200+offset/16,words[0],words[1]);
  }
  nabuMetalActiveApi=parent;
  errno=saved;
 }
 NabuMetalApiScope(const NabuMetalApiScope &)=delete;
 NabuMetalApiScope &operator=(const NabuMetalApiScope &)=delete;
};
static void nabuMetalApiProfileProblem(const char *text,int64_t code=0,bool codeKnown=false) {
 if(nabuMetalActiveApi)nabuMetalActiveApi->problem(text,code,codeKnown);
}
