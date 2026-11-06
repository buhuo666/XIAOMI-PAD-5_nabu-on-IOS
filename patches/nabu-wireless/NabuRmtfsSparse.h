// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuRmtfs.h"

static bool nabu_rmtfs_unpack(const uint8_t *packed, unsigned bytes, uint8_t *output, unsigned size) {
    if (bytes < 16 || memcmp(packed, "NRF1", 4) || NabuRmtfs::u32(packed+4) != size ||
        NabuRmtfs::u32(packed+8) != 4096 || !size || size%4096) return false;
    unsigned count = NabuRmtfs::u32(packed+12);
    if (count > (bytes-16)/4100 || bytes != 16+count*4100) return false;
    memset(output, 0, size);
    for (unsigned i = 0; i < count; ++i) {
        unsigned at = 16+i*4100, offset = NabuRmtfs::u32(packed+at);
        if (offset%4096 || offset > size-4096) return false;
        memcpy(output+offset, packed+at+4, 4096);
    }
    return true;
}
