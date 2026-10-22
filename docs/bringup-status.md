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
| Scheduler/VM progress with 512 MiB | 39775489349 | Exact-kernel PC/LR symbols and paused VM counters; no physical-device claim |
| Pre-BSD startup trace | 39778361201 | EARLY_BOOT/LOCKDOWN callback phases completed; CPU matching gap identified |
| CPU driver and BSD root-device search | 39779752907 | Single-CPU SGI verified, BSD/autoconf completed, captured HFS root-device wait |
| Enforced BSD/root-wait observation | 39783240494 | All six explicit progress checks passed; 402 artifact hashes verified |

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

Run 39778361201 passed and all 401 artifact hashes matched. Startup tracing
and the actual `_startup_phase=0xffffffff` establish completion of the
EARLY_BOOT and LOCKDOWN callback phases. The last bootstrap message was
`PE_lockdown_iokit`; the platform expert subsequently registered, but no
`bsd_init enter` was captured.

Source tracing found that the experiment's CPU compatible list contained only
`arm,armv8`, while this exact kernel's NabuCPU personality matches
`qcom,kryo485`. Consequently it could not run the driver that calls
`ml_set_max_cpus`; `kperf_init_early`, immediately before BSD entry, waits on
that publication. This is a source-supported explanation to verify, not yet
a measured stack trace. The next experiment adds the matching string to
the emulator CPU node and captures `_max_cpus_initialized`. It still selects
one CPU and supplies no PSCI node, extra CPUs, storage or root filesystem.

1. Establish a reversible UEFI invocation path for this actual tablet,
   then collect its memory/GOP/CPU report.
2. Compare the 12 GiB inventory with reserved regions and usable UEFI ranges.
   A total capacity alone is not a contiguous allocation guarantee.
3. Resolve the fixed framebuffer contract (0x9c000000, 1600x2560,
   stride 6400, BGRA32) against actual observations.
4. Validate real kernel entry, interrupt/timer behavior and memory ownership.
5. Integrate a version-matched userland, storage and prelink path only after
   the diagnostic handoff is understood.

The emulator milestones above did not edit tablet partitions, flash images
or update hardware NVRAM. The later, separately authorized physical partition
operation is recorded below.

## CPU publication and BSD confirmed (2026-10-22)

Run 39779752907 completed on macos-14; all 402 artifact sizes and SHA-256
digests matched after download. The paused `_max_cpus_initialized` is 1,
and the exact-font decoder recovered:

- `NABU CPU: 1/1 CPUs initialized, SGI1 verified`
- `NABU BSD: bsd_init enter`
- `NABU BSD: after bsd_autoconf`
- `NABU: setconf before IOFindBSDRoot`
- An `IOMedia` / `Apple_HFS` root-device matching wait.

This verifies the emulator CPU-compatible repair and progress beyond the
earlier pre-BSD wait. It does not provide a root device or mount a filesystem.
The selected kernel hash is unchanged. No panic text was decoded, which is
not a guarantee that no panic occurred outside the captured framebuffer.
The NVRAM serialization failure reported no `_nvramController`; the emulator
still has only a volatile CHRP snapshot and no persistence controller.

Subsequent observations now report explicit CPU/BSD/root-search messages and
require that demonstrated milestone, successful decoding/symbolization and
no captured panic to pass. Early VM markers alone no longer pass this
real-kernel experiment. These are emulator requirements, not tablet results.

Run 39783240494 verified the stricter observation on macos-14 at source
`6d8a772085574c8d1eb580ad0bb0d70709783eb7`. All six explicit progress
checks were true, `missing_goal_observations` was empty, and
`observation_goal_pass` was true. All 402 artifact sizes and SHA-256 digests
matched after download. It still supplied no root filesystem or userland,
and did not execute on the physical tablet.

## Connected tablet and existing Windows (2026-10-22)

The owner confirms that this tablet also runs Windows 11 ARM. Its current
authorized ADB session reports Android 15, nabu, slot `_a`,
`ro.boot.flash.locked=0`, and `ro.boot.verifiedbootstate=orange`.
Android MemTotal is 11766512 KiB (12048908288 bytes), separate from
12582908 KiB of swap. It is consistent with the reported RAM upgrade but
does not establish the entire DRAM layout or a UEFI allocation window.

Read-only names identify `mindowsesp`/`mindowswin`/`mindowsdat` as
`sda32`/`sda33`/`sda34`. These existing OS partitions, along with Android
and both boot slots, must be preserved. Partition names do not establish
filesystem health, free space or which boot image contains the installed UEFI.
Android shell denied device-tree, DRM-mode and partition-size reads; the
collector records those failures and does not escalate privileges.

The probe-only kit is staged on the PC from verified run 39779752907.
It contains no kernel, fallback bootloader, startup script or installer.
The Windows collector refuses an x64 host and queries only selected metadata
on the ARM64 tablet. Neither tool deploys to the tablet. See
[existing-windows.md](existing-windows.md) for the existing-UEFI validation
path and its unresolved firmware/menu evidence.

## Real GPT backup and 64 GiB proposal (2026-10-22)

The owner's subsequent authorization reserves 64 GiB from Android storage,
while retaining Android and Windows. Fixed fastboot queries first measured
userdata as 230,157,955,072 bytes; a remote unsupported getvar returned process
status zero, so the analyzer also checks its FAILED text.

A later temporary RAM boot used the local nabu recovery kernel with the recovery
application, decrypt startup, boot-control startup and disk fstab disabled.
Root ADB and the absence of all disk filesystem mounts were verified.
All six UFS LUNs' primary/backup GPT headers and entry arrays passed CRC and
consistency checks. Twelve boot/ESP/metadata images also passed device/local
SHA-256 comparison. This is physical recovery execution, not an XNU tablet boot.
No partition edit, flash, erase or slot change occurred. Normal Android 15
startup on slot `_a` and a read-write encrypted F2FS `/data` were reverified.

