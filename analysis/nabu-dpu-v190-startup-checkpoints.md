# GPU190: first-frame handover checkpoints

2026-11-10, Asia/Shanghai.

GPU188 and the identical-image GPU189 both went black after XNU boot while
iPadOS initialized its graphical interface. GPU189's full 64 MiB slot was
collected and cleared with readback; 799,545 bytes of the runtime prefix were
saved, APFS boot count was 168, and Android boot partitions were unchanged.
GPU188 saved 818,157 bytes. Both prefixes end around the first 1600x2560 BGRA
IOSurface creation, before the first recorded SwapSet. Neither contains a
persisted DPU mapper operation or panic. The periodic writer's last prefix is
not proof that execution stopped at the final logged line.

GPU187 differs: its incorrect 4 KiB-derived pmap page number rejected the first
display table allocation, and subsequent logs continued for over five minutes.
GPU188 fixed that query to use the VM page size. This makes the newly reachable
handover path worth tracing, but does not establish the failing operation.

The opt-in `nabu-dpu-trace=1` candidate commits diagnostic markers through the
existing authorized log writer before proceeding through surface user mapping,
producer readiness, table allocation/initialization, source qualification,
VIG quiesce, CB2 programming/TLBSYNC, VIG resume, surface mapping, submit and
hardware acceptance. It does not seal capture or create another storage path.
Each checkpoint targets a captured prefix and releases the root read lock
between records. No checkpoint is called under the surface lock, display state
lock or an interrupt lock. Ordinary surface/frame tracing is limited to the
first large surface, first present call and first frame worker.

Checkpoint delays perturb startup timing and are diagnostic only. A returned
checkpoint or successful compile is not evidence of pixels on screen. A failed
commit is reported and does not fabricate progress or display completion.

Local validation:

- Actual log runtime/parser/pump/finish/checkpoint tests under ASan/UBSan passed.
- Actual mapper fixture, 4/16 KiB page regression and ARM64 compile passed;
  maximum function stack was 336 bytes, and fault reads remain free of locks,
  stores and waits.
- Ten actual-code listener/client/wait groups passed with host threads.
- DPU display backend ARM64 compilation passed.
- Installer repeat and surface-lock marker placement checks passed.
- Complete local MiniIOSurface/framebuffer compilation is unavailable with
  these exported headers (private typed-allocation definitions fail, as in
  GPU187); complete consuming-kernel validation must come from macOS CI.

Live trial state and subsequent findings: `log/host/gpu-v190/continuation.json`.

## Live result

Complete CI 42818600464 and the 64-object link/loader checks passed. The user
confirmed the same black screen entering iPadOS. The full 64 MiB slot and
818,053 bytes of runtime prefix were collected and cleared with readback;
APFS count is 169 and Android boot partitions are unchanged.

Committed markers prove success of user surface mapping, producer wait, native
VM cache queries, inactive display table construction and source preflight.
The last marker is `xin-quiesce-enter` at 49.389396 seconds. No return from
quiesce and no entry to CB2 activation were committed. The evidence narrows the
stall to quiesce or the checkpoint's return boundary, not IOSurface creation or
the pmap page-number query. It does not identify an individual MMIO access.

GPU191 corrects the existing quiesce ordering so both VIG force clocks are set
before the first VBIF access. The fixed Android source's
`sde_vbif_set_xin_halt` sets the client force clock before the request-register
read inside `sde_hw_set_halt_ctrl`. Our previous code read that register first.
The register base still matches the saved device DTB; it was not changed.

The regression fixture now rejects any VBIF access before the force clocks.
GPU190's actual quiesce body fails that assertion; the corrected body passes,
including inherited request ownership and resume preservation. This test
models the source ordering, not physical bus behavior. The new scanout core
and display backend compile for ARM64; the core's maximum stack is 128 bytes.

GPU191 also records entry and return of the first eight quiesce reads and three
writes, including write completion barriers. This is confined to normal-thread
quiesce with tracing enabled, outside display state locks. It will distinguish
clock-register, VBIF request and halt-status access if the stall remains.
