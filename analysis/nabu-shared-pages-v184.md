# GPU184: connection capacity and inherited display observation

GPU183's recovered kernel log proves the test never reached shared-memory
rendering. At 1158.304360 s, MetalPresent PID 324 requests a ninth connection:
slot=8, active=8, capacity=8, status=e00002db (`kIOReturnNoSpace`). The eight
live clients are mediaserverd, backboardd, SBRendererService, FitnessWidget,
chronod, SpringBoard, Preferences and Spotlight. Their enumeration connections
closed successfully; no failed teardown accounts for this exhaustion.

Cached imports were enabled successfully on chip 06040001. The user reports a
smoother desktop with tearing; this is not a pixel-coherence or 60 Hz pass.
8,606,535 bytes of runtime prefix and the complete 64 MiB slot were preserved,
the slot was cleared with readback, APFS advanced to 155, and Android boot
partitions were unchanged. Receipts: `log/device/nabu-boot-20261110-183/`.

## Capacity change

Keep GPU181's eight VA windows exactly. Add sixteen 128 MiB windows at
0x80000000..0x100000000. All 24 clients have eight disjoint scheduler queues
(192 of the existing 256). The compositor retains its 1 GiB window; no old
window is reduced and no firmware/GMEM/ring address is reused.

The A640 SMMU already uses 32-bit TTBR0 input. Expand only its software arena
to cover that full 4 GiB, with 1,048,576 leaf slots and 2,053 table pages
(1 L1 + 4 L2 + 2,048 L3). This adds 4,202,496 bytes of page-table storage;
VA reservations do not allocate BO pixels. The shared SMMU prepare routine
accepts the larger explicit budget. GMU still passes its original 2 GiB
extent, 524,288 leaves and 1,027 table pages. Existing class member layout and
alias scratch capacity are unchanged. GPU mappings continue to use the same
physical IOSurface pages and WB/outer-shareable PTEs.

Production overlays are compiled for Publish, GpuContext and SmmuContext;
other GPU and display01 objects remain those used in GPU183. Userland and
the shared-source App are reused without modification.

## Bounded display observation

An optional `NABU_DPU_SNAPSHOT` hook runs once on the sleepable GPU bring-up
thread, after the inherited framebuffer has initialized and outside display
locks. It captures candidate CTL/LM/SSPP/INTF registers and up to 250 ms of
frame/line counters. Only APPS SMMU IDR0/GFSR are read (depth 0); the old
unqualified SMR/CB reads remain disabled. It does not alter display registers,
provide hardware vsync, switch scanout addresses, or fix tearing itself.

## Local verification and remaining device work

- ASan/UBSan runs the production slot allocator, reproduces GPU180/183 launch
  order and checks all window pairs, saturation/reuse and reserved regions.
- Actual production live SMMU code prepares the full 4 GiB graph. All 32
  endpoints of the new windows map to their expected physical pages and WB
  attributes, unmap and synchronize TLB; the final graph is empty. Old table
  and leaf budgets are independently rejected. MMIO is a host fixture.
- DPU production reader passes 334 source-reference register checks and host
  fixtures; ARM64 compile/LLVM inspection shows no volatile stores, and max
  stack is 432 bytes.
- The linked 63-object kernel preserves 48 original component extents and
  passes actual near/far ARM64 branch decoding and return-trace replay.

Device acceptance remains pending: ninth-client creation, strict 64-frame
dirty-source/prewarmed-target verification with zero copied/shadow buffers,
then inherited display decoding for synchronized same-page scanout. The App
has a fixed delay and readback, so it is not a 60/120 Hz benchmark.
