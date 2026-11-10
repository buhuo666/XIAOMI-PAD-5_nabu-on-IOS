# GPU185: panel already scans at approximately 120 Hz

Temporary boot: `log/device/nabu-boot-20261110-185/run.json`.
Kernel source commit: `097ade7` (full commit in the continuation record).
Raw diagnostic: `log/host/gpu-v185/dpu-snapshot.log`; parsed registers and
counters: `log/host/gpu-v185/dpu-snapshot.json`.

Both INTF1 and INTF2 advanced from frame 2539 to 2568 over a 250,334 us
sampling interval. There were 29 observed changes, each exactly one frame,
219 polls, and a maximum poll gap of 1,145 us. The interval between first and
last observed edges divided by the intervening 28 frames was 8,330,714 ns on
both interfaces, consistent with 120 Hz. This is bounded polling evidence of
scanout cadence, not proof of 120 distinct application frames per second.

The bootloader's Nabu panel XML also specifies DSIRefreshRate=0x780000
(120 in 16.16). Captured timing totals match it: 884 horizontal clocks,
2,758 lines, 2,560 active lines. The 198 blank lines correspond to about
0.60 ms at 120 Hz. GPU183's fixed-GOP copy commonly took around 2.2 ms, so
waiting for blanking and then copying the whole frame is not sufficient.

The current MiniIOMobileFramebuffer still publishes 60 Hz and generates
software timer notifications. GPU184 qualified shared IOSurface CPU/GPU
pages, but final scanout still uses the actively scanned fixed GOP. Therefore
no panel mode switch is needed to begin 120 Hz integration. Required work is
direct scanout, correct old/new surface ownership, flush acceptance and actual
hardware cadence in the existing native framebuffer notification path.

## Inherited display address translation

APPS access was observed only after the same boot's native USB attachment;
its initialization performs a complete successful scan of 94 implemented SMRs.
The DPU reader then completed all 94 slots and found one route overlapping
the display DT set SID 0x800/mask 0x420:

- SMR slot 3: 0x84200800; S2CR: 0x00000002 (translation type, bank 2).
- CBAR: 0x0001f000, CBA2R: 1, SCTLR: 0x000000e0 (M=0).
- TTBR0/TTBR1, TCR and MAIR are zero. Stage-1 translation is disabled.
- FSR=0x400 does not intersect the kit's FSR_FAULT mask 0xc00001fe.
- IDR0=0x4c017e5e, IDR1=0x60000038, IDR2=0x5555: 94 stream groups,
  56 context banks, 128 global 4 KiB register pages.

Together with both SSPP source registers equaling GOP PA 0x9c000000, this
establishes the inherited bypass path. Ordinary IOSurface pages can be
physically scattered, so they need display mappings before scanout addresses
can be changed. The GPU's IOVA must not be written directly to the DPU.

The snapshot logs only display-overlapping routes. It does not establish that
no unrelated stream uses bank 2. A takeover must inspect all valid routes and
preserve other owners; retain identity access to GOP during the transition.
Native USB's stream 0x140 uses slot4/bank3 and must remain intact.

CTL0, VIG0/1, LM0/1 and INTF1/2 remain the observed pipeline. Each half is
800x2560; the right half starts at x=800. Both use stride 6400 and linear
four-byte pixels. Frame acceptance must include CTL flush completion and a
real frame boundary; only then can old mappings and surface references retire.

## Recovery

User confirmed desktop and touch. Full 64 MiB slot plus 3,277,045 bytes of
runtime prefix were preserved and cleared with readback. APFS advanced to
157; Android boot partitions were unchanged. Device is Android with USB,
still assigned to GPU/display work. No GPU186 log slot or candidate was
prepared. Tearing and end-to-end 120 FPS remain unverified/unfixed.
