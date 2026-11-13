mod device {
    #[derive(Clone, Copy, Default, Debug, PartialEq)]
    pub struct CopySite {
        pub file: &'static str,
        pub line: u32,
        pub command: &'static str,
        pub calls: u64,
        pub regions: u64,
    }
    #[derive(Clone, Copy, Default)]
    pub struct Commands {
        pub cmd_copy_buffer_to_image: u64,
        pub cmd_copy_image_to_buffer: u64,
        pub cmd_copy_buffer: u64,
        pub cmd_copy_image: u64,
    }
    pub struct Vk {
        pub sites: [CopySite; 32],
        pub dropped: u64,
    }
    impl Vk {
        pub fn copy_sites(&self) -> [CopySite; 32] { self.sites }
        pub fn copy_sites_dropped(&self) -> u64 { self.dropped }
    }
    pub struct DeviceShared {
        pub vk: Vk,
        pub commands: Commands,
        pub available: bool,
    }
    impl DeviceShared {
        pub fn vk(&self) -> &Vk { &self.vk }
        pub fn commands_recorded(&self) -> Commands { self.commands }
        pub fn commands_recorded_available(&self) -> bool { self.available }
    }
}
mod production;
fn main() { production::verify(); }

/* SNAPSHOT_CHECKS */
pub fn verify() {
    use crate::device::{Commands, CopySite, DeviceShared, Vk};
    let mut sites = [CopySite::default(); 32];
    sites[0] = CopySite { file: "/ci/a/crates/metal2vulkan-runtime/src/shadow.rs", line: 1716,
        command: "vkCmdCopyBufferToImage", calls: 9, regions: 18 };
    sites[1] = CopySite { file: "/ci/a/crates/metal2vulkan-runtime/src/blit_texture.rs", line: 921,
        command: "vkCmdCopyBufferToImage", calls: 4, regions: 4 };
    sites[2] = CopySite { file: "/ci/a/crates/metal2vulkan-runtime/src/texture/staging_copy.rs", line: 93,
        command: "vkCmdCopyImageToBuffer", calls: 7, regions: 7 };
    let mut device = DeviceShared { vk: Vk { sites, dropped: 5 }, available: true,
        commands: Commands { cmd_copy_buffer_to_image: 13, cmd_copy_image_to_buffer: 7,
                             cmd_copy_buffer: 0, cmd_copy_image: 0 } };
    #[cfg(any(target_os = "macos", target_os = "ios"))]
    unsafe { *libc::__error() = 13; }
    emit(&device, 42);
    #[cfg(any(target_os = "macos", target_os = "ios"))]
    assert_eq!(unsafe { *libc::__error() }, 13);
    let mut records = Vec::new();
    snapshot(&device, 42, |stage, identity, b, c| records.push((stage, identity, b, c)));
    if !enabled() {
        assert!(records.is_empty());
        println!("{{\"enabled\":false,\"records\":0}}");
        return;
    }
    assert_eq!(records.len(), 11);
    assert!(records.iter().all(|r| r.1 == 42));
    assert_eq!(records[0].0, 100);
    assert_eq!(records[0].3, 5);
    assert_eq!(records[1], (106, 42, 1, 0));
    assert_eq!(records[2], (101, 42, 13, 7));
    assert_eq!(records[3], (102, 42, 0, 0));
    for (index, site) in sites[..3].iter().enumerate() {
        let key = site_key(site.file, site.line, site.command);
        assert_eq!(records[4 + index * 2], (103, 42, key, site.calls));
        assert_eq!(records[5 + index * 2], (104, 42, key, site.regions));
    }
    assert_eq!(records[10], (105, 42, 3, records[0].2));
    assert_eq!(device.vk.sites, sites);
    let saved = records.clone(); records.clear();
    snapshot(&device, 42, |s, i, b, c| records.push((s, i, b, c)));
    assert_eq!(records, saved); // A read must not reset cumulative counters.
    device.available = false;
    device.commands = Commands::default();
    records.clear();
    snapshot(&device, 42, |s, i, b, c| records.push((s, i, b, c)));
    assert_eq!(records[1], (106, 42, 0, 0));
    assert_eq!(records[2], (101, 42, 0, 0));
    assert_eq!(records[4].3, 9); // Unavailable totals do not erase source counts.
    let key = site_key(sites[0].file, sites[0].line, sites[0].command);
    assert_eq!(key, site_key("/different/root/metal2vulkan-runtime/src/shadow.rs", 1716, sites[0].command));
    assert_ne!(key, site_key(sites[0].file, 1717, sites[0].command));
    assert_ne!(key, site_key(sites[0].file, 1716, "vkCmdCopyImage"));
    println!("{{\"enabled\":true,\"records\":11,\"source_key\":{key},\"cumulative_unchanged\":true,\"availability_distinct\":true}}");
}
