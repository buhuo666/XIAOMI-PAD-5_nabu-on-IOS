# GPU215 runtime baseline and sustained frame work

On 2026-11-11 the user performed desktop swipes and Settings scrolling, then
confirmed normal desktop/touch but unchanged visible stutter. Both new paired
performance requests succeeded and their complete matching begin/end records
were recovered from the persistent log:

- Before: `25821e554dbf44eab0631dbd9a1c9bb3`, monotonic1321.570076s.
- After: `964652ddf02f4239ba71b55f0cb4f2fd`, monotonic1409.366418s.
- Pair duration87.796342s includes user-response/idle time. Gesture boundaries
  were not instrumented and the interval is not a fixed30-second benchmark.

The native registry confirms requested675000KHz, requestedDDR8363000KB/s and
StockOppAcknowledged=true. Actual clock telemetry remains unavailable.

| Paired GPU measurement | Result |
| --- | ---: |
| Submitted/completed jobs | 892/892 |
| IRQ callback/fence notification deltas | 892/892 |
| New faults/timeouts/poisoned jobs | 0/0/0 |
| All-queue cumulative issue-to-observed-completion mean | 1.881252ms |
| Retained individual job samples | 256/892,28.70% |
| Retained tail queue1 mean | 1.713094ms |

The tail sample is not the whole interaction and none of these durations is
pure GPU hardware execution. GPU214 and215 used different scene mixes; no
same-workload frequency speedup is claimed.

Seven DPU aggregation windows lie wholly within the new request pair and
cover840 accepted transactions. Their mean stage costs are:

| Stage | Mean |
| --- | ---: |
| Serialized request gap | 98.451636ms |
| Admission | 0.014558ms |
| Surface/read-lease acquisition | 1.320118ms |
| Queue | 0.013952ms |
| Producer wait | 0.210680ms |
| Map | 0.559508ms |
| Scan submit through acceptance observation | 1.311024ms |
| Present entry through acceptance observation | 3.433325ms |
| Old-surface retirement, after acceptance | 0.528120ms |

Six of the seven windows have approximately99-100ms mean request gaps. Even
the busier window has90.833ms mean gaps. The exact cause is unresolved: inspect
upstream frame production, native vblank callback delivery and CA pacing.
These aggregated transactions cannot establish unique-image FPS or gesture
responsiveness. The relatively short producer/scan stages justify prioritizing
that upstream investigation while adding hardware and per-frame timing.

The recovery saved17,230,082 bytes of contiguous committed log and the complete
67,108,864-byte slot. The stream was not sealed: complete=false and reason
`no committed record header` describe its end, not loss of the recovered paired
snapshots. Clearing and readback passed, Android boot partitions were unchanged,
Data boot count is193, and the device returned to Android. No extra Android
reboot was performed. Reproduce the summary with
`python log/host/gpu-v215/finalize-baseline.py`.

The next source change adds a separate FrameBench application, retaining the
existing MetalPresent correctness test. FrameBench targets1600x2560 at60/120Hz,
uses asynchronous command completion and three bounded in-flight slots,
records CPU timing in preallocated rows, and exports after each run. It has
opaque-motion and eight-layer alpha scenes,3x60-second runs after3-second warmup,
plus a600-second soak mode. It does not perform per-frame pixel readback or
insert125ms delays. Presented callbacks are explicitly not classified as
hardware acceptance. A frame barcode supports external visual comparison.
Build/device qualification of this new application is still pending.

Evidence: `log/host/gpu-v215/baseline-report.json`, `gpu-stats-resumed-{before,after}.json`,
`timing-persistent.json`, `post-ready/gpu-producer-ioregistry.json`, and
`log/device/nabu-boot-20261111-215/runtime-log/`.
