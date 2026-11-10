# Nabu SSC clock and configuration evidence — 2026-11-10

The SSC acquisition timestamp must not be replaced by the callback receipt time.
The retained material establishes a 19.2 MHz SSC time unit and XNU's local time
mapping. It does **not yet establish the exact SSC/AP counter epoch in the next
nabu iPadOS run**. The new mapping component therefore defaults to an unconfirmed
epoch and emits no timestamps until the caller explicitly supplies evidence for
the current clock generation.

## Evidence and its limits

| Evidence | Established fact | Limit |
| --- | --- | --- |
| Captured ROM `log/host/sensors-20261109/android/vendor-sensors/sensors/proto/sns_dae.proto:146,192` | Absolute sensor scheduling times use 19.2 MHz ticks since boot. IRQ/read acquisition timestamps are described separately. | Does not identify AP CNTPCT/CNTVCT epoch. |
| `log/host/sensors-20261109/reference/libssc/data/ssc-common.proto:71` | SSC timestamps are described as an internal DSP timer at 19.2 MHz. | Same frequency is not same epoch. |
| `patches/darwinboot/nabu-handoff.patch:72` | Nabu boot rejects a CPU counter frequency other than 19.2 MHz. | Does not validate SSC timestamps. |
| Actual retained 8796 `osfmk/arm64/machine_routines.c:2148–2191` | Generic `ml_get_hwclock()` reads CNTVCT with an ordering barrier; `ml_get_timebase()` adds the per-CPU base offset. | A direct CNTVCT read and a Mach timestamp need not have the same numeric value. |
| Actual retained 8796 `osfmk/kern/clock.c:1691` | `clock_get_uptime` returns `mach_absolute_time`. | It is not continuous time across system sleep. |
| Actual retained 8796 `osfmk/arm64/cpu.c:959–991` | Wake sets the base to `wake_abstime - hardware_counter`, so Mach absolute stops across sleep. The counter may continue or reset. | Backlight off is not evidence that this sleep path ran. |
| Actual retained 8796 `osfmk/arm/rtclock.c:106–138` | Mach units derive from the platform frequency; 19.2 MHz implies 625/12 ns per tick. | This mapping must stay consistent with the actual boot frequency. |

The XNU paths above are under `build/xnu8796-capacity/tree/`. Its wake comment
mentions CNTPCT when describing reset-time initialization, but the actual function
called is `ml_get_hwclock()`, whose generic implementation reads CNTVCT. The code,
not that comment, determines the mapping used here.

Qualcomm's official current reference, retrieved through the configured proxy:

`https://raw.githubusercontent.com/qualcomm/sensinghub/main/utils/inc/qshTimeUtil.h`

Retained as `log/host/sensors-live-20261109/qshTimeUtil.h`. It calls CNTVCT the
QTimer, reads CNTFRQ, and correlates local QTimer reads with Android's
`elapsedRealtimeNano()`. It periodically refreshes that offset, including on
backward time or a forced refresh. Its Android offset calibration brackets local
clock reads; it does not fit a sensor's first arrival to the current OS time.
This is a general Qualcomm implementation reference, not a decompilation of
nabu's shipped HAL and not proof of this board's SSC epoch. Its floating point
conversion and non-Android CLOCK_REALTIME branch were not copied into the driver.

## Retained Android observation

`tools/nabu_android_ssc_probe.cpp:12,40` records reception using CLOCK_BOOTTIME at
millisecond resolution. The same-session capture is
`log/host/sensors-live-20261109/android-after-sensors02/ssc-live.jsonl`.
The derived summary is
`log/host/sensors-live-20261109/android-ssc-clock-envelope-20261110.json`.

For the continuous streams, `received_boottime_ns - SSC_ticks * 625/12` spans:

| Sensor | Samples | Minimum | Maximum |
| --- | ---: | ---: | ---: |
| Mag (`ak09917x` driver) | 500 | −5.350660 s | −5.346488 s |
| LSM6DSO gyro | 263 | −5.315726 s | −5.276566 s |
| LSM6DSO accel | 263 | −5.325459 s | −5.286566 s |

