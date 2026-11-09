// SPDX-License-Identifier: MIT
// Appended only to the derived IOSurface test frontend, after its existing globals.
#include "NabuMetalSurfaceStats.h"
extern "C" bool nmb_device_surface_stats(const NmbDevice *, NabuMetalSurfaceStats *);

extern "C" bool native_bridge_metal_surface_stats(NabuMetalSurfaceStats *out) {
    if (!out || !gDevice) return false;
    NabuMetalSurfaceStats stats = {};
    if (!nmb_device_surface_stats(gDevice, &stats)) return false;
    {
        std::lock_guard<std::mutex> lock(gSurfaceImportLock);
        stats.surface_imports_made = gSurfaceImportsMade.load(std::memory_order_relaxed);
        stats.surface_imports_released = gSurfaceImportsReleased.load(std::memory_order_relaxed);
        stats.surface_imports_held = gHeldImports.size();
    }
    *out = stats;
    return true;
}
