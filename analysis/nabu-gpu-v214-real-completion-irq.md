# GPU214 real completion interrupt

## Evidence and selected change

GPU213 removed most measured VM index overhead but remained visibly slow.
Following the Android KGSL comparison through the actual nabu board adapter
revealed that `native_adreno_smmu_register_irq` only stored a callback, and
`native_adreno_poll_irqs` invoked the GPU and SMMU callbacks from the hardware
worker after each `IOSleep(10)`. GPU212/213 boot logs explicitly say `irq=poll`.
Having a completion callback and a sleeping scheduler did not establish real
GPU interrupt delivery. The DPU's GIC/vblank path is separate and already live.

The running Android device tree supplies GPU SPI 300 (GIC INTID 332), and the
pinned A640 ring emits CACHE_FLUSH_TS with its interrupt bit. The existing
NativeAdrenoIrq decoder clears RBBM status and completes its barrier before
reporting fence or fatal status. GPU214 connects this decoder to the existing
kernel `gic_v3_spi_attach` API as a level-triggered source.

The callback/context are initialized before attach, which can immediately
enable delivery. Until the service explicitly enables the source, an early
handler masks it and returns. Enabled handlers clear/decode the source and
schedule the existing GPU completion worker; allocation and retirement remain
in worker context. GPU callbacks are removed from periodic polling. SMMU
sources retain their original worker serialization with ECATS.

Fatal callbacks mask the source without waiting on their own handler. The
service failure and diagnostic-stop paths detach/drain it from thread context
before stopping GPU/GMU DMA. Sources and the A640 service retain their existing
one-shot lifetime. Stats add separate hardware entries, dispatched callbacks,
disabled entries, SMMU polls, fence notifications and fault notifications.

The kernel GIC implementation in
`src/hakios-8796/xnu/files/osfmk/arm64/gic_v3_irq.c` was inspected: attach routes
to the current CPU and enables; mask does not drain; detach waits for handlers.
No completion is synthesized from an interrupt count: the existing scheduler
still observes the hardware fence before retiring jobs or waking consumers.

## Validation and pending qualification

The host regression compiles the production board IRQ functions, GPU callback,
IRQ decoder and published notification. ASan/UBSan cases cover an interrupt
during attach, delivery before any poll, RBBM clear/barrier, repeated/spurious
interrupts, SMMU-only polling, disable/re-enable, fatal/clear failure, attachment
errors, and draining an in-flight handler on another host thread. GIC, MMIO and
thread-call delivery are substitutes; this is not hardware acceptance.

The existing deferred-close concurrency regression passed. ARM64 compilation
passed for Publish, Scheduler, Service and Resources. Full CI and device IRQ
counts/timing comparison are pending. Candidate linking must replace all four
objects, retaining the remaining 60 and the GPU212 bootstrap.

GPU frequency stays 257MHz. The Android OPP comparison identified a separate
fixed-frequency limitation; 499.2MHz requires raw ARC level224 and
6215000KB/s DDR on this device. That clock trial has not been implemented.
GPU214 first separates completion-notification delay from rendering time.
