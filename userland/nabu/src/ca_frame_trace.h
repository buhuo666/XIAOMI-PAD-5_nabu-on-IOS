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
    NabuCaMakeBufferEnter = 121, NabuCaMakeBufferLeave = 122,
    /* All immediate state is captured before the original call. Leave repeats
     * the entry targets and carries raw x0; it does not report block execution. */
    NabuCaImmediateEnter = 123, NabuCaImmediateState = 124,
    NabuCaImmediateConfig = 125, NabuCaImmediateLeave = 126,
    /* Shared event127: a=1/2 identifies flush enter/leave; b=bool argument,
     * c=current thread CPU ns. Frontend subevents start at16. */
    NabuCaExtendedPhase = 127
};
enum nabu_ca_extended_phase {
    NabuCaFlushEnter = 1, NabuCaFlushLeave = 2
};
enum nabu_ca_trace_capability {
    NabuCaDisplayHooks = 1, NabuCaFramebufferHooksSupported = 2,
    NabuCaSelectedQueueSnapshot = 4, NabuCaRenderHooks = 8,
    NabuCaMetalContextHooks = 16, NabuCaImmediateHooks = 32,
    NabuCaMetalFlushHook = 64
};
/* Call once from an explicitly opted-in backboardd startup path. Returns a
 * capability mask, zero for wrong process/images, or negative on installation
 * failure. It never modifies executable pages or schedules diagnostic work.
 * The callback must remain alive for the process lifetime and be non-reentrant.
 * Kernel trace gating belongs in the supplied sink. */
int nabu_ca_frame_trace_install(nabu_ca_trace_sink sink);
uint32_t nabu_ca_frame_trace_capabilities(void);
/* Installed can observer for explicit chaining inside the same lifetime dylib.
 * Zero unless this observer installed successfully. No installation or writes. */
uintptr_t nabu_ca_frame_trace_can_predecessor(void);
#ifdef __cplusplus
}
#endif
#endif