All three raw SSC sequences in this capture are strictly increasing. The negative
offset shows why raw SSC nanoseconds cannot simply be passed off as Android boot
time. The envelope combines epoch offset, acquisition age, transport/scheduling
delay, and millisecond quantization; it cannot separate those components or prove
that SSC equals CNTPCT. The three ALS samples are included in the JSON but are not
used to calibrate time. The original physical-config timestamps are also much
older than receipt; this is allowed by the captured protocol.

## Mapping component

`patches/nabu-sensors/NabuSscClock.h` is freestanding integer code. It has no
clock-reading, transport, allocation, sleeping, or sample-generation behavior.

Capture each ordered local bracket in the serialized worker:

1. Read `clock_get_uptime` as `mach_before`.
2. Execute an ordering barrier and read CNTPCT.
3. Execute an ordering barrier and read CNTVCT.
4. Read CNTFRQ, then `clock_get_uptime` as `mach_after`.

For a hardware counter reading `C` inside that bracket, the fixed local offset
lies in `[mach_before - C, mach_after - C]`. The component intersects those
intervals over successive accepted brackets, separately for physical and virtual
counters. Optional caller-supplied local read uncertainty expands each interval
before intersection; it must be justified by measurement. It is not inferred
from SSC arrivals. The midpoint is the published candidate timestamp; the full
earliest/latest Mach interval is retained in `ClockStamp`.

The candidate formula is `Mach_acquisition = SSC_acquisition + local_offset`,
**only after SSC is independently confirmed to use the selected counter's epoch
in that generation**. Selecting `ClockEpoch::Virtual` (1) or `Physical` (2) is an
explicit trust boundary. `Unknown` (0) is the default. The component does not
claim to infer SSC epoch from the local bracket.

Integration sequence:

```cpp
NabuSsc::ClockMapping mapping;
NabuSsc::ClockQualification qualification;
NabuSsc::ClockCursor cursor_for_each_stream;
// Acquire the first bracket before enabling SSC so new acquisitions follow it.
auto update = mapping.observe(bracket, measured_max_bracket_ticks,
                              measured_read_uncertainty_ticks);
// Candidate domain comes from hardware/API evidence, not sample arrival.
qualification.arm(mapping, independently_selected_epoch, qualification_policy);
// On each later callback: refresh the ordered local bracket first.
// If a discontinuity occurs, close every source and require fresh evidence.
auto corroborated = qualification.consider(mapping, stream_id, is_continuous,
                                          ssc_ticks, suid.low, suid.high);
// Only Qualified confirms the initial epoch internally. ALS cannot contribute.
NabuSsc::ClockStamp stamp;
auto result = mapping.convert(ssc_ticks, cursor_for_each_stream,
                              configured_and_measured_age_bound_ticks, stamp);
// Only Converted permits publishing stamp.mach_ticks; other results are logged.
```

The boot policy supplies a candidate domain. `ClockQualification` performs the
current-session corroboration before its one internal call to `confirm_epoch`.
It requires each explicitly selected continuous stream to provide a minimum
number of strictly increasing samples, with both SSC acquisition span and AP
counter observation span reaching the configured minimum. A single batched
receipt cannot substitute for observations across local time. It checks bounded
nonnegative sample age, maximum sample gaps, and freshness of all required streams
at confirmation. Source SUID changes reset that stream's evidence, so different
devices cannot pool samples under the same stream index. On-change events do not
contribute, even if their stream bit was mistakenly included in the policy.

Arming is one-shot for an instance. Reusing the same boot argument after a
discontinuity is not new evidence; the qualifier permanently retires on a
generation change. The lower-level `confirm_epoch` also rejects an old generation
token and a source change within the same confirmed generation. Samples only
corroborate the candidate domain; they never adjust the local clock offset.

Behavior at uncertain boundaries:

- A bracket wider than the configured limit pauses conversion for that
  observation. A later consistent bracket can recover. Width alone does not
  imply sleep and does not revoke an otherwise established epoch.
- Disjoint offset intervals after accounting for supplied read uncertainty, a
  backward Mach/counter value, an invalid frequency, or explicit `invalidate()`
  closes the epoch gate. Discontinuity is a diagnosis of incompatible readings,
  not a claim that the cause was necessarily sleep.
