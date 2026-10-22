# Bring-up evidence, 2026-10-22

## Verified milestones

| Component | Actions run | Scope |
| --- | --- | --- |
| Original xnu-8796 kernel | 39750243808 | macOS 14 / Xcode 15.0.1 compile, link, arm64 check |
| Clock fallback kernel | 39762760559 | Adds patch 0085 and tests absent, supplied and zero clock properties |
| DarwinBoot ABI profiles | 39762368133 | Darwin 22/23 compile, host parser/ABI checks, five QEMU tests |
| UEFI observation collector | 39763299490 | Adds NabuProbe.efi and a sixth QEMU test; all pass |
| Real kernel early VM/console startup | 39769172744 | Real xnu-8796 C entry, final TTBR1 mapping, pmap_bootstrap and kprintf startup; simulator only |
| Persistent early-stage mask kernel | 39771320855 | Patch 0086, actual-function mask tests, macOS compile/link and exported-symbol verification |

Clock fallback kernel SHA-256:
`768d5fe74fde124c58fb55365859997cdb98c47fe60d84c88ec3deea63a4b37e`

Current checkpoint-mask kernel SHA-256:
`cdb8e23ba56dcec2d8c2df5f69b1388dd96618759e8ed52e3b54d70bbbe572e6`

These are compiler and emulator results. No physical tablet test was
performed by these runs, and none produces a complete iPadOS installation.
The workflow now selects the checkpoint-mask kernel for subsequent contract
checks; manifests identify the exact kernel run and source lock.

## Interfaces repaired

- Darwin 22 boot_args: command line 608 bytes, bootFlags at 0x2d0,
  memSizeActual at 0x2d8, total 0x2e0.
- Darwin 23 remains separate: 1024-byte command line, offsets 0x470 and
  0x478, total 0x480.
- The diagnostic ADT uses `/arm-io/gic`, one CPU and the nabu 19.2 MHz
  timebase, without storage or PSCI nodes.
- The diagnostic loader requires exactly `nabulog=0 ufsrw=0 cpus=1`,
  no ramdisk, no trust cache/addon placeholders, a 256 MiB conventional
  window entirely below 4 GiB, and the current kernel's fixed GOP contract.
- Patch 0085 preserves nominal XNU clock-accounting defaults when optional
  properties are missing/zero. It does not program hardware frequencies.

## Evidence still required from the device

The old local ADT is unsuitable for this diagnostic: it requests a 4.75 GiB
contiguous window, includes PackedRAMDisk, and uses `/arm-io/intc` rather
than the 8796 kernel's `/arm-io/gic`.

`NabuProbe.efi` can collect the actual GOP and UEFI memory map while remaining
in boot services. Its no-argument mode only prints. Its optional `--save`
mode creates a new report on the application's own filesystem volume.
No device execution is performed by the workflows.

The offline analyzer rejects corrupt/truncated reports and checks current
EL, boot CPU affinity, timer frequency, translation granules, memory
descriptor integrity, low-window feasibility, and framebuffer geometry.
Its positive result is a contract comparison, not permission or proof to boot.

## Remaining work

The first real-kernel QEMU experiment (run 39765266344) entered the actual
XNU assembly entry, as shown by the 64x32 white physical-framebuffer marker,
but did not reach its first C checkpoint. This is a failed experiment,
not a successful kernel boot. Its QEMU GOP adapter also declined activation.

Source inspection found that the loader preserved only 2 MiB VA/PA offsets,
while this nabu kernel uses 16 KiB pages and 32 MiB L2 bootstrap mappings.
The loader and probe now preserve 32 MiB congruence. Host and synthetic
handoff checks cover that constraint. A new experiment must determine
whether this repair permits the real kernel to continue.

Run 39767864244 confirmed the repair: the real kernel reached checkpoints
1 through 7, including C entry, platform discovery, CPU bootstrap and entry
to `arm_vm_init`. The framebuffer console reported:
`Expected 64 seed bytes from bootloader, but got 0. @prng_random.c:64`.
The QEMU GOP adapter also activated successfully with ACPI disabled.
The next repair supplies `/chosen/random-seed` from UEFI RNG before handoff;
it does not weaken the kernel's entropy requirement or bake a reusable seed
into an artifact.

