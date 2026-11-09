/* SPDX-License-Identifier: MIT */
#ifndef NABU_GPU_MEMORY_POLICY_H
#define NABU_GPU_MEMORY_POLICY_H
#include <stddef.h>
#include "NabuGpuPort.h"

/* The IOService and Metal clients both own BOs. A640's qualified owned-memory
 * path keeps CPU and GPU aliases Normal NC and bypasses the cached pool.
 * This does not enable cached imports or change explicit bootstrap modes. */
constexpr bool NabuGpuOwnedBoWriteCombined(bool user_owned)
{
#if NABU_GPU_CLIENT
    return user_owned;
#else
    (void)user_owned;
    return false;
#endif
}

constexpr size_t NabuGpuVmObjectCapacity(size_t maximum)
{
#if NABU_GPU_CLIENT
    return maximum;
#else
    (void)maximum;
    return 16;
#endif
}
#endif
