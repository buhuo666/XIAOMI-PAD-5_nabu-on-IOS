// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <IOKit/IOLib.h>
#include <kern/clock.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>

// 20F66 sends signed Q16.16 nits here, not a KTZ8866 register level.
// Observe the native request and its existing result until panel calibration
// is known. This does not change the registry or claim a hardware write.
static inline void nabu_backlight_observe_property(OSObject *properties, IOReturn result)
{
    auto dict = OSDynamicCast(OSDictionary, properties);
    if (!dict) return;
    auto value = dict->getObject("IOMFBBrightnessLevel");
    if (!value) return;
    uint64_t now;
    absolutetime_to_nanoseconds(mach_absolute_time(), &now);
    static uint64_t nextLog;
    uint64_t previous = __atomic_load_n(&nextLog, __ATOMIC_RELAXED);
    if (now < previous || !__sync_bool_compare_and_swap(&nextLog, previous, now + 250000000ULL)) return;
    auto number = OSDynamicCast(OSNumber, value);
    if (number) {
        IOLog("NABU BACKLIGHT PROPERTY: IOMFBBrightnessLevel raw=%llu bits=%u original=%#x\n",
            number->unsigned64BitValue(), number->numberOfBits(), result);
    } else {
        IOLog("NABU BACKLIGHT PROPERTY: IOMFBBrightnessLevel non-number original=%#x\n", result);
    }
}
