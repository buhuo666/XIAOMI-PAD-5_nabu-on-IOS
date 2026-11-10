/* SPDX-License-Identifier: MIT */
#ifndef NABU_GPU_CLIENT_SLOTS_H
#define NABU_GPU_CLIENT_SLOTS_H
#include <stdint.h>

enum : unsigned { NabuGpuMaxClients = 8 };
struct NabuGpuClientWindow { uint64_t start, bytes; };
/* Keep the four established windows. The additional clients use 8..512 MiB:
 * above A640's SQE at 4 MiB and below the original client aperture. These are
 * address reservations, not allocations of physical RAM. */
static constexpr NabuGpuClientWindow NabuGpuClientWindows[NabuGpuMaxClients] = {
    {0x20000000ull, 0x40000000ull},
    {0x60000000ull, 0x0AAA9000ull},
    {0x6AAA9000ull, 0x0AAA9000ull},
    {0x75552000ull, 0x0AAA9000ull},
    {0x00800000ull, 0x07E00000ull},
    {0x08600000ull, 0x07E00000ull},
    {0x10400000ull, 0x07E00000ull},
    {0x18200000ull, 0x07E00000ull},
};

inline unsigned NabuGpuSelectClientSlot(bool compositor,
    const bool (&occupied)[NabuGpuMaxClients])
{
    if(compositor && !occupied[0])return 0;
    for(unsigned slot=1;slot<NabuGpuMaxClients;++slot) {
        if(!occupied[slot])return slot;
    }
    return NabuGpuMaxClients;
}
#endif
