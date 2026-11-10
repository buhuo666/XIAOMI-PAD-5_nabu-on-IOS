/* SPDX-License-Identifier: MIT */
#ifndef NABU_GPU_CLIENT_SLOTS_H
#define NABU_GPU_CLIENT_SLOTS_H
#include <stdint.h>

enum : unsigned { NabuGpuMaxClients = 24 };
struct NabuGpuClientWindow { uint64_t start, bytes; };
/* Keep all eight established windows. Slots 8..23 each reserve 128 MiB
 * in the remaining 2..4 GiB of the GPU's 32-bit address space. Slots 4..7
 * remain above SQE/GMEM/ring and below the compositor's 512 MiB base.
 * These are address reservations, not allocations of physical RAM. */
static constexpr NabuGpuClientWindow NabuGpuClientWindows[NabuGpuMaxClients] = {
    {0x20000000ull, 0x40000000ull},
    {0x60000000ull, 0x0AAA9000ull},
    {0x6AAA9000ull, 0x0AAA9000ull},
    {0x75552000ull, 0x0AAA9000ull},
    {0x00800000ull, 0x07E00000ull},
    {0x08600000ull, 0x07E00000ull},
    {0x10400000ull, 0x07E00000ull},
    {0x18200000ull, 0x07E00000ull},
    {0x80000000ull, 0x08000000ull},
    {0x88000000ull, 0x08000000ull},
    {0x90000000ull, 0x08000000ull},
    {0x98000000ull, 0x08000000ull},
    {0xA0000000ull, 0x08000000ull},
    {0xA8000000ull, 0x08000000ull},
    {0xB0000000ull, 0x08000000ull},
    {0xB8000000ull, 0x08000000ull},
    {0xC0000000ull, 0x08000000ull},
    {0xC8000000ull, 0x08000000ull},
    {0xD0000000ull, 0x08000000ull},
    {0xD8000000ull, 0x08000000ull},
    {0xE0000000ull, 0x08000000ull},
    {0xE8000000ull, 0x08000000ull},
    {0xF0000000ull, 0x08000000ull},
    {0xF8000000ull, 0x08000000ull},
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
