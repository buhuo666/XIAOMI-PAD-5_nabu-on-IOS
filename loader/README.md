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

Host tests compile the actual loader parsers and check both ABI layouts
against the real xnu-8796 header. The pinned kernel from Actions run
39750243808 is parsed without booting it. No filesystem or Apple userland
is included. Compilation and host parser acceptance do not validate
UEFI handoff, actual device memory maps, interrupts, or hardware boot.

QEMU runs ordinary Darwin 22/23 synthetic handoffs, Darwin 22 GOP and packed
ramdisk variants, and eight diagnostic refusals. It checks firmware retention
on refusal and the synthetic payload after ExitBootServices. These results
apply only to the emulator and synthetic payload, never the physical tablet.

Do not flash these EFI drivers as boot images or replace an existing
payload with the diagnostic files. A matching UEFI integration and
device observations are still required.