- Each new segment begins at its first accepted local counter reading. Older
  batches and cached on-change events cannot be projected through its new offset.
  This deliberately drops the uncertain transition interval. No history of
  pre-sleep offsets is invented.
- An old on-change sample inside a continuously validated segment may retain its
  true old acquisition timestamp; the caller can set its age bound to UINT64_MAX.
  An on-change sample before the segment still fails. It is never retimestamped.
- Each stream has its own cursor. Duplicate/backward SSC values within one
  generation and non-increasing published Mach values across generations fail.
  Failure never advances the cursor or supplies a partial timestamp.
- The positive maximum sample age is caller policy. No unmeasured nabu transport
  latency or batching threshold is hard-coded. Future timestamps are rejected.
- Exact integer conversion uses the reduced 625/12 ratio and checked overflow;
  the driver does not require compiler 128-bit division or floating point.

## Configuration units and acknowledgement

Captured ROM sources are under
`log/host/sensors-20261109/android/vendor-sensors/sensors/proto/`.

| Operation | Wire field / event | Units and meaning |
| --- | --- | --- |
| Streaming configure | ID 513, `sns_std_sensor_config.sample_rate` field 1 | float Hz; 513 is also a configuration acknowledgement event. |
| On-change enable | ID 514, empty payload | Same-client repeated enable is documented as a NOP; 514 also serves as acknowledgement. |
| Batching | `sns_std_request.batching` field 1, nested `batch_period` field 1 | uint32 microseconds; maximum delivery interval, 0 disables batching; earlier delivery is allowed. Omitted batching disables it. |
| Retention/flush period | nested `flush_period` field 2 | uint32 microseconds, should be at least batch_period. Omitted with nonzero batch becomes batch_period; otherwise UINT32_MAX. |
| Batch flags | nested bool `flush_only` field 3, `max_batch` field 4 | Both default false; flush_only takes precedence. |
| Flush | request 2 / completion 129 | Empty messages. A QMI response alone is not flush completion. |
| Physical configuration | event 768 | Actual sample_rate, hardware watermark, range/resolution and optional DAE watermark; actual rate can reflect other clients. |
| Sample | event 1025 | Acquisition event, subject to sensor-defined timestamp semantics. |

`sns_client.proto` wakeup delivery (0) sends at sample/batch cadence and can deliver
early at capacity. In that mode queued data does not accumulate indefinitely, so
flush_period is effectively ignored. NO_WAKEUP (1) batches while the AP sleeps.

`sns_std_sensor.proto:389–402` explicitly permits an initial on-change event for
a subsequent client to retain the most recent state-transition timestamp, and a
physical configuration event to retain the most recent configuration-change
timestamp. Neither is a valid fresh-arrival clock probe.

The current common encoder sends only `sns_std_request.payload` field 2, so its
existing requests have batching disabled. Enabling batching requires field 1
encoding in the independent control path. A successful QMI transaction is
transport/control acceptance, not proof of the requested hardware configuration.
Keep the corresponding configuration events and observed stream state separate.

The request proto carries no additional logical client identity. Preserve the
existing QRTR/QMI connection when reconfiguring an existing subscription. A new
QRTR port cannot be assumed to update the prior connection. Exact streaming
replacement behavior still requires client-manager source or same-session
validation; the explicit repeated-request NOP rule above only covers on-change.

## Required device evidence still pending

The minimum acceptable first-confirmation procedure combines established
hardware/interface provenance with current-run corroboration. It does not
require repeating the reverse engineering, proving a mathematical zero offset
from arrival times, or asking for fresh human approval at every boot:

- First establish which AP QTimer domain the SSC interface publishes from shipped
  implementation evidence or an applicable official hardware/interface contract.
  The retained current Qualcomm utility identifies QTimer as CNTVCT, so Virtual
  is the supported initial candidate. Physical requires board-specific evidence
  that SSC follows CNTPCT, or that physical and virtual readings are equivalent
  within the ordered bracket's uncertainty in the current setup.