The verified GPT places userdata at LBAs 68,190,272 through 124,381,178
(4096-byte blocks). The old configured first LBA, 2,654,272, now identifies
the existing Windows ESP. Raw userdata image generation is therefore blocked
when `userdata.preserve_existing=true`, before tools, IPSW or output creation.

The initial offline planner computed an aligned 512 MiB project EFI area and
63.5 GiB system area inside the userdata tail. At that proposal stage neither
partition existed.
The encrypted filesystem has no validated offline decrypted mapping or complete
restorable backup. Its existing recovery tool advertises safe resize, but
that does not verify compatibility or permit changing GPT boundaries first.
See [project-space-64g.md](project-space-64g.md) for exact observations,
candidate boundaries and remaining prerequisites.

The owner subsequently authorized erasing Android userdata to avoid preserving
and shrinking the encrypted filesystem. That removes the complete userdata
backup and offline shrink prerequisites for this recreation route, not protection
of Windows, Android system/vendor, boot slots or firmware. Actual file inventory
is 16.48 MiB for kernel/loader/ADT/probe, or 308.91 MiB including optional UEFI
and two boot archives plus two additional kernel-size budgets. A 512 MiB EFI
area fits current materials but has no verified future ramdisk allowance.
The revised proposal reserved 4 GiB for project EFI and 60 GiB for system images,
still 64 GiB total. The installed Android fstab confirms F2FS with metadata
encryption; formatting userdata as ext4 would not match that configuration.

## Authorized 4+60 GiB partition operation completed (2026-10-22)

Following the owner's explicit confirmation, the temporary root recovery was
RAM-booted again. All 24 original backup checksums, live GPT edges, boot hashes
and absence of disk mounts were checked before applying the limited change.
GPT entry 31 retains its original identity and start, with a shorter end;
new entries 35 and 36 provide the project space:

| Partition | First LBA | Last LBA, inclusive | Bytes |
| --- | ---: | ---: | ---: |
| userdata | 68,190,272 | 107,603,711 | 161,437,450,240 |
| nabu_esp | 107,603,712 | 108,652,287 | 4,294,967,296 |
| nabu_system | 108,652,288 | 124,380,927 | 64,424,509,440 |

The old sgdisk initially aligned userdata's start forward by 192 sectors.
The immediate readback rejected that change before any erasure; the original
start was restored and the exact comparison passed. The executor now disables
automatic alignment for explicit LBAs and rejects automatic-move notices.
Seven synthetic offline tests cover this case and protected GPT identities.

After a fresh temporary boot verified the kernel's new partition boundaries,
the authorized userdata and project areas were discarded. Android's metadata
was also reset for its new encryption keys and recreated as ext4; five-pass
read-only e2fsck passed. Userdata is left wiped for installed Android fs_mgr /
vold to create its encrypted F2FS, rather than creating an incompatible ext4
or plaintext filesystem. Project ESP is FAT32 with 4096-byte sectors and passed
a read-only mount test. The 60 GiB system partition is unformatted.

Both GPT copies pass CRC and array consistency; every protected GPT entry is
byte-identical to the baseline. Eleven unchanged boot/ESP partition hashes
match their original backups. The other five LUN edge pairs and the Windows
system/data volume edge samples match. This does not constitute whole-volume
verification or a Windows boot test. No boot/firmware image was flashed, and
the active slot remains `_a`.

Android 15 then booted successfully on slot `_a`, with `sys.boot_completed=1`,
`device_provisioned=1`, and `user_setup_complete=1`. After the owner restored ADB,
normal shell reads confirmed encrypted, read-write F2FS on `/dev/block/dm-45`,
metadata encryption enabled, and a 157,651,712 KiB data filesystem. MemTotal
remains 11,766,512 KiB; this is not a UEFI memory map. The original Mindows helper
APK was reinstalled and its original UEFI file restored to shared storage with
SHA-256 verification, without invoking a boot-flashing function.

Windows startup has not yet been retested. The original backups and private
execution log remain on the PC, outside Git. There is still no physical XNU boot
or iPadOS installation. Local checks pass: seven synthetic GPT change tests,
six planner tests, four fastboot parser tests, and two preservation tests with
the tracked userdata protection patch applied to a separate validation copy.

## Project-volume-only device testing (2026-10-22)

The owner then restricted all future project persistent writes to the new
4 GiB / 60 GiB partitions. The userdata erasure authorization was specific to
the completed partition operation and is not an ongoing test permission.

A fresh RAM-only recovery session revalidated GPTs and kernel boundaries.
Every other partition was marked kernel read-only; only nabu_esp was mounted
writable. A 16 MiB random file passed SHA-256 checks after writing and after
unmounting and reopening the filesystem read-only, then was deleted.
The pinned 14,336-byte ARM64 NabuProbe.efi from run 39779752907 was staged at
`\EFI\NabuDiag\NabuProbe.efi`, with provenance and recovery observations.

All eleven protected boot/ESP hashes, all six LUN edge pairs and the Windows
volume edge samples were unchanged across deployment. The 60 GiB partition
remains unformatted and read-only during the test. The deployment helper
refuses non-project filenames and refuses overwriting existing files.

Recovery MemTotal is 11,733,112 KiB, distinct from normal Android's
11,766,512 KiB. Linux System RAM regions were collected; fb0 geometry was
unavailable. These observations do not supply a UEFI memory map or GOP.
Neither the EFI probe nor XNU was executed. The existing UEFI's automatic boot
and variable-storage behavior still needs verification before invoking it
under the new write restriction. See [device-test-scope.md](device-test-scope.md).
