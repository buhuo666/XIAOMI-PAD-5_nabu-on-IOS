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

The original host check used the upstream decoder, whose generation branch did
not recognize A640. It has been corrected to compile the canonical A640
adapter used by GPU185 and the current build. The corrected ASan/UBSan run
also checks the exact `0x13d0e3c2` enable mask, `0xf7` CP error mask, known
IB1/IB2 status, and CP protect reads after source acknowledgement.

The existing deferred-close concurrency regression passed. ARM64 compilation
passed for Publish, Scheduler, Service and Resources. Full CI 43011757018
passed all three jobs at source `0fd535a`. The final candidate replaces those
four objects, retains the remaining 60 including Hall, and passes actual
branch and loader-window checks. It retains the GPU212 bootstrap.
Device IRQ counts, timing and visual qualification remain pending.

The candidate was deployed with readback and temporarily booted on
2026-11-11. Native USB appeared. Initial diagnostics ran before Lockdown was
listening; later read-only queries succeeded with direct scanout enabled,
1600x2560/120Hz parameters and `DisplayProducerStatus=0`.
The two root performance requests returned status0 with matching identifiers:
`74891674fdf54be792708c9ad7d05e35` and
`64f3bf9025154b53875f1133c752e453`.
Their GPU snapshot body is absent from online syslog, so the matching
persistent begin/end records and real IRQ counters must be recovered in
Android. Slot1 remains owned by GPU214 and must not be overwritten.
Online DPU reporting covers 2160 accepted frames in mixed scenes; it is not
a controlled frame-rate result.

The user subsequently confirmed normal desktop and touch, but unchanged
stutter in desktop swipes and Settings scrolling. After return to Android,
7,473,356 bytes of continuous log prefix and the complete 64MiB slot were
saved, cleared and read back; Android boot partitions remained unchanged
and the Data boot count is 192. The capture was not sealed, so coverage of
all output immediately before reset is not claimed.

Paired counters confirm 1636 real GPU interrupt callbacks and fence
notifications for 1636 completed submissions, with no new disabled entries,
faults, timeouts or poisoned jobs. The final scheduler snapshot only retains
256 of those jobs (15.65%), from a late light paced scene. Its queue1 mean
1.958ms must not be presented as a same-scene reduction from GPU213.
The cumulative all-queue observed latency is 7.755ms across the pair, still
including scheduling and mixed scenes. Earlier DPU windows retain
11-17ms average producer waits and 17-23ms end-to-end latency. GPU215
therefore applies the highest stock675MHz OPP and matching voltage/bandwidth
as the default, following the user's request for direct performance work.

The paired snapshot parser now retains hardware IRQ counters and cumulative
submission/completion deltas. The comparison helper normalizes notifications
by cumulative completions, allowing coalesced interrupts and independent
counter reads. It does not require the cached `completed_fence` getter to
match the submitted fence: the existing `observeFence()` path does not update
that cache. Hardware CP/RB profiling is not initialized in the current A640
service, so issue-to-observed-completion remains a software-observed duration.

GPU frequency stays 257MHz. The Android OPP comparison identified a separate
fixed-frequency limitation; 499.2MHz requires raw ARC level224 and
6215000KB/s DDR on this device. That clock trial has not been implemented.
GPU214 first separates completion-notification delay from rendering time.