- Then check multiple continuously acquired same-boot samples against that
  declared domain: strictly increasing SSC ticks, cadence consistent with actual
  physical configuration, a stable frequency and local Mach/counter bracket,
  and a plausible nonnegative `counter_at_receipt - SSC_sample` envelope within
  the configured batching/transport bound. The samples corroborate the declared
  relation; they never determine a fitted additive sample-to-receipt offset.
- If both counters are observably equivalent, retain the domain named by the
  interface evidence (Virtual in the reference utility), and record the local
  equivalence. If they differ and the provenance does not disambiguate them,
  nonnegative ages alone are not enough to choose whichever looks convenient.
- Fresh-run corroboration can be automated. On a discontinuity, invalidate and
  repeat the relation checks against the already established hardware contract;
  another decompilation is not required. The unchanged boot argument by itself
  must not bypass these checks.

The main `NabuSlpi.cpp` path now arms this qualifier instead of confirming directly
from the boot argument. Its initial diagnostic policy selects accel only (mask
1), four samples, at least 100 ms of both SSC and AP counter span, maximum age
1 s, and maximum sample gap 500 ms. Its bracket-width limit is 1 ms, with no added
read uncertainty. These are explicit provisional no-batching trial limits, not
claimed measurements of nabu's actual delivery latency. Stream metadata must
identify a ready continuous sensor; cached ALS cannot qualify. The explicit
`nabu-ssc-clock` domain defaults to 0, so ordinary startup stays unconfirmed.
Mode3 evidence is still required before selecting Virtual or Physical for the
first device trial. Every mapping generation change stops native sources and
does not automatically reopen them.

1. Retain same-run SSC timestamps and ordered AP brackets for continuous
   accel/gyro/mag, with multiple samples and callbacks over time. Record frequency,
   both local offset intervals, SSC monotonicity, source choice and age envelope.
   Merely having 19.2 MHz on both sides is insufficient.
2. Establish the SSC epoch relation using the procedure above. Current Qualcomm source makes
   CNTVCT a concrete candidate, but nabu's shipped implementation and actual run
   remain decisive. A fresh non-cached SSC timer request could help bound the
   relation: `sns_timer.proto` config 512 accepts start_time/timeout_period in
   ticks, event 1025 returns requested and actual timeout, registration event
   1026 acknowledges the selected configuration. No timer probe was executed by
   this subtask; receipt latency would still be an error bound, not an exact
   offset calibration.
3. Measure and document local bracket width/read uncertainty and per-stream
   acceptable acquisition age. Existing Android millisecond receipt envelopes
   cannot provide a precise Mach-side gate.
4. Test real suspend/resume and SLPI restart. A screen power change alone does
   not validate the XNU sleep mapping. Verify that stale proof and old batches
   remain rejected and fresh streams resume only after renewed evidence.
5. Validate native sensor clients, units/axes, reconfiguration, and sustained
   physical behavior separately. This clock work does not establish that iPadOS
   sensor services already work.

## Host validation

Command:

```text
python tools/check_nabu_ssc_clock.py --output log/host/sensors-live-20261109/ssc-clock-qualification-host-20261110
```

Result: **79,807 checks, zero failures**, compiled with GCC `-Wall -Wextra -Werror`
and AddressSanitizer/UndefinedBehaviorSanitizer. Saved report:
`log/host/sensors-live-20261109/ssc-clock-qualification-host-20261110/report.json`.

Cases include positive/negative/full-width offsets, a hardware counter continuing
through Mach-stopped sleep, counter reset, stale proof, invalidated old batches,
cached ALS, duplicate/backward/future samples, read uncertainty and wide brackets,
and timestamp overflow/underflow. Forty thousand rational-conversion comparisons
use an independent 128-bit host oracle. One hundred independent physical/virtual
clock simulations check the known acquisition time lies inside the output bounds
and is not replaced by arrival time.

Qualification cases additionally cover multiple required streams, one-batch
receipt exclusion, source SUID changes, sample gaps, stale per-stream evidence,
on-change exclusion, invalid/unbounded policy, nonzero local offsets remaining
unchanged, and permanent retirement after frequency/generation changes.

These checks validate host-side logic against controlled truth. They do not
validate SSC epoch on nabu or constitute iPadOS sensor operation evidence. This
subtask did not operate, boot, or reboot the device.
