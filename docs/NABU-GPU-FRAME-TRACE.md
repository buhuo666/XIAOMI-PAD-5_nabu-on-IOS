# GPU / DPU bounded frame trace

2026-11-11 implementation; device capture and overhead qualification remain pending.

`NabuGpuTrace` records fixed 48-byte little-endian `<QQQQQII>` rows:
`time_us, identity, a, b, c, event, window`. CPU times use
`mach_absolute_time` converted to microseconds. Raw GPU ticks have their own
clock contract and calibration records; see `analysis/nabu-a640-timestamp-audit.md`.

## Capture and durable export

The administrator IORegistry commands are `Start(DurationMs)`, `Snapshot`,
`Stop(Window)`, `Read(Window, Offset)` and `Acknowledge(Window, Count)`.
Each request/result has a matching `RequestID`. GPU publication and the root
system-services helper must both be rebuilt. The paired host entry point is:

```powershell
python tools/nabu_frame_trace.py start --duration-ms 70000 --output log/host/TRIAL/trace-start
python tools/nabu_frame_trace.py snapshot --output log/host/TRIAL/trace-state
python tools/nabu_frame_trace.py stop --window WINDOW --output log/host/TRIAL/trace-stop
python tools/nabu_frame_trace.py export --window WINDOW --output log/host/TRIAL/trace-WINDOW
python tools/analyze_nabu_frame_trace.py --input log/host/TRIAL/trace-WINDOW --output log/host/TRIAL/software-timing.json
python tools/analyze_nabu_a640_timestamps.py --input log/host/TRIAL/trace-WINDOW --output log/host/TRIAL/hardware-timing.json
```

Use the returned numeric window, and select a capture long enough to contain
the app's actual 60-second interval. `Export` reads only an immutable stopped
window, transfers its raw binary through the existing paired AFC service,
validates the record identities/count/time bounds, saves and fsyncs
`records.bin` plus `metadata.json`, then acknowledges the complete export.
`records.csv` is a secondary representation. Failed or interrupted export can
be repeated. Reading the final chunk alone does not permit overwriting a
window; a complete contiguous read and explicit acknowledgement are required.

The software analyzer joins job completion IDs, worker sequences, read-lease
writers and swap IDs. It reports stage distributions and partial boundary
records separately. Use `--start-us` and `--end-us` to select an App interval
fully inside the trace. Its accepted-transaction rate is not unique-content
FPS; overflow makes the complete rate null. The hardware analyzer reports
SlotBusy and bracket/validity records without a final tick pair, even when
the recorder dropped no rows. These counts constrain the reported quantiles.

Recording performs no allocation, disk output or formatting. The IRQ-safe lock
protects one record at a time. Chunk copies happen outside that lock after the
window is stopped; control calls share the publication export lock. Window
stop time is read inside the IRQ-safe lock so a concurrent final record cannot
land after an earlier sampled end time. GPU locks never depend on the trace
control lock. The DPU producer table uses the versioned registration symbol
`nabu_dpu_register_producer_v2`, so old three-pointer tables cannot be mixed
silently with the extended table.

## Capacity and measurement scope

The buffer has 1,048,576 records (48 MiB), allocated before recording starts.
At 120 frames/s with three GPU jobs/frame, an estimated 5.5–6.5k events/s
requires roughly 330–390k records for 60 seconds. The buffer permits about
17,476 events/s for a 60-second interval. These are capacity estimates, not
device measurements. Every overflow increments `dropped`; never label an
overflowed window a complete sample or use its quantiles as full-run results.

Each full 60-second capture is exported separately. Start/end times must be
matched to FrameBench's CSV; USB export time must not be assumed to fit the
app's short between-run pause. A 600-second load uses full-run app and DPU
counters plus separately aligned head/tail windows. This buffer is not a claim
of complete 600-second per-event coverage. Record-on versus record-off timing,
event rate, dropped count, and lock/IRQ impact still require device validation.

## Software event identities

| Event | identity | a, b, c |
|---|---|---|
| GpuAccepted | scheduler completion ID | queue, resources, GPU dependency count in high32 / DPU reader count in low32 |
| GpuIssued | scheduler completion ID | queue, hardware fence, resources |
| GpuCompleted | scheduler completion ID | queue, hardware fence, completion-worker sequence (0 outside that worker) |
| GpuIrq | cumulative IRQ entry | interrupt number, 0, 0 |
| WorkerBegin / Locked / End | worker sequence | Begin records latest IRQ count; other payloads zero |
| ProducerWriter | read-lease identity | scheduler completion ID, hardware fence, queue |
| ProducerCallback | read-lease identity | latest fence, status, slot |
| Present | swap ID | surface ID, 0, 0 |
| Queued / DisplayWorker | swap ID | surface ID, queue depth, read-lease identity |
| ProducerReady | swap ID | read-lease identity, fence, status |
| Mapped | swap ID | surface ID, mapping token, IOVA |
| ScanSubmit / Accepted | swap ID | surface ID, mapping token, scan sequence |
| ScanAcceptedCounters | swap ID | scan sequence, observed INTF1 frame, observed INTF2 frame |
| Retired | old swap ID | old surface ID, old mapping token, replacing swap ID |
| Vblank | master sequence | IRQ count, INTF1 frame, INTF2 frame |
| VblankNotify | master sequence | original IRQ time in us, IRQ count, 0 |
| NativeVblankDelivery | master sequence | original IRQ time in us, async-send result, 0 |

`ProducerWriter` records both the lease's initial writer relation and each
writer's completion; repeated relations are not extra GPU jobs. Vblank delivery
records include every subscribed client's attempted send, not one event per
physical frame. WorkerBegin's IRQ counter is a snapshot, not proof that one
specific IRQ caused one worker. GPU completion and DPU acceptance are not
proof of distinct visual content. App frame/barcode and compositor surface
identity still need correlation for actual new-image FPS.

Rejected presentation requests retain their original return value. Reason
codes are 0 short payload, 1 extra surfaces, 2 source rectangle, 3 destination
rectangle, 4 no surface and no clear bit. `PresentRejected` stores reason,
status and per-reason count (payload byte count for short requests).
`PresentSurfaceList` packs SID0/1 and SID2/3 into low/high32 pairs and records
the clear bits. `PresentLayerFlags` packs four enabled words and the set mask.
Source/destination events pack each layer's four raw rectangle words into two
pairs, with the layer index in `c`. Separate logs preserve these fields on the first and
every 120th rejection of each reason even when capture is off.

The legacy `bo_slot=4` diagnostic bucket aggregates all client slots >=4;
the ABI array is still 5x6. It must not be interpreted as process slot4 or
expanded by changing only the publisher's print loop. Resource budgets are
separately maintained for the actual 24 client slots.

## Local validation

- `tools/check_nabu_frame_trace.py`: production recorder boundaries, overflow,
  contiguous retry/acknowledgement, 12,000 serialized concurrent records,
  durable host export and actual rejection logging/field packing (ASan/UBSan).
- Current Trace/Publish/Scheduler/Resources/Display ARM64 objects:
  `log/host/gpu-120fps/trace-integration-arm64/report.json`.
- Actual DPU lifecycle 12 groups, flip 20 groups, surface leases 13 groups,
  GPU IRQ handling and deferred close six groups passed with trace fixtures.
- Full MiniIOMobileFramebuffer object, system-services helper SDK compilation,
  final linked image and physical-device capture require their respective CI
  and runtime checks. A host mock or ARM64 object alone does not qualify them.
