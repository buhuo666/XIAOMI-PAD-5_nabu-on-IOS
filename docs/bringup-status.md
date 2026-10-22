# Bring-up evidence, 2026-10-22

## Verified milestones

| Component | Actions run | Scope |
| --- | --- | --- |
| Original xnu-8796 kernel | 39750243808 | macOS 14 / Xcode 15.0.1 compile, link, arm64 check |
| Clock fallback kernel | 39762760559 | Adds patch 0085 and tests absent, supplied and zero clock properties |
| DarwinBoot ABI profiles | 39762368133 | Darwin 22/23 compile, host parser/ABI checks, five QEMU tests |
| UEFI observation collector | 39763299490 | Adds NabuProbe.efi and a sixth QEMU test; all pass |

Clock fallback kernel SHA-256:
`768d5fe74fde124c58fb55365859997cdb98c47fe60d84c88ec3deea63a4b37e`

These are compiler and emulator results. No physical tablet test was
performed by these runs, and none produces a complete iPadOS installation.
The workflow now selects the clock-fallback kernel for subsequent contract
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
