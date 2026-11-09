// SPDX-License-Identifier: MIT
// Read-only diagnostics for the isolated NC IOSurface test; not capability flags.
#pragma once
#include <stdbool.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

typedef struct NabuMetalSurfaceStats {
    // Raw runtime counters: cumulative imports/copies/image choices, unmodified.
    uint64_t host_pointer_imports_made;
    uint64_t host_pointer_import_bytes_made;
    uint64_t copied_host_buffers_made;
    uint64_t copied_host_buffers_refused;
    uint64_t copied_host_buffers_degraded;
    uint64_t copied_copy_in_bytes;
    uint64_t copied_merge_back_bytes;
    uint64_t host_textures_in_place;
    uint64_t shadowed_textures;
    uint64_t host_texture_shadows_exact;
    uint64_t host_texture_shadows_render_target;
    uint64_t host_texture_shadows_shader_write;
    uint64_t host_texture_shadows_check_pending;
    uint64_t host_texture_shadows_check_failed;
    uint64_t host_texture_shadows_unchecked;
    uint64_t host_texture_shadows_refused_rows;
    uint64_t host_texture_shadows_refused_detached;
    uint64_t host_texture_shadows_refused_image;
    uint64_t host_texture_shadows_refused_pitch;
    uint64_t host_texture_shadows_refused_placement;
    uint64_t host_texture_shadows_refused_source;
    uint64_t host_texture_shadows_refused_dma_buf;
    uint64_t in_place_checks_run;
    uint64_t in_place_checks_passed;
    uint64_t in_place_checks_failed;
    uint64_t in_place_checks_unchecked;
    uint64_t in_place_checks_recalled;
    // Frontend import wrappers; made/released are cumulative, held is the cache size.
    uint64_t surface_imports_made;
    uint64_t surface_imports_released;
    uint64_t surface_imports_held;
} NabuMetalSurfaceStats;

// The device must already be opened by the standard factory. No wait, trim,
// import or policy change is performed. Compare snapshots after GPU completion
// and after creation/release has stopped; this is not one atomic cross-layer view.
bool native_bridge_metal_surface_stats(NabuMetalSurfaceStats *out);
// Existing frontend operation: prune imports with no other local surface owner.
void native_bridge_metal_trim_surface_imports(void);

#ifdef __cplusplus
}
#endif
