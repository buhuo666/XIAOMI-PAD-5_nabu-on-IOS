//! GPU246 reads existing copy counters on the observed submission path.
//! Counts are device-wide and cumulative, not costs of the current batch.

use crate::device::DeviceShared;

fn enabled() -> bool {
    static ENABLED: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    *ENABLED.get_or_init(|| {
        std::env::var_os("NABU_METAL_COPY_PROFILE").is_some_and(|value| value == "1")
    })
}

pub(crate) fn site_key(file: &str, line: u32, command: &str) -> u64 {
    let mut hash = 2_166_136_261_u32;
    // Three trailing components identify the source independently of the CI root.
    for part in file.rsplit('/').take(3).chain(std::iter::once(command)) {
        for byte in part.bytes().chain(std::iter::once(0)) {
            hash = (hash ^ u32::from(byte)).wrapping_mul(16_777_619);
        }
    }
    (u64::from(hash) << 32) | u64::from(line)
}

#[cfg(any(target_os = "macos", target_os = "ios"))]
fn mark(stage: u64, identity: u64, b: u64, c: u64) {
    unsafe { libc::syscall(179, 0x31ca81fc_u64, identity, stage, b, c); }
}

#[cfg(not(any(target_os = "macos", target_os = "ios")))]
fn mark(_stage: u64, _identity: u64, _b: u64, _c: u64) {}

fn snapshot(device: &DeviceShared, identity: u64, mut mark: impl FnMut(u64, u64, u64, u64)) {
    if !enabled() {
        return;
    }
    let device_key = device as *const DeviceShared as usize as u64;
    let vk = device.vk();
    let dropped = vk.copy_sites_dropped();
    let sites = vk.copy_sites();
    let commands = device.commands_recorded();
    mark(100, identity, device_key, dropped);
    mark(106, identity, u64::from(device.commands_recorded_available()), 0);
    mark(101, identity, commands.cmd_copy_buffer_to_image, commands.cmd_copy_image_to_buffer);
    mark(102, identity, commands.cmd_copy_buffer, commands.cmd_copy_image);
    let mut count = 0;
    for site in sites.iter().filter(|site| site.calls != 0) {
        let key = site_key(site.file, site.line, site.command);
        mark(103, identity, key, site.calls);
        mark(104, identity, key, site.regions);
        count += 1;
    }
    mark(105, identity, count, device_key);
}

pub(crate) fn emit(device: &DeviceShared, identity: u64) {
    // Preserve errno across the first environment lookup and diagnostic syscalls.
    #[cfg(any(target_os = "macos", target_os = "ios"))]
    let saved = unsafe { *libc::__error() };
    snapshot(device, identity, mark);
    #[cfg(any(target_os = "macos", target_os = "ios"))]
    unsafe { *libc::__error() = saved; }
}
