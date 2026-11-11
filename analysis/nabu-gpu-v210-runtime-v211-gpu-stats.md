# GPU210 timings and GPU211 GPU statistics

## GPU210 device evidence — 2026-11-11

Kernel `86a5052ddb188ca8e5d0bb6e7c965d9612c6f41d`, full CI 42983403463,
GPU207 bootstrap. Desktop direct scanout and producer registry queries passed.
The user confirmed normal desktop/touch, then persistent obvious lag during
desktop swiping and Settings scrolling, with picture and touch still correct.

The recovered stream contains complete stage records for 1680 accepted frames.
One shorter 120-submission window, ending at monotonic 226.323376 s, reports:

| Measurement | Window mean | Window maximum |
| --- | ---: | ---: |
| Serialized request interval | 43.947 ms | 704.718 ms |
| Admission | 0.015 ms | 0.047 ms |
| Surface/read-lease acquisition | 1.218 ms | 1.472 ms |
| Queue | 0.278 ms | 16.092 ms |
| GPU producer wait | 8.362 ms | 33.036 ms |
| Mapping | 0.603 ms | 0.840 ms |
| Scan submit through acceptance | 4.822 ms | 8.310 ms |
| Retirement work | 0.597 ms | 1.939 ms |
| Present entry through hardware acceptance | 15.302 ms | 42.158 ms |

The following window includes a 48.9-second gap, demonstrating why whole-window
submission rates are not application FPS. The maximum producer wait across the
captured windows was 40.204 ms. The data motivates examining upstream GPU command
production and scheduling; it does not identify hardware execution as the sole
cause. Mapping and retirement are small relative to the observed lag.

The online mode-0 retirement statistics reached 4200 calls: all nonblocking,
zero actual sleeps, zero timeouts, total 10.128 ms, maximum 0.253 ms. Mode 1 had
three sampled calls, no timeout, total 26.619 ms; mode 2 had two calls, no timeout,
total 10.636 ms. These observations do not support attributing the lag to the
driver's default 500 ms bound.

3,927,190 bytes of contiguous committed stream and the entire 67,108,864-byte
slot were saved; the stream was not sealed. Clearing/readback passed, Android
boot partitions were unchanged, and Data boot count advanced 187 → 188 with
fullfsync successful. Device remains assigned to GPU work in Android with USB.

Evidence: `log/host/gpu-v210/timing-persistent.json`, `timing-online-final.json`,
`interaction-start.json`, `continuation.json`, and
`log/device/nabu-boot-20261111-210/runtime-log/{report,collection,clearing}.json`.

## GPU211 changes and intended measurement

GPU210's 38-scalar stage log survived serial persistence but was absent from
syslog. XNU's kernel os_log argument buffer is 256 bytes
(`src/xnu-8796/libkern/os/log.h` and `log_encode.c`). GPU211 emits the same ten
stage counters in two shorter records, paired by frame and monotonic timestamp.
The first record contains gap/admission/acquire/queue; the second contains the
remaining six stages. Sampling and all rendering/lifetime rules are unchanged.

A paired `GpuPerformance` helper request reaches the existing root diagnostic
job. It sends `DumpStats=true` and a request ID to `NativeAdrenoControl`. The
existing administrator privilege check remains, and the original `Start=true`
command retains its behavior. DumpStats does not request GPU startup or change
render state. Kernel begin/end markers and LastStatsRequestID pair completion
with the host request; they do not claim all statistics were sampled.

The existing dump function copies scheduler samples under the GPU lock, prints
outside it and emits `submission_sample=lock_busy` if that copy could not be made.
Its 256-entry ring includes accepted, issued and completion-observed timestamps,
hardware fences, queues and dependency counts. Method/VM/memory counters provide
before/after deltas. Issued-to-observed-completion includes IRQ/worker scheduling
and must not be labelled pure GPU execution time. A snapshot is requested before
and after interaction, outside the measured gesture, to limit logging interference.

The new helper requires a GPU211 bootstrap. The linked kernel must replace the
old GPU187 NativeAdrenoPublish object with the freshly compiled GPU211 producer
object; compiling the core kernel alone would leave the old control implementation.
All other previously qualified driver objects and Hall/120 Hz configuration stay.

Local checks: whole ARM64 Display and producer-enabled NativeAdrenoPublish objects
compiled; 20 actual flip/mapper/scanout groups passed. Full kernel/helper CI and
GPU211 device execution are pending at this revision.
