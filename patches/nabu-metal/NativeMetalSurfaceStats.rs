// SPDX-License-Identifier: MIT
// Included only by the project-owned IOSurface test build, within NativeMetalObjects.rs.
// Layout matches NabuMetalSurfaceStats.h. The frontend fills its last three fields.
#[repr(C)]
pub struct NabuMetalSurfaceStats {
    pub host_pointer_imports_made: u64,
    pub host_pointer_import_bytes_made: u64,
    pub copied_host_buffers_made: u64,
    pub copied_host_buffers_refused: u64,
    pub copied_host_buffers_degraded: u64,
    pub copied_copy_in_bytes: u64,
    pub copied_merge_back_bytes: u64,
    pub host_textures_in_place: u64,
    pub shadowed_textures: u64,
    pub host_texture_shadows_exact: u64,
    pub host_texture_shadows_render_target: u64,
    pub host_texture_shadows_shader_write: u64,
    pub host_texture_shadows_check_pending: u64,
    pub host_texture_shadows_check_failed: u64,
    pub host_texture_shadows_unchecked: u64,
    pub host_texture_shadows_refused_rows: u64,
    pub host_texture_shadows_refused_detached: u64,
    pub host_texture_shadows_refused_image: u64,
    pub host_texture_shadows_refused_pitch: u64,
    pub host_texture_shadows_refused_placement: u64,
    pub host_texture_shadows_refused_source: u64,
    pub host_texture_shadows_refused_dma_buf: u64,
    pub in_place_checks_run: u64,
    pub in_place_checks_passed: u64,
    pub in_place_checks_failed: u64,
    pub in_place_checks_unchecked: u64,
    pub in_place_checks_recalled: u64,
    pub surface_imports_made: u64,
    pub surface_imports_released: u64,
    pub surface_imports_held: u64,
}

#[unsafe(no_mangle)]
pub extern "C" fn nmb_device_surface_stats(device: *const NmbDevice, out: *mut NabuMetalSurfaceStats) -> bool {
    guard(false, || {
        let out = get_mut(out)?;
        let counts = get(device)?.0.nabu_surface_work_counts();
        out.host_pointer_imports_made = counts.host_pointer_imports_made;
        out.host_pointer_import_bytes_made = counts.host_pointer_import_bytes_made;
        out.copied_host_buffers_made = counts.copied_host_buffers_made;
        out.copied_host_buffers_refused = counts.copied_host_buffers_refused;
        out.copied_host_buffers_degraded = counts.copied_host_buffers_degraded;
        out.copied_copy_in_bytes = counts.copied_copy_in_bytes;
        out.copied_merge_back_bytes = counts.copied_merge_back_bytes;
        out.host_textures_in_place = counts.host_textures_in_place;
        out.shadowed_textures = counts.shadowed_textures;
        out.host_texture_shadows_exact = counts.host_texture_shadows_exact;
        out.host_texture_shadows_render_target = counts.host_texture_shadows_render_target;
        out.host_texture_shadows_shader_write = counts.host_texture_shadows_shader_write;
        out.host_texture_shadows_check_pending = counts.host_texture_shadows_check_pending;
        out.host_texture_shadows_check_failed = counts.host_texture_shadows_check_failed;
        out.host_texture_shadows_unchecked = counts.host_texture_shadows_unchecked;
        out.host_texture_shadows_refused_rows = counts.host_texture_shadows_refused_rows;
        out.host_texture_shadows_refused_detached = counts.host_texture_shadows_refused_detached;
        out.host_texture_shadows_refused_image = counts.host_texture_shadows_refused_image;
        out.host_texture_shadows_refused_pitch = counts.host_texture_shadows_refused_pitch;
        out.host_texture_shadows_refused_placement = counts.host_texture_shadows_refused_placement;
        out.host_texture_shadows_refused_source = counts.host_texture_shadows_refused_source;
        out.host_texture_shadows_refused_dma_buf = counts.host_texture_shadows_refused_dma_buf;
        out.in_place_checks_run = counts.in_place_checks_run;
        out.in_place_checks_passed = counts.in_place_checks_passed;
        out.in_place_checks_failed = counts.in_place_checks_failed;
        out.in_place_checks_unchecked = counts.in_place_checks_unchecked;
        out.in_place_checks_recalled = counts.in_place_checks_recalled;
        Ok(true)
    })
}
