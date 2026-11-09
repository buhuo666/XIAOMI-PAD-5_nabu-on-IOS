# SLPI root-PD census candidate

This opt-in candidate is compiled for XNU 8796 / iPadOS 16.5 arm64. It does not
publish an iPadOS sensor or claim a valid sample. `nabu_slpi_start()` does nothing
without `nabu-slpi=1`; with the argument it schedules a separate worker after
60 seconds. The default boot path remains inactive until the entrypoint is linked
and explicitly enabled by the caller.

## Actual board inputs

The 2026-11-09 Android capture is stored locally at
`log/host/sensors-20261109/android/device-tree.tar` and `slpi-firmware/`.

- `soc/qcom,msm-ssc-sensors/qcom,firmware-name` overrides `slpi` with `slpi_nb`.
- PAS id 12, reserved memory `0x97b00000..0x98f00000`, SMEM remote host 3.
- SMP2P ids 481 inbound / 430 outbound; APCS `0x17c0000c`, doorbell bit 26.
  The Android `qcom,smem` cells are inbound then outbound. Run173 used these
  backwards and timed out before observing ready; that direction is corrected.
- GLINK descriptor/TX/RX ids 478/479/480 within host 3, doorbell bit 24.
- The original `IPCRTR` receive pool is 5×2048 + 3×8192 + 2×17408 bytes.
- `vdd_cx-supply` phandle `0x6c` resolves to
  `rpmh-regulator-lcxlvl/regulator-pm8150-l8-level`, resource **lcx.lvl**.
- `vdd_mx-supply` phandle `0x7e` resolves to
  `rpmh-regulator-lmxlvl/regulator-pm8150-l4-level`, resource **lmx.lvl**.
  Both requested levels are 385 (TURBO 384 plus regulator consumer offset 1).
  The candidate resolves actual ARC command addresses/positions from command-db.
- The AOP load-state resource is `slpi`; the DT signals AOP via `slpi-pil`.

The original MDT contains 20 effective PT_LOAD segments, all marked relocatable.
Its link range is `0x97300000..0x98700000`. The loader must add `0x00800000` to
each segment destination; the end then equals the original reserved-memory end.
The signed MDT itself remains unmodified. The packager keeps all 19 file-backed
load segments (6,341,840 bytes) and records the zero-filled final segment.

## Implemented boundary

The worker prepares host-3 SMEM, performs AOP and LCX/LMX/XO votes, loads and
authenticates the original relocated firmware through PAS12, polls SMP2P ready,
opens GLINK `IPCRTR`, and searches QRTR announcements for service 400. It records
the announced node/port; no destination from the Android run is hard-coded.

GLINK opening is limited to 5 seconds, discovery to 10 seconds, and close to
1 second. The worker also limits the transport loop using the actual kernel
clock. Missing service 400 exits with an explicit timeout and no native sensor
publication. It requests force-stop and PAS shutdown; failed PAS shutdown keeps
metadata/mappings alive rather than freeing memory still owned by the DSP.

The firmware, AOP and secure-monitor sequencing follows the project's existing
ADSP implementation, with independently resolved SLPI resources. This is **host
verified, not device verified**. APPS loops are finite, but a secure-world SMC
that does not return cannot be forcibly timed out from this worker. The known
ADSP SMC continuation stall therefore remains a first-boot limitation here too.

Android starts `sscrpcd sensorspd` after booting SLPI. This candidate does not
implement FastRPC `INIT_ATTACH_SNS` or reverse file requests for DSP libraries,
sensor config, and per-device registry/calibration. Root-PD ready, or even a QRTR
announcement, cannot be reported as working sensor data. Those are explicit
remaining dependencies for the runtime provider.

## Build and checks

```
python tools/prepare_nabu_slpi_checks.py --firmware log/host/sensors-20261109/android/slpi-firmware --device-tree log/host/sensors-20261109/android/device-tree.tar --output log/host/sensors-smp2p-20261109/slpi-host
python tools/prepare_nabu_slpi_firmware.py --firmware log/host/sensors-20261109/android/slpi-firmware --output artifacts/nabu-slpi-firmware-census-20261109
python tools/prepare_nabu_slpi_object.py --compile-command build/nabu-aes-v32/compile-command.json --output artifacts/nabu-slpi-object-census-20261109
```

Host checks execute the actual image parser, SMEM/SMP2P helpers and GLINK state
machine. They cover original MDT relocation, host-3 isolation, stage failures,
shutdown retention, fragmented SSC announcements, missing service and silent
peer deadlines. The compiled object has no automatic module initializer.
Link integration must add `NabuSlpi.o`, invoke `nabu_slpi_start()` from the existing
late-init hook, and stage the packaged originals under `/fw/`. Existing validated
objects and the normal boot argument set need not enable this candidate.
