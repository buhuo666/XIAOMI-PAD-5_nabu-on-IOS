// SPDX-License-Identifier: MIT
#ifndef NABU_ALLOCATION_PRESSURE_H
#define NABU_ALLOCATION_PRESSURE_H

// Allocation calls return with the runtime's locks released. Reclaim only the
// frontend's extra import-cache owners, then retry once after those owners have
// actually been dropped. Live texture/command owners keep their allocations.
template<class Allocate, class IsDeviceOom, class Reclaim, class Observe>
auto nabuAllocateWithImportPressure(Allocate allocate, IsDeviceOom isDeviceOom,
                                    Reclaim reclaim, Observe observe)
    -> decltype(allocate())
{
    auto result = allocate();
    if (result || !isDeviceOom()) return result;
    const auto removed = reclaim();
    if (!removed) return result;
    result = allocate();
    observe(removed, result != nullptr);
    return result;
}

#endif
