/* SPDX-License-Identifier: MIT */
#pragma once

/* The source kernel defines this concrete base in MiniIOMobileFramebuffer.cpp.
 * Its metaclass and structors are imported by name; no original IOGPUFamily
 * class is loaded or replaced. */
#include <IOKit/IOService.h>

class IOAcceleratorES : public IOService {
    OSDeclareDefaultStructors(IOAcceleratorES)
};
static_assert(sizeof(IOService)==136 && sizeof(IOAcceleratorES)==136,
    "Source-kernel IOAcceleratorES extent");
