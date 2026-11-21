// SPDX-License-Identifier: MIT
// Frontend ownership only: a C release call does not prove Vulkan memory freed.
// Event127 stages640..647. Identity is a process-local span counter, paired by
// trusted PID + span identity + stage. The kernel records only its active window.
static std::atomic<uint64_t> nabuMetalLifetimeSequence{0};
class NabuMetalLifetimeSpan {
 const bool enabled;
 const uint64_t identity, pointer, detail, endStage;
 void mark(uint64_t stage) const {
  const int saved=errno;
  nabu_ca_trace_marker(127,identity,stage,pointer,detail);
  errno=saved;
 }
public:
 NabuMetalLifetimeSpan(uint64_t begin,uint64_t end,uint64_t object,uint64_t value)
 : enabled(nabuMetalSubmitTraceEnabled()),
   identity(enabled?nabuMetalLifetimeSequence.fetch_add(1,std::memory_order_relaxed)+1:0),
   pointer(object),detail(value),endStage(end) {if(enabled)mark(begin);}
 ~NabuMetalLifetimeSpan(){if(enabled)mark(endStage);}
 NabuMetalLifetimeSpan(const NabuMetalLifetimeSpan&)=delete;
 NabuMetalLifetimeSpan&operator=(const NabuMetalLifetimeSpan&)=delete;
};
