// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>

extern "C" int nabu_log_checkpoint(void);

namespace NabuDpuCheckpoint {
// Diagnostic startup checkpoints only. Call from normal thread context with
// no surface, display-state or interrupt lock held. The existing authorized
// log writer commits the marker before the next display operation begins.
inline bool enabled() {
    uint32_t enabled = 0;
    return PE_parse_boot_argn("nabu-dpu-trace", &enabled, sizeof(enabled)) && enabled == 1;
}
inline bool record(const char *phase, uint32_t result = 0) {
    if (!enabled()) return true;
    IOLog("NABU DPU CHECKPOINT: %s result=%#x\n", phase, result);
    const int error = nabu_log_checkpoint();
    if (error) IOLog("NABU DPU CHECKPOINT: %s commit-error=%d\n", phase, error);
    return error == 0;
}
}
