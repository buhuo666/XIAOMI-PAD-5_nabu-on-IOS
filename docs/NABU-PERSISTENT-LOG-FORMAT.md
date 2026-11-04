# Nabu append-only runtime log formats v1 and v2

Version 1 was written and recovered on device in run 23 (2026-11-04), with a valid 56 MiB prefix and an explicit capture-capacity failure. Version 2 host checks pass; its native build, loader compatibility and device qualification are pending.

The existing `nabu_system` partition is 64424509440 bytes with 4096-byte logical
blocks. Its reserved log area begins at partition-relative byte 63350767616 and
is 1073741824 bytes long. Its sixteen 67108864-byte allocation units retain
exactly the v1 addressing. Never reuse a nonzero or reserved unit. OS,
SystemOS, Data and GPT remain outside the write window.

A v1 manifest owns one unit, selected by `nabu-log-slot=N` (0..15). A v2
manifest owns a contiguous extent of 2..16 units, selected explicitly by
`nabu-log-slot=N nabu-log-span=S`, with `N + S <= 16`. Its immutable
`slot_bytes` field is exactly `S * 67108864`; no new metadata fields or
record encoding are introduced. The version/span pairing is strict: v1 only
accepts one unit and v2 only accepts more than one. Preparation and recovery
continue to accept original v1 receipts and snapshots.

The next candidate reserves units 2 through 11: 640 MiB beginning at the
unchanged unit-2 offset. Units 0 and 1 retain their old contents, and units
12 through 15 remain available. Preparation must scan the complete selected
640 MiB, including every interior unit and the last byte, before writing only
the first 4096-byte manifest. The allocator also recognizes an existing v2
reservation whose later units are still zero; those units cannot be selected
by another run. Unknown/corrupt Nabu manifests cause preparation to fail
closed. Use the upgraded preparation tool after v2 is introduced, since an
old v1 allocator does not understand multi-unit reservations.

All integers below are unsigned little-endian. Each metadata block is exactly
4096 bytes, with unused bytes zero and an IEEE CRC32 at byte 4092 covering bytes
0..4091. Reject unknown versions, fields, flags, invalid CRCs and inconsistent
geometry. UUID fields hold sixteen opaque bytes. This is an integrity format,
not an authentication mechanism.

Slot block zero is an immutable manifest, created and read back by the Android
host preparation tool only after verifying the entire slot is zero:

| Offset | Bytes | Value |
|---|---:|---|
| 0 | 8 | ASCII `NABULG01` |
| 8 | 4 | manifest version 1 or 2 |
| 12 | 4 | slot index |
| 16 | 8 | extent bytes: v1 67108864; v2 span × 67108864 |
| 24 | 8 | partition bytes 64424509440 |
| 32 | 8 | reserved offset 63350767616 |
| 40 | 8 | reserved bytes 1073741824 |
| 48 | 4 | block bytes 4096 |
| 52 | 4 | maximum DATA payload 65536 |
| 56 | 16 | run UUID |
| 72 | 8 | preparation Unix timestamp seconds |
| 80 | 32 | selected kernel SHA-256 (provenance, not evaluated by kernel) |
| 112 | 3980 | zero |
| 4092 | 4 | CRC32 |

Records begin at slot block one and occupy a header block plus rounded-up
payload blocks. They are contiguous and strictly sequential. A BEGIN record
(kind 1, sequence 0, stream offset 0, no payload) claims the slot. An existing
nonzero first record makes the slot ineligible for a later boot. Every write
must remain in this one validated slot; the immutable manifest is never written
by XNU. The writer must check target bytes are zero before writing each record.

| Offset | Bytes | Record header |
|---|---:|---|
| 0 | 8 | ASCII `NBLOGR01` |
| 8 | 4 | version 1 |
| 12 | 4 | kind: BEGIN=1, DATA=2, END=3 |
| 16 | 8 | sequence, incrementing from 0 |
| 24 | 8 | logical stream offset before this record |
| 32 | 4 | exact payload bytes (DATA: 1..65536; others: 0) |
| 36 | 4 | record blocks = 1 + ceil(payload bytes / 4096) |
| 40 | 16 | manifest run UUID |
| 56 | 32 | DATA payload SHA-256; BEGIN SHA-256(empty); END SHA-256(entire committed stream) |
| 88 | 8 | lost capture bytes, zero until END |
| 96 | 4 | status, zero for success; nonzero END is incomplete |
| 100 | 4 | flags, END: bit0 capture sealed; bit1 capture loss; all other bits zero |
| 104 | 3988 | zero |
| 4092 | 4 | CRC32 |

For DATA, write zero-padded payload first and SYNCHRONIZE CACHE, then commit the
header and SYNCHRONIZE CACHE. BEGIN and END similarly require committed header
sync. A reader accepts only the valid, contiguous prefix whose payload hashes,
sequence, stream offset, UUID, padding, block counts and bounds all match. An
invalid/torn header or payload ends recovery with an explicit incomplete state.
Reserve space for one END block before accepting any DATA record. Never wrap.

