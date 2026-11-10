// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "../nabu-wireless/NabuWlanDma.h"

// Original nabu DT: sdsprpc-smd compute_cb13 uses SID 0x5a1, cb=SID&3=1.
// Unlike ADSP's tagged 32-bit IOVA, downstream adsprpc.c maps the complete
// SDSP 34-bit address, starting at 0x80000000 + (cb << 32).
using NabuSlpiDma=NabuSmmuDma<8u<<20,1,32768,0x180000000ULL,0x5a1,1,34>;
