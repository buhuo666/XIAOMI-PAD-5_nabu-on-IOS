/* SPDX-License-Identifier: MIT */
#ifndef NABU_GPU_KERNEL_COMPAT_H
#define NABU_GPU_KERNEL_COMPAT_H

/* Force-include for GPU C++ units compiled with the current exported 8796
 * kext headers. IONewData/IODeleteData are KERNEL_PRIVATE-only there; their
 * paired public allocator macros preserve the same owned-array lifetime. */
#ifdef __cplusplus
#include <IOKit/IOLib.h>
#ifndef IONewData
#define IONewData(type, count) IONew(type, count)
#endif
#ifndef IODeleteData
#define IODeleteData(ptr, type, count) do { \
    IODelete(ptr, type, count); \
    (ptr)=nullptr; \
} while (0)
#endif
#endif

#endif