Run 39769172744 passed the early-VM milestone. The actual kernel reached
stages 1-16, 19 and 20, including `arm_vm_init returned`, `pmap_bootstrap done`
and `kprintf startup complete`. Stages 17/18 are the optional framebuffer
serial-console path, not missing sequential checkpoints in this setup.
All 392 artifact file hashes were checked after download.

The kernel subsequently panicked because an interrupt took 17.344 ms against
a 13.631 ms elapsed-time hygiene threshold under QEMU. A passed observation
milestone is not a stable running kernel. Later emulator experiments use
the kernel's existing `wdt=-1` option and record that policy explicitly;
physical-device diagnostic settings remain unchanged.

Run 39770758940 also passed the VM milestone with the emulator watchdog
policy and reached IOKit, then reported `IONVRAMCHRPHandler creation failed`
because the minimal emulator ADT lacked a NVRAM startup snapshot.
The next experiment reuses `empty_nvram_proxy` from the pinned UniXNU tree.
It supplies only a fresh empty 8 KiB CHRP image in guest RAM, not a hardware
NVRAM controller. Its partition bounds, CHRP checksums and Adler checksum
are checked before use.

Run 39772752656 passed with kernel 39771320855. All twenty checkpoint bits
were read from `_nabu_early_stage_mask` (`0x1ffffe`), including the real
framebuffer mapping path (17/18). The final captured frame had no decoded
panic text, and all 393 artifact file hashes matched after download.
This is not a no-panic guarantee: DEVELOPMENT defaults suppress kprintf,
and a single register snapshot does not establish forward progress.
The follow-up experiment explicitly enables verbose/development kprintf,
samples registers every ten seconds, and pauses the VM for consistent final
screen/memory/register capture.

Run 39774060917 enabled DEVELOPMENT kprintf and captured nine periodic CPU
snapshots plus a final paused snapshot. All twenty checkpoints still passed;
all 394 artifact hashes were verified locally. LLVM symbolization against the
exact kernel places every sample in `vm_page_grab_options`, `vm_page_wait`,
or their lock/preemption helpers. This is evidence of a repeated page-allocation
wait path, not successful post-startup progress. No new panic was decoded.
The next emulator experiment increases only its allocated window from 256 to
512 MiB and captures actual free/reserved/target/wired/delayed page counters.
The physical-device diagnostic contract remains 256 MiB.

Run 39775489349 allocated 512 MiB and passed all loader, contract and emulator
checks; all 400 artifact hashes were verified after download. The actual
kernel logged scheduler, BANK, IPC, HMAC-SHA256 and libpthread initialization.
Nine periodic snapshots and the final capture were in the timebase, idle,
waitq or recount paths, rather than the earlier page-allocation wait loop.
The paused counters were: free 31007, reserved 130, target 144, wired 1712,
delayed 0. The symbolizer's kernel hash matched the selected kernel.
No panic text was decoded from the final framebuffer.

This establishes progress beyond the 256 MiB experiment, not a completed
OS boot or a proven minimum memory requirement. The follow-up keeps 512 MiB
and requests the existing `serial=1` output option to expose ordinary
`printf`/IOLog boot messages as well as kprintf.

Run 39776490485 passed on macOS and all 400 artifact hashes matched locally.
Ordinary logging now confirms that IODTNVRAM accepted the 8 KiB CHRP snapshot
and parsed its common partition. The DT platform expert registered. Scheduler
maintenance, averages and thread-dispatch functions were sampled in addition
to idle/timebase functions. No panic text was decoded from the captured frame.
Some device messages describe stubs (including a static battery fallback);
their registration is not hardware support.

There was no captured `bsd_init enter` or root-device-wait message, so neither
BSD entry nor a root filesystem wait is claimed. The next experiment enables
XNU's existing `startup_debug=1` and captures `_startup_phase` directly, without
changing the kernel or adding any storage.

1. Establish a reversible UEFI invocation path for this actual tablet,
   then collect its memory/GOP/CPU report.
2. Compare the 12 GiB inventory with reserved regions and usable UEFI ranges.
   A total capacity alone is not a contiguous allocation guarantee.
3. Resolve the fixed framebuffer contract (0x9c000000, 1600x2560,
   stride 6400, BGRA32) against actual observations.
4. Validate real kernel entry, interrupt/timer behavior and memory ownership.
5. Integrate a version-matched userland, storage and prelink path only after
   the diagnostic handoff is understood.

No partition editing, flashing, NVRAM updates, or access to the tablet's
Android data is part of the completed work.
