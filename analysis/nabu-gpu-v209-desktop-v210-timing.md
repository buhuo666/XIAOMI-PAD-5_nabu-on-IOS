# GPU209 desktop scanout and GPU210 timing

## GPU209 measured result — 2026-11-11

GPU209 reused the GPU208 NC-scanout kernel (`9bbad291026b987fbb933ccca2142be869a81d4f`,
CI 42976602917) and GPU207 bootstrap. Configuration enabled `nabu-dpu=1`,
disabled standalone diagnostics, and retained live identity, Hall and 120 Hz.

The user confirmed desktop and touch operation, no visible tearing during desktop
swipes and Settings scrolling, but severe lag similar to the previous CPU path.
The production driver alternated mapped IOSurfaces without pixel copies, accepted
scans and retired old slots. The persistent log's last sampled acceptance is 6960;
no DPU failure line was found. These are submissions, not distinct visual frames.
Idle time is included in the measured submission intervals, so their rates cannot
qualify application FPS or sustained high refresh.

The existing GPU-present correctness app produced a fresh run
`1794382690390726`: 64 frames, 4,194,304 GPU pixels and 4,194,304 actual IOSurface
pixels, all correct; three direct shared imports and three releases, held zero,
no copied or shadow imports. Animation, clear, return to desktop and touch were
visually correct. The app intentionally sleeps 125 ms per frame and performs CPU
pixel creation/checking/reporting. Its low visual rate is not a GPU benchmark.
Median drawable acquisition was 6.161 ms; command submission to observed completion
5.874 ms; drawable acquisition to submission 45.828 ms; completion to present
47.317 ms; present-request interval 272.170 ms. The command interval includes
submission and waiting and is not hardware-only execution time.

After Android recovery, 8,211,980 bytes of contiguous committed stream and the
entire 67,108,864-byte slot were saved. The stream was not sealed before recovery;
the missing final record header limits the evidence to that captured prefix.
Slot clearing/readback and unchanged Android boot partitions passed. Data boot
record advanced 186 → 187 with fullfsync successful. Device remains assigned to GPU.

Evidence: `log/host/gpu-v209/{continuation,shared-app-check,shared-app-timing,
persistent-dpu-analysis}.json` and
`log/device/nabu-boot-20261111-209/runtime-log/{report,collection,clearing}.json`.

## GPU210 instrumentation

The next kernel measures the real desktop pipeline without changing producer
leases, swap completion rules, queue capacity, deadlines, SMMU attributes or scan
acceptance. It keeps the GPU207 bootstrap; no new app or helper is required.

`NABU DPU PERF` reports the first eight accepted frames, then every 120th frame.
Every successful frame contributes to each intervening window; `n` is that
window's frame count. The ten ordered stages each contain total microseconds,
maximum microseconds and count above 16,666 microseconds:

1. `gap`: interval between requests obtaining the serialized submit lock,
   including idle time. This is not a rendering time or unique-image count.
2. `admission`: entry through submit/state locks and waiting for queue capacity.
3. `acquire`: surface lookup/validation and producer read-lease acquisition.
4. `queue`: enqueue until worker dequeue, including time the worker is busy.
5. `producer`: worker wait for the captured GPU writers to finish.
6. `init`: mapper readiness/first identity activation.
7. `map`: descriptor pinning, page table mapping and publication.
8. `scan`: submit through observed hardware acceptance, including scheduling.
9. `retire`: mapper acceptance, old mapping release, producer/surface release and
   ledger completion. This is release work, not the old surface's scan lifetime.
10. `end-to-end`: present entry through hardware acceptance; excludes retirement.

Each sample also identifies swap, accepted monotonic timestamp, queue depth,
producer status-call count and the latest hardware fence associated with that
read lease. Fence changes alone do not establish distinct image content.
`old-active-us` measures the retired slot's acceptance-to-next-acceptance lifetime.

`NABU DPU WAIT` reports each mode's first eight calls and every 120th call, plus
the first eight timeouts and every 120th timeout. Per-mode counters are cumulative:
calls, actual sleeps, timeouts, non-busy errors, duration total/max and over-16ms
count. Individual samples include requested flags, effective timeout, entry/exit
ledger phase and result. The existing mode 0 retirement, mode 1 display, mode 2
prior-transactions and mode 3 readiness rules remain unchanged. Unsupported input
rejected before the wait loop is not included in these statistics.

Output occurs after measured work and outside display locks. Timing uses the
existing monotonic clock helper; there are no per-frame persistent checkpoints.
Measurements still include scheduling and instrumentation effects and need
correlation with actual desktop interaction and user feedback.

Local validation: whole ARM64 Display object compiled, maximum function stack
816 bytes; 20 real-function flip/mapper/scanout groups, 13 diagnostic isolation
groups and 12 lifecycle/wait groups passed, with ASan/UBSan on the host regressions.
Cloud compilation and GPU210 device results are pending at this revision.
