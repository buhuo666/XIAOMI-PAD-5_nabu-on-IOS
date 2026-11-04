# Nabu append-only runtime log format v1

Implemented with host checks, 2026-11-04. Native compilation and device write/readback qualification are pending.

The existing `nabu_system` partition is 64424509440 bytes with 4096-byte logical
blocks. Its reserved log area begins at partition-relative byte 63350767616 and
is 1073741824 bytes long. It is divided into sixteen 67108864-byte slots. Never
reuse a nonzero slot. OS, SystemOS, Data and GPT remain outside the write window.
Boot argument `nabu-log-slot=N` explicitly selects one prepared slot (0..15).

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
| 8 | 4 | version 1 |
| 12 | 4 | slot index |
| 16 | 8 | slot bytes 67108864 |
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

Capture producers perform no I/O. A 56 MiB append-only RAM buffer retains the stream
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

The disk pump uses THREAD_CALL_PRIORITY_KERNEL and batches at most sixteen
records per callback, so it does not share the normally serial high-priority
group with sampling and return timers. Normal return first stops the pump, seals
capture under its producer lock, drains it, and commits END before SMP shutdown.

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