Capture producers perform no I/O. A 512 MiB append-only RAM buffer retains the stream
from early boot; a normal kernel callback batches disk writes. Normal timed
return seals capture and drains it before SMP/UFS quiesce. END states this seal
boundary explicitly; later return-stub messages are outside the saved stream.
Abnormal termination can leave a valid partial prefix without END. Reaching a
capacity limit must be reported as incomplete, never silently overwrite bytes.

The captured stream includes kprintf, explicit loader lines, user console
output, and live characters sent to the kernel message buffer (including its
lock-failure path). Existing messages mirrored by their producer are retained;
this is not a claim to capture every private unified-logging record. Screen
summary storage remains separate and can retain only its first/latest excerpts.
The persistent stream is unaffected by that screen-summary ring.

The disk pump uses THREAD_CALL_PRIORITY_KERNEL, at most 128 records (8 MiB)
per callback, then a 250 ms interval. It releases the root-read lock after each
record, so readers can contend between records; it never holds that lock for
the entire 8 MiB batch. Capture producers still perform only memory operations.
The sampler and return timer use their existing independent priority group.
Normal return marks the pump stopped, seals capture under its producer lock,
drains it, and commits END before SMP shutdown. A late queued pump does no
post-END I/O.

Run 23 attempted 407899412 captured bytes (389.003 MiB): 58720256 saved and
349179156 lost after the 56 MiB limit. The 512 MiB capture has about 31.6%
headroom over that measured stream, not a guarantee for an arbitrary future
run. Full 512 MiB data uses about 544 MiB on disk at 64 KiB records, plus partial
record padding, within the 640 MiB extent. Every real capacity/error condition
still produces an incomplete result; no records are filtered, compressed or
overwritten. The RAM change adds 456 MiB of wired/BSS storage and requires
qualification of the linked Mach-O layout and loader bounds. In particular,
the older loader's 256 MiB ParseKernel limit must be updated and tested before
this kernel can be deployed; a large ADT allocation window alone is insufficient.

Use `tools/nabu_runtime_logs.py --prepare` for a new slot and pass its
`preparation.json` to `stage_nabu_boot_chain.py --log-preparation`. Deployment
and temporary boot each recheck that the whole slot still consists only of the
expected immutable manifest and zero bytes. Boot collection automatically saves
the raw slot and verifies/exports `runtime.log`; only `report.json` with
`complete=true` establishes successful complete recovery through the seal.

Native integration must validate the existing GPT and installed layout before
opening the log window. Any write rechecks ready/poisoned/queue/fatal state while
holding the transport lock, before changing DMA memory. No disk I/O is allowed
while holding the log producer lock or from interrupt/panic contexts.


macOS Actions `41839045982` (source `8c64be0d7ad2b8277c66cb08973047ba670f35bf`)
passed the complete kernel build, capture/writer/runtime/format checks, existing
storage and return checks, export contract, and native LLDB/capacity checks.
The stripped kernel SHA-256 is
`7df502f2a4ef936fe6b990d74cbf49227585710f19ddfa232d1fd025b9b32c74`.
Fourteen linked storage/return instruction ranges match the exact boot kernel.
Host verification receipts are in `log/host/nabu-log-candidate/`.

Android preparation preserved nonzero slot 0 and verified all of slot 1 was zero.
It wrote only slot 1's 4096-byte immutable manifest, read it back, verified the
remaining slot bytes stayed zero, and rechecked 30 GPT records. The receipt is
`log/device/nabu-log-slot-20261104-23b/preparation.json`. An earlier staging
attempt failed before any partition write because adbd could not write a
root-owned directory; staging now uses the adbd identity. This preparation
establishes neither XNU disk writes nor successful runtime log capture.


## Version 2 host verification, 2026-11-04

- Actual capture producer functions pass ASan/UBSan at the full 512 MiB boundary,
  including loss accounting, immutable publication and atomic seal behavior.
- Actual writer/UFS command code commits a continuous 512 MiB stream into a
  640 MiB simulated extent starting at unit 2. It checks far-tail freshness,
  exact slot/span binding, immutable manifest, both extent edges, zero padding,
  every payload hash and the final stream hash. An independent Python reader
  verifies all 8194 records and SHA-256
  `7fb0c8e3728891a5bacd5178fda77d45c0d31e947430ece26b3d6867d23a90da`.
- The actual runtime/parser passes ASan/UBSan with 128-record batches,
  per-record lock release, explicit span checks, failures and finish races.
- Twenty-four Python tests cover old/new format recovery, reservation ownership,
  an occupied final byte, CRC/UUID/size failures and full-extent deployment
  preflight. The old C++ v1 fixture is read independently as well.
- The new reader reopens run 23's original `slot-01.bin` with its unchanged
  receipt and reproduces its 58720256-byte stream hash and incomplete END.

Receipts are in `log/host/nabu-log-v2-*`. These are host/simulated-medium checks;
they do not establish v2 XNU execution, real UFS throughput or device completion.

Native Actions `41847611792` passes the v2 kernel build, all logging checks,
linked storage/return/capacity analysis and export contracts. The exact kernel
contains the 512 MiB buffer and passes the updated loader parser/layout guard.
See `DEVICE-CLASS-COMPATIBILITY.md` for hashes and memory-fit evidence.
Device v2 write/readback qualification remains pending.
