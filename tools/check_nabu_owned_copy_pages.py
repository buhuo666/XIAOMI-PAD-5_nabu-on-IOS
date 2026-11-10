#!/usr/bin/env python3
"""Run real Mach mapping and production CopiedBuffers lifetime checks on macOS."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from build_nabu_gpu_metal_probe import stage_owned_copy_pages

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
use std::ptr::NonNull;
use std::sync::Arc;

mod device {
    pub(crate) fn lock<T>(value: &std::sync::Mutex<T>) -> std::sync::MutexGuard<'_, T> {
        value.lock().unwrap()
    }
}
mod work_counts {
    use std::sync::atomic::{AtomicU64, Ordering};
    #[derive(Default)]
    pub(crate) struct Counters {pub(crate) input: AtomicU64, pub(crate) output: AtomicU64}
    impl Counters {
        pub(crate) fn copied_copied_in(&self, n: u64) {self.input.fetch_add(n, Ordering::Relaxed);}
        pub(crate) fn copied_merged_back(&self, n: u64) {self.output.fetch_add(n, Ordering::Relaxed);}
    }
}
#[path = "../../runtime/crates/metal2vulkan-runtime/src/copied.rs"]
mod copied;
#[path = "../../runtime/crates/metal2vulkan-runtime/src/nabu_copied_pages.rs"]
mod owned_test;

unsafe extern "C" {
    static mach_task_self_: u32;
    fn mach_vm_allocate(task: u32, address: *mut u64, length: u64, flags: i32) -> i32;
    fn mach_vm_deallocate(task: u32, address: u64, length: u64) -> i32;
    fn mach_vm_protect(task: u32, address: u64, length: u64, maximum: i32, protection: i32) -> i32;
    fn mach_vm_read_overwrite(task: u32, address: u64, length: u64, data: u64, size: *mut u64) -> i32;
    fn getpagesize() -> i32;
}

fn allocate(length: usize) -> u64 {
    let mut at = 0;
    assert_eq!(unsafe {mach_vm_allocate(mach_task_self_, &mut at, length as u64, 1)}, 0);
    at
}
fn fixed(at: u64, length: usize) {
    let mut target = at;
    assert_eq!(unsafe {mach_vm_allocate(mach_task_self_, &mut target, length as u64, 0)}, 0);
    assert_eq!(target, at);
}
fn free(at: u64, length: usize) {
    assert_eq!(unsafe {mach_vm_deallocate(mach_task_self_, at, length as u64)}, 0);
}
fn protect(at: u64, length: usize, protection: i32) {
    assert_eq!(unsafe {mach_vm_protect(mach_task_self_, at, length as u64, 0, protection)}, 0);
}
fn readable(at: u64) -> bool {
    let mut byte = 0u8; let mut size = 0u64;
    unsafe {mach_vm_read_overwrite(mach_task_self_, at, 1, (&mut byte as *mut u8) as u64, &mut size) == 0 && size == 1}
}
fn pointer(at: u64) -> NonNull<u8> {NonNull::new(at as *mut u8).unwrap()}
fn put(at: u64, value: u8) {unsafe {(at as *mut u8).write_volatile(value)}}
fn get(at: u64) -> u8 {unsafe {(at as *const u8).read_volatile()}}
fn fill(at: u64, length: usize, value: u8) {
    unsafe {std::slice::from_raw_parts_mut(at as *mut u8, length).fill(value)};
}

fn main() {
    let page = unsafe {getpagesize()} as usize;
    let mut cases = 0;
    // Real shared data and sub-page offset; deleting the alias leaves the source.
    {
        let source = allocate(page * 2);
        fill(source, page * 2, 0x19);
        let alias = unsafe {owned_test::OwnedPages::new(pointer(source + 37), page + 11)}.unwrap();
        let view = alias.pointer().as_ptr() as u64;
        assert_eq!(view % page as u64, 37);
        put(source + 40, 0x71); assert_eq!(get(view + 3), 0x71);
        put(view + 7, 0x82); assert_eq!(get(source + 44), 0x82);
        drop(alias); assert!(!readable(view)); assert_eq!(get(source + 44), 0x82);
        free(source, page * 2); cases += 1;
    }
    // A source protection change does not revoke the independently held view.
    {
        let source = allocate(page); fill(source, page, 0x29);
        let alias = unsafe {owned_test::OwnedPages::new(pointer(source), page)}.unwrap();
        let view = alias.pointer().as_ptr() as u64;
        protect(source, page, 0); assert!(!readable(source)); assert_eq!(get(view), 0x29);
        put(view, 0x93); protect(source, page, 3); assert_eq!(get(source), 0x93);
        drop(alias); free(source, page); cases += 1;
    }
    // Unmap and reuse the caller VA: the old object remains separate from the new.
    {
        let source = allocate(page); fill(source, page, 0x39);
        let alias = unsafe {owned_test::OwnedPages::new(pointer(source), page)}.unwrap();
        let view = alias.pointer().as_ptr() as u64;
        free(source, page); assert_eq!(get(view), 0x39);
        fixed(source, page); fill(source, page, 0xee);
        put(view, 0x94); assert_eq!(get(source), 0xee);
        drop(alias); assert!(!readable(view)); assert_eq!(get(source), 0xee);
        free(source, page); cases += 1;
    }
    // Missing and initially inaccessible pages remain failed imports.
    {
        let source = allocate(page); protect(source, page, 0);
        assert!(unsafe {owned_test::OwnedPages::new(pointer(source), page)}.is_err());
        free(source, page);
        assert!(unsafe {owned_test::OwnedPages::new(pointer(source), page)}.is_err());
        cases += 1;
    }
    // Read-only input is readable without broadening either mapping's permissions.
    {
        let source = allocate(page); fill(source, page, 0x49); protect(source, page, 1);
        let alias = unsafe {owned_test::OwnedPages::new(pointer(source), page)}.unwrap();
        assert_eq!(get(alias.pointer().as_ptr() as u64), 0x49);
        drop(alias); free(source, page); cases += 1;
    }
    // Execute the unchanged production sync algorithm over the retained views.
    {
        let source = allocate(page); fill(source, page, 0x51);
        let mut gpu = vec![0u8; page];
        let registry = Arc::new(copied::CopiedBuffers::default());
        let counts = work_counts::Counters::default();
        let token = unsafe {registry.add(pointer(source), NonNull::new(gpu.as_mut_ptr()).unwrap(), page)}.unwrap();
        assert!(gpu.iter().all(|&x| x == 0x51));
        put(source, 0x61); put(source + page as u64 - 1, 0x62);
        registry.copy_in(&counts); assert_eq!(gpu[0], 0x61); assert_eq!(gpu[page-1], 0x62);
        gpu[8] = 0x71; gpu[9] = 0x72; put(source + 9, 0x81);
        registry.merge_back(&counts); assert_eq!(get(source + 8), 0x71); assert_eq!(get(source + 9), 0x81);
        registry.copy_in(&counts); assert_eq!(gpu[9], 0x81);
        assert_eq!(counts.output.load(std::sync::atomic::Ordering::Relaxed), 1);
        drop(token); free(source, page); cases += 1;
    }
    // Production copy_in/merge_back after original VA reuse reaches only old data.
    {
        let source = allocate(page); fill(source, page, 0x52);
        let observer = unsafe {owned_test::OwnedPages::new(pointer(source), page)}.unwrap();
        let view = observer.pointer().as_ptr() as u64;
        let mut gpu = vec![0u8; page];
        let registry = Arc::new(copied::CopiedBuffers::default());
        let counts = work_counts::Counters::default();
        let token = unsafe {registry.add(pointer(source), NonNull::new(gpu.as_mut_ptr()).unwrap(), page)}.unwrap();
        free(source, page); fixed(source, page); fill(source, page, 0xef);
        put(view, 0x63); registry.copy_in(&counts); assert_eq!(gpu[0], 0x63);
        gpu[1] = 0x73; registry.merge_back(&counts);
        assert_eq!(get(view + 1), 0x73); assert_eq!(get(source + 1), 0xef);
        drop(token);
        let moved = counts.input.load(std::sync::atomic::Ordering::Relaxed);
        put(view, 0x64); registry.copy_in(&counts);
        assert_eq!(counts.input.load(std::sync::atomic::Ordering::Relaxed), moved);
        assert_eq!(gpu[0], 0x63);
        drop(observer); free(source, page); cases += 1;
    }
    // Both production directions continue when only the caller VA is protected.
    {
        let source = allocate(page); fill(source, page, 0x53);
        let observer = unsafe {owned_test::OwnedPages::new(pointer(source), page)}.unwrap();
        let view = observer.pointer().as_ptr() as u64;
        let mut gpu = vec![0u8; page];
        let registry = Arc::new(copied::CopiedBuffers::default());
        let counts = work_counts::Counters::default();
        let token = unsafe {registry.add(pointer(source), NonNull::new(gpu.as_mut_ptr()).unwrap(), page)}.unwrap();
        protect(source, page, 0); put(view, 0x65);
        registry.copy_in(&counts); assert_eq!(gpu[0], 0x65);
        gpu[1] = 0x75; registry.merge_back(&counts); assert_eq!(get(view + 1), 0x75);
        protect(source, page, 3); assert_eq!(get(source + 1), 0x75);
        drop(token); drop(observer); free(source, page); cases += 1;
    }
    println!("PASS: {cases} real Mach and production copied-buffer lifetime cases");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage-only', action='store_true')
    args = parser.parse_args()
    if sys.platform != 'darwin' and not args.stage_only:
        parser.error('Real Mach tests run on macOS; use --stage-only for local source checks')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metal = output / 'metal'
    patch_dir = metal / 'bridge/patches'
    patch_dir.mkdir(parents=True)
    (patch_dir / 'series').write_text('')
    stage_owned_copy_pages(ROOT, metal)
    runtime = output / 'runtime'
    relative = Path('crates/metal2vulkan-runtime/src/copied.rs')
    (runtime / relative).parent.mkdir(parents=True)
    shutil.copyfile(ROOT / 'src/metal2vulkan' / relative, runtime / relative)
    # Isolate git apply from the enclosing checkout's ignored log/artifact paths.
    subprocess.run(['git', 'init', '--quiet'], cwd=runtime, check=True)
    for patch in (ROOT / 'patches/nabu-metal/0027-nabu-ios-copied-host-read.patch',
                  patch_dir / '0028-nabu-owned-copied-pages.patch'):
        subprocess.run(['git', 'apply', '--check', str(patch)], cwd=runtime, check=True)
        subprocess.run(['git', 'apply', str(patch)], cwd=runtime, check=True)
    source = (runtime / relative).read_text()
    assert 'let pages = owned_pages.pointer();' in source
    assert '_owned_pages: owned_pages,' in source
    assert (runtime / relative.with_name('nabu_copied_pages.rs')).is_file()
    project = output / 'project'
    (project / 'src').mkdir(parents=True)
    (project / 'Cargo.toml').write_text('[package]\nname="nabu-owned-copy-check"\nversion="0.1.0"\nedition="2024"\n[workspace]\n[dependencies]\nlibc="0.2"\n')
    (project / 'src/main.rs').write_text(HARNESS, encoding='utf-8', newline='\n')
    report = dict(result='staged_not_run', production_patch_applied=True,
                  rust_executed=False, apple_mach_executed=False, gpu_executed=False)
    if not args.stage_only:
        command = ['cargo', '+1.98.1', 'run', '--release', '--manifest-path', str(project / 'Cargo.toml')]
        result = subprocess.run(command, capture_output=True)
        (output / 'test.stdout').write_bytes(result.stdout)
        (output / 'test.stderr').write_bytes(result.stderr)
        result.check_returncode()
        assert b'PASS: 8 real Mach and production copied-buffer lifetime cases' in result.stdout
        report.update(result='pass', cases=8, rust_executed=True, apple_mach_executed=True,
                      production_copied_registry_executed=True, counters_recording_only=True,
                      source_address_reuse_isolated=True, original_protection_change_survived=True,
                      initial_unreadable_refused=True, subpage_offset_preserved=True,
                      bidirectional_shared_data=True, cpu_conflict_rule_preserved=True,
                      dropped_entry_no_longer_compared=True,
                      limitation='Real macOS Mach and production CPU sync; Vulkan/GPU/iPadOS execution not performed')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
