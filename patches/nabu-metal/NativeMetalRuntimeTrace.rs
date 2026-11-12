//! Optional GPU230 submission spans. The kernel retains only active trace windows.

#[cfg(any(target_os = "macos", target_os = "ios"))]
fn enabled() -> bool {
    static ENABLED: std::sync::OnceLock<bool> = std::sync::OnceLock::new();
    // Preserve the caller's errno even during the first environment lookup.
    let saved = unsafe { *libc::__error() };
    let enabled = *ENABLED.get_or_init(|| {
        std::env::var_os("NABU_METAL_SUBMIT_TRACE").is_some_and(|value| value == "1")
    });
    unsafe { *libc::__error() = saved };
    enabled
}

#[cfg(not(any(target_os = "macos", target_os = "ios")))]
fn enabled() -> bool {
    false
}

#[cfg(any(target_os = "macos", target_os = "ios"))]
fn mark(stage: u64, identity: u64, argument: u64) {
    // Same BSD179 ABI as the existing nabu CA marker. This emits observations,
    // never a scheduling transition, and never retains a command buffer.
    unsafe {
        let saved = *libc::__error();
        let mut cpu = libc::timespec { tv_sec: 0, tv_nsec: 0 };
        let ns = if libc::clock_gettime(libc::CLOCK_THREAD_CPUTIME_ID, &mut cpu) == 0 {
            cpu.tv_sec as u64 * 1_000_000_000 + cpu.tv_nsec as u64
        } else {
            0
        };
        libc::syscall(179, 0x31ca81fc_u64, identity, stage, argument, ns);
        *libc::__error() = saved;
    }
}

#[cfg(not(any(target_os = "macos", target_os = "ios")))]
fn mark(_stage: u64, _identity: u64, _argument: u64) {}

pub(crate) struct Span {
    enabled: bool,
    end: u64,
    identity: u64,
    argument: u64,
}

impl Span {
    pub(crate) fn new(begin: u64, end: u64, identity: u64, argument: u64) -> Self {
        let span = Self { enabled: enabled(), end, identity, argument };
        if span.enabled {
            mark(begin, identity, argument);
        }
        span
    }
}

impl Drop for Span {
    fn drop(&mut self) {
        if self.enabled {
            mark(self.end, self.identity, self.argument);
        }
    }
}
