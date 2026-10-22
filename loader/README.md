# DarwinBoot ABI and nabu diagnostic builds

This workflow builds standalone ARM64 UEFI loader drivers on macOS 14.
It does not build an Android boot image, firmware image, or iPadOS installation.

The source lock and local patches are included with the build evidence.
Darwin 22 targets xnu-8796; Darwin 23 targets xnu-10063. Their boot_args
structures are different. The ordinary variants retain upstream behavior
and are intended for synthetic regression testing.

The nabu-diagnostic variant requires the exact arguments
`nabulog=0 ufsrw=0 cpus=1`, a 256 MiB conventional-memory window below 4 GiB,
and GOP base 0x9c000000, 1600x2560, stride 6400, BGRA32. It refuses
storage/PSCI node paths and ramdisk/trust cache/GPU addon placeholders.
Its companion ADT records 12 GiB as inventory only; that capacity is not
declared as memory owned by XNU.

All loader variants preserve the kernel virtual-base offset within a 32 MiB
bootstrap block when selecting physical memory. The nabu kernel uses 16 KiB
pages and 32 MiB L2 mappings; matching only a 2 MiB offset is insufficient.
This stronger constraint also satisfies 4 KiB-page / 2 MiB-block kernels.
The diagnostic ADT includes a 64-byte `/chosen/random-seed` placeholder.
Before handoff the loader replaces it through `EFI_RNG_PROTOCOL`, refusing
an unavailable, failed or all-zero result. Seed bytes are never printed.
The real-kernel QEMU experiment adds a host-backed virtio RNG.

Host tests compile the actual loader parsers and check both ABI layouts
against the real xnu-8796 header. The pinned kernel from Actions run
39771320855 is parsed without booting it. No filesystem or Apple userland
is included. Compilation and host parser acceptance do not validate
UEFI handoff, actual device memory maps, interrupts, or hardware boot.

QEMU runs ordinary Darwin 22/23 synthetic handoffs, Darwin 22 GOP and packed
ramdisk variants, and eight diagnostic refusals. It checks firmware retention
on refusal and the synthetic payload after ExitBootServices. These results
apply only to the emulator and synthetic payload, never the physical tablet.

## Firmware information collector

`NabuProbe.efi` is a standalone UEFI application. It reports CPU ID registers,
timer frequency, all UEFI memory descriptors, a possible low 256 MiB window,
and GOP geometry. It stays in boot services and returns to firmware.
Version-2 reports also record UEFI RNG protocol presence, without requesting
random bytes. Presence is only a prerequisite; the loader checks GetRNG.
Its memory candidate is a snapshot, not an allocation or proof of bootability.
Conventional memory is not the total physical DRAM inventory.

With no arguments it prints only. The exact optional argument `--save` writes
a new `nabu-probe-0001.txt` (or the next unused number) in the root of the
application's own filesystem volume. Use that option only when the application
is loaded from the intended removable test volume. It does not overwrite an
existing report. File writes occur only with this explicit option.

This application is not an Android boot image. Installing a compatible UEFI
environment and choosing a reversible device boot method remain separate work;
no flashing or repartitioning commands are provided by this workflow.

Analyze a saved text report with:

```sh
python3 loader/scripts/analyze-nabu-probe.py nabu-probe-0001.txt --output probe-analysis.json
```

The analyzer checks report completeness, descriptor count, alignment, overlap,
totals and candidate bounds, then compares the CPU/timer/GOP observations with
the diagnostic contract. A compatible report still has `ready_to_boot=false`:
it cannot prove device identity, successful allocation or a kernel boot.

## Optional real-kernel emulator observation

The manual `observe_kernel` input adds a separate experiment after all normal
tests. It uses QEMU `virt` with a `max` CPU, GICv3 and 2 GiB RAM. A test-only
driver validates the QEMU FDT before configuring ramfb at the kernel's fixed
0x9c000000 address. This driver is excluded from default builds.

The experiment runs the actual compiled open-source kernel with an
emulator-specific ADT and no root filesystem. It captures the serial log,
display, physical framebuffer, CPU registers, exception log and early checkpoint
markers. ACPI is disabled so the adapter can use the QEMU FDT. The experiment
fails if the kernel's post-VM-mapping marker is not observed; raw evidence is
still uploaded. These observations never establish physical nabu support or
an iPadOS userspace boot.
The emulator command line uses `wdt=-1` because host emulation latency can
trip interrupt/preemption elapsed-time hygiene limits. This policy is
reported in the observation and is not a physical-device recommendation.
The report separately records an observed early panic even when the
early-VM milestone was reached.

The real-kernel experiment enables the existing `nabu-fbcon` implementation
and supplies the pinned UniXNU generator's empty volatile CHRP NVRAM snapshot.
No NVRAM persistence controller is installed. Patch 0086 retains a RAM-only
checkpoint mask when framebuffer console initialization clears the screen.
The exact Mach-O symbol determines the mask offset; QMP capture is bounded
by the physical ownership window logged by DarwinBoot.
DEVELOPMENT kprintf is explicitly enabled only in the experiment. Periodic
register snapshots help distinguish forward progress from one final address;
the VM is paused before the final memory/display/register capture.
The current emulator experiment allocates 512 MiB after a 256 MiB run repeatedly
sampled the page-allocation wait path. It also captures five VM page counters
from exact exported symbols within the loader-owned window. This allocation
change applies only to the emulator experiment. The guarded nabu diagnostic
profile continues to require exactly 256 MiB.

`loader/scripts/symbolize-registers.py` resolves sampled PC/LR addresses with
`llvm-symbolizer` against the exact kernel and records its SHA-256. The result
is a set of observations, not a backtrace or an automatic progress verdict.

`loader/scripts/decode-nabu-framebuffer.py` extracts the exact `_iso_font`
from the supplied kernel's Mach-O symbol table and decodes matching 2x-scaled
console cells into `console.json`. This exposes early panic text without
assuming a host font. Wrapped lines remain in physical framebuffer row order.
Build manifests and raw evidence are also recorded when an experiment fails.

Do not flash these EFI drivers as boot images or replace an existing
payload with the diagnostic files. A matching UEFI integration and
device observations are still required.
