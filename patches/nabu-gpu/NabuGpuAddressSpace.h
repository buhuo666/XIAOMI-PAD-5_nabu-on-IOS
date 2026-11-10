/* SPDX-License-Identifier: MIT */
#ifndef NABU_GPU_ADDRESS_SPACE_H
#define NABU_GPU_ADDRESS_SPACE_H
#include <stddef.h>
#include <stdint.h>

/* A640 already programs a 32-bit TTBR0 input region. Reserve its full VA
 * extent; physical BO storage is allocated only on demand. The GMU keeps
 * its independent 2 GiB aperture and existing leaf/table budget. */
enum : uint64_t { NabuGpuApertureBytes = UINT64_C(1) << 32 };
enum : size_t {
    NabuGpuApertureLeaves = NabuGpuApertureBytes / 4096,
    /* One L1 root, four L2 pages, 2048 L3 pages. */
    NabuGpuTablePages = 1 + NabuGpuApertureBytes / (UINT64_C(1) << 30)
                         + NabuGpuApertureBytes / (UINT64_C(1) << 21)
};
#endif
