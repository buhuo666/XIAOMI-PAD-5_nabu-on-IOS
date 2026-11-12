// SPDX-License-Identifier: MIT
// Included after NativeMetalCaPresentTrace.inc. Event 127 stages 1/2 belong to
// the CA flush observer; stages 16..27 below describe this frontend's actual calls.
#include <time.h>
#include <cstdlib>

static bool nabuMetalSubmitTraceEnabled() {
 const int saved = errno;
 // backboardd does not call the App's trace setter. Its explicit launch option
 // enables these call boundaries; the kernel still stores only active windows.
 static const bool configured = [] {
  const char *value = std::getenv("NABU_METAL_SUBMIT_TRACE");
  return value && value[0] == '1' && value[1] == '\0';
 }();
 const bool enabled = configured || gCaPresentTrace.load(std::memory_order_relaxed);
 errno = saved;
 return enabled;
}

class NabuMetalSubmitSpan {
 const bool enabled;
 const uint64_t identity, pointer, endStage;
 void mark(uint64_t stage) const {
  const int saved = errno;
  struct timespec cpu = {};
  const bool sampled = clock_gettime(CLOCK_THREAD_CPUTIME_ID, &cpu) == 0;
  const uint64_t ns = sampled ? (uint64_t)cpu.tv_sec * 1000000000ull + cpu.tv_nsec : 0;
  nabu_ca_trace_marker(127, identity, stage, pointer, ns);
  errno = saved;
 }
public:
 NabuMetalSubmitSpan(uint64_t begin, uint64_t end, uint64_t commit, uint64_t object)
 : enabled(nabuMetalSubmitTraceEnabled()), identity(commit), pointer(object), endStage(end) {
  if (enabled) mark(begin);
 }
 ~NabuMetalSubmitSpan() { if (enabled) mark(endStage); }
 NabuMetalSubmitSpan(const NabuMetalSubmitSpan &) = delete;
 NabuMetalSubmitSpan &operator=(const NabuMetalSubmitSpan &) = delete;
};
