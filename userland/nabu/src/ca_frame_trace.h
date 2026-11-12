/* Bounded, transparent observation of the original arm64 20F66 CA display path.
 * The caller owns opt-in and the short kernel trace window. No constructor. */
#ifndef NABU_CA_FRAME_TRACE_H
#define NABU_CA_FRAME_TRACE_H
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif
typedef void (*nabu_ca_trace_sink)(uint32_t event, uint64_t identity,
                                  uint64_t a, uint64_t b, uint64_t c);
enum nabu_ca_trace_event {
    NabuCaCanEnter = 96, NabuCaCanLeave = 97,
    NabuCaBeginEnter = 98, NabuCaBeginLeave = 99,
    NabuCaFinishEnter = 100, NabuCaFinishLeave = 101,
    NabuCaPage = 102, NabuCaUpdateTimes = 103,
    NabuCaQueue = 104, NabuCaQueueWords = 105,
    NabuCaSample = 106, NabuCaSampleTimes = 107,
    NabuCaWaitEnter = 108, NabuCaWaitLeave = 109,
    NabuCaSwapEnter = 110, NabuCaSwapLeave = 111,
    NabuCaSwapLayers = 112, NabuCaFramebufferHooks = 113,
    NabuCaSnapshotLimit = 114, NabuCaSampleWords = 115,
    NabuCaRenderEnter = 116, NabuCaRenderLeave = 117,
    NabuCaServerState = 118,
    NabuCaCollectEnter = 119, NabuCaCollectLeave = 120,
    NabuCaMakeBufferEnter = 121, NabuCaMakeBufferLeave = 122
};
enum nabu_ca_trace_capability {
    NabuCaDisplayHooks = 1, NabuCaFramebufferHooksSupported = 2,
    NabuCaSelectedQueueSnapshot = 4, NabuCaRenderHooks = 8,
    NabuCaMetalContextHooks = 16
};
/* Call once from an explicitly opted-in backboardd startup path. Returns a
 * capability mask, zero for wrong process/images, or negative on installation
 * failure. It never modifies executable pages or schedules diagnostic work.
 * The callback must remain alive for the process lifetime and be non-reentrant.
 * Kernel trace gating belongs in the supplied sink. */
int nabu_ca_frame_trace_install(nabu_ca_trace_sink sink);
uint32_t nabu_ca_frame_trace_capabilities(void);
#ifdef __cplusplus
}
#endif
#endif
