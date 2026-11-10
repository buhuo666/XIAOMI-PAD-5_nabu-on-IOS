// SPDX-License-Identifier: MIT
use std::ptr::NonNull;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;
use std::time::Instant;

/// Preserve the copied-buffer byte merge contract, with fixed-width loads in
/// the full-word loop. Only the final 0..7 bytes use the scalar tail.
///
/// # Safety
/// Both pointers name at least snapshot.len() live readable/writable bytes as
/// required by the caller's copied registry. They need not be word aligned.
pub(crate) unsafe fn sync(
    from: NonNull<u8>,
    to: NonNull<u8>,
    snapshot: &mut [u8],
    keep_to: bool,
) -> u64 {
    let (from, to) = (from.as_ptr(), to.as_ptr());
    let words_end = snapshot.len() & !7;
    let mut written = 0u64;
    let mut at = 0;
    while at < words_end {
        // SAFETY: a complete word remains; read_unaligned also handles subpage
        // and buffer-view offsets. No load reaches past the registered range.
        let was = unsafe { snapshot.as_ptr().add(at).cast::<u64>().read_unaligned() };
        let now = unsafe { from.add(at).cast::<u64>().read_unaligned() };
        if now != was {
            let was = was.to_ne_bytes();
            let now = now.to_ne_bytes();
            let there = if keep_to {
                unsafe { to.add(at).cast::<u64>().read_unaligned().to_ne_bytes() }
            } else {
                [0u8; 8]
            };
            for byte in 0..8 {
                if now[byte] != was[byte] {
                    if !keep_to || there[byte] == was[byte] {
                        // Preserve the old volatile byte stores: never write
                        // an unchanged byte or overwrite a CPU conflict.
                        unsafe { to.add(at + byte).write_volatile(now[byte]) };
                        written += 1;
                    }
                    snapshot[at + byte] = now[byte];
                }
            }
        }
        at += 8;
    }
    let tail = snapshot.len() - at;
    if tail != 0 {
        let (mut was, mut now, mut there) = ([0u8; 8], [0u8; 8], [0u8; 8]);
        was[..tail].copy_from_slice(&snapshot[at..]);
        unsafe { std::ptr::copy_nonoverlapping(from.add(at), now.as_mut_ptr(), tail) };
        if keep_to && now != was {
            unsafe { std::ptr::copy_nonoverlapping(to.add(at), there.as_mut_ptr(), tail) };
        }
        for byte in 0..tail {
            if now[byte] != was[byte] {
                if !keep_to || there[byte] == was[byte] {
                    unsafe { to.add(at + byte).write_volatile(now[byte]) };
                    written += 1;
                }
                snapshot[at + byte] = now[byte];
            }
        }
    }
    written
}

// Default-off, bounded trial diagnostics. Time includes waiting for the copied
// registry lock and scanning its entries; it is not GPU execution time.
pub(crate) fn profile_start() -> Option<Instant> {
    static ENABLED: OnceLock<bool> = OnceLock::new();
    if *ENABLED.get_or_init(|| std::env::var_os("NABU_COPIED_SYNC_PROFILE").is_some_and(|v| v == "1")) {
        Some(Instant::now())
    } else {
        None
    }
}

struct Profile {
    calls: AtomicU64,
    scanned: AtomicU64,
    moved: AtomicU64,
    micros: AtomicU64,
    max_micros: AtomicU64,
}
impl Profile {
    const fn new() -> Self {
        Self {
            calls: AtomicU64::new(0), scanned: AtomicU64::new(0),
            moved: AtomicU64::new(0), micros: AtomicU64::new(0),
            max_micros: AtomicU64::new(0),
        }
    }
}

pub(crate) fn profile_finish(merge: bool, began: Option<Instant>, scanned: u64, moved: u64) {
    let Some(began) = began else { return };
    static COUNTS: [Profile; 2] = [Profile::new(), Profile::new()];
    let p = &COUNTS[usize::from(merge)];
    let us = began.elapsed().as_micros() as u64;
    p.scanned.fetch_add(scanned, Ordering::Relaxed);
    p.moved.fetch_add(moved, Ordering::Relaxed);
    p.micros.fetch_add(us, Ordering::Relaxed);
    p.max_micros.fetch_max(us, Ordering::Relaxed);
    let calls = p.calls.fetch_add(1, Ordering::Relaxed) + 1;
    if calls <= 4 || (calls <= 2048 && calls.is_multiple_of(64)) {
        eprintln!("NABU_COPIED_SYNC pid={} phase={} calls={} scanned={} moved={} total_us={} max_us={}",
            std::process::id(), if merge { "merge_back" } else { "copy_in" }, calls,
            p.scanned.load(Ordering::Relaxed), p.moved.load(Ordering::Relaxed),
            p.micros.load(Ordering::Relaxed), p.max_micros.load(Ordering::Relaxed));
    }
}
