# CPU-only capture capability migration

On the tested J317AP image, mediaserverd's optional Portrait prewarm requests
`lkt_bgra2yuva` from empty Metal libraries and aborts at the null compute-function
assertion. CMCapture already gates that prewarm on BackgroundBlurSupported or
StudioLightingSupported. Disabling the former, with the latter absent, takes the
existing unsupported-feature path. This does not implement CPU optical flow or
disable the separately gated cinematic prewarms.

Patch 0182 adds a fixed-file migration before initproc starts, after normal root
mount and journal replay. `nabucpucapture=1` applies it; `=2` restores it; omitted
or other values do nothing. It requires the exact model, verified NABU project
device, internal healthy HFS journal, 20 GiB case-sensitive HFS on the 60 GiB
project partition, fixed file ID/length/link count, four known aliases, and a
full SHA-256 preimage. All path components reject symlinks and mount crossings.
Compressed, immutable and append-only files are rejected before write-open.

The 10,581-byte plist changes only its value-reference byte at offset 128:
`0x29` to `0xb0`. The shared true object is preserved. Existing four hard links
remain linked, so their common inode receives the capability change. The
expected complete file hashes are:

- Before: `d865b46b429c01d508e1674f6e58d92f617331880799a755d068098fe2fcbed1`
- After: `56d5c531e99794942bcaeb3b5eeb65a52d540405f6b18c03413f7a30a7835129`

Normal vnode operations handle file data and HFS metadata; no raw filesystem
sector modification is used. Sync waits for file data and journal metadata and
checks the NABU driver's cache synchronization result explicitly. Readback must
match the full target hash. A failed write/sync/readback attempts exact reversal;
failure of that reversal stops initproc. An already matching target is idempotent.
Ordinary reads can update access time. Close errors are reported separately.
These checks do not promise power-loss atomicity.

`NABU CAPCFG1` reports mode, stage, result, errors, whether a write was attempted,
and whether the runtime model matched. Applying the configuration is distinct
from proving stable media service, a working VFB connection, or a visible desktop.
Actual device files, backups, identifiers and raw logs are not repository inputs.

The CI fixture extracts the implementation and injects filesystem/I/O failures
using synthetic data. Its API and SHA stubs cannot prove real journal or device
behavior; those require the downloaded-kernel experiment.
