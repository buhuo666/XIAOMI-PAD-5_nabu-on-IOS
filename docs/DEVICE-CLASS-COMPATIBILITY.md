# Device-class compatibility for the 20F66 iPad userland

Date: 2026-11-04, Asia/Shanghai. Candidate not yet device-qualified.

## Run 23 evidence

The original photo is preserved in `log/device/nabu-boot-20261104-23/screen-halted-600s.jpg`.
It shows a normal timed return (reason/code 0, TIMER MARKER YES), 32,711 reads
and zero read failures. Android collection verified all 30 GPT records and
14 boot partitions unchanged. A transient USB disconnect interrupted the
first read-only collection attempt; the subsequent collection succeeded.

The raw 64 MiB slot and decoded stream are preserved in that run's
`runtime-log/` directory. All 935 accepted records, individual DATA hashes and
the END stream hash validate. The stream SHA-256 is
`bc37c6499d26ad498ade602042012d4522a82f23c5c0ac5eefb4d9eeb9ed9753`.
However, `complete=false`: END records 58,720,256 captured bytes, 349,179,156
lost bytes, sealed capture, and status 28 (ENOSPC). This establishes real XNU
write/readback of the valid prefix, not complete logging.

The prefix ends around the device clock's 193-second mark, before the first
240-second stack sample. No stack-sample header was recovered. There are
220,349 lines (51,257,056 bytes) containing either the missing
`com.apple.sleepd.sleepserver` endpoint or its HKSP connection invalidation.
That is about 87% of the recovered bytes. The approximate 389 MiB total
capture demand explains why both the old screen ring and the 56 MiB
append-only capture failed to retain late diagnostics.

## Stock artifacts and source

The local 20F66 OS image inventory contains neither the sleepd executable nor
`com.apple.sleepd.plist`. All extracted LaunchDaemons and LaunchAngels plists
were parsed: none advertises `com.apple.sleepd.sleepserver`. This is bounded
to the supplied OS image and those launch directories; it is not a universal
claim about every iPadOS release. Adding a fabricated daemon definition is not
supported by these artifacts.

The frozen ADT's root `model` is `Xiaomi Pad 5`. In the pinned XNU source,
`sysctl_hw_generic(HW_PRODUCT)` calls `PEGetProductName`; ARM
`IODTPlatformExpert::getProductName` calls `getMachineName`, which reads
the root model property. GenericARMPE uses that inherited model with the
current default boot arguments. The actual log reports device class 2 in
backboardd's PUIProgressWindow.

The original cache has this independently decoded path:

- `0x19c4a69c4` obtains `hw.product` through the helper at
  `0x19c4a68a0`, which calls sysctlbyname.
- `0x19c4a4808..0x19c4a4a30` compares model prefixes. Unknown input and
  `iPod` select class 2; `iPad` selects class 3; `iPhone` selects class 1.
  A diagnostic string explicitly says the class was not recognized.
- `-[_HKBehavior currentDeviceClass]` at `0x19b53f6a8` queries
  MobileGestalt's `DeviceClass`.
- Sleep's `hksp_device` at `0x1a3a94df4` distinguishes the original
  CFStrings `iPad`, `iPod`, `iPhone`, and `Mac`.
- `_hksp_supportsSleep_checkTinker:` at `0x1a3a9458c` returns true for
  iPod but queries `sleepOnIpad` for iPad. The feature getter calls
  `_os_feature_enabled_impl("Health", "sleepOnIpad")`. The supplied stock
  Health feature plist has no such entry; the live feature result is still
  unmeasured, so its value is not asserted from this absence.

Eight exact functions were decoded separately with LLVM18 and checked
instruction by instruction against the original cache. Five model cases and
five Sleep support cases execute those original instructions under Unicorn,
with explicit string/sysctl-result/ObjC/log boundary stubs. Both iPad feature
values are tested. Cache file and local-symbol hashes were reverified.

Evidence and reproducible analysis are in `log/host/display-v24/`, especially
`device-class-proof.json`, `run23-analysis.json`, and
`verify-device-class-v24.py`. REA's plist/native Apple utilities are unavailable
on Windows; local plistlib, the existing bounded cache parser, LLVM, and
Unicorn supplied this evidence. No REA decompilation result is claimed.

## Candidate and limits

`make_nabu_adt.py` and staging accept an explicit
`--userland-model iPad7,11`. The default recreates old inputs exactly. The
candidate changes only root `model` to match the supplied iPad7,11 userland:
`compatible=xiaomi,nabu`, the hardware product name, CPU/GIC routing, Wi-Fi
address, and random seed remain byte-identical. The setting is an OS
compatibility model, not a claim that the physical device is an Apple iPad.

The new ADT is compared recursively with the frozen run-23 tree. Invalid
models are rejected, and an existing candidate cannot be silently reused
without its explicit model argument.

This explains a concrete device-class mismatch and predicts a different Sleep
support branch. It does not yet prove the retry storm causes the absent
desktop, or that the model adjustment alone will make SpringBoard display.
The next run must check class selection, retry volume, all three late stack
samples, surface/frame activity, and complete log recovery.

The log-capacity correction is separately necessary: successful compatibility
must not be relied on to keep diagnostics within the old 56 MiB limit.


The diagnostic candidate also expands the immutable RAM capture to 512 MiB
and uses an explicitly prepared 640 MiB v2 extent (allocation units 2 through
11). The existing units 0 and 1 remain reserved for their earlier logs. The
loader's early Mach-O parser previously rejected any segment/span above
256 MiB even when the ADT requested more memory. The candidate uses the
existing 12 GiB supported parser maximum; the final payload layout still has
to fit the actual conventional-memory allocation, with the 2 MiB tail reserve.

`check_darwinboot_kernel_window.py` extracts and executes the actual parser
and final layout guard with ASan/UBSan. Eleven cases cover a 512 MiB BSS,
small kernels, overlap, address overflow, excessive span/segment, invalid
entry, file bounds and truncation, plus actual-window boundary acceptance and
rejection. WSL LLVM18 built the candidate DarwinBoot successfully, SHA-256
`ab39085cc03833478cf7496fb205e82df767091947bfd8c93caf8356f0dd6c0b`.
The 7888-byte report callback is identical in the old and new EFI; the frozen
run-23 UniXNU launcher is reused. Actual linked kernel layout qualification
and the device run are pending.


Native Actions `41847611792` for source `653d1eb9bb34ee9cac26bb3be83f4a32e69bec23`
completed successfully. Both kernel hashes, project/capture/writer/runtime source
hashes, eight check suites and 18 linked instruction ranges match
the selected stripped kernel. Its SHA-256 is
`122517a210e398b6ac3b905ae122d361d8a9a0a4970c195c0b05d98d9aa235cf`.
The linked VM span is 558383104 bytes (532.515625 MiB); `_nabu_capture`
has exactly 536870928 bytes before the next symbol, including 512 MiB payload
and state. The actual loader parser accepts this exact kernel; its payload
layout uses 566820864 bytes and retains the final actual-allocation check.
Host checks do not establish successful device allocation or execution.

EFI Actions `41847611821` also passed. Its source receipt matches the local
EFI build; their binaries differ and are not represented as byte-identical.
The selected local EFI's 1723 Boot instructions are independently checked
against its PE bytes, including all enlarged limits and the final window guard.
Receipts are under `log/host/display-v24/kernel/` and `efi/`.
