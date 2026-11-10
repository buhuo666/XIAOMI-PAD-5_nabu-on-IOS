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
