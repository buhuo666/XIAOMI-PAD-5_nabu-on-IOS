# GPU212 baseline and GPU213 surface index

## GPU212 device evidence, 2026-11-11

The `06a3452` kernel passed full CI 42996174222 and the 64-object link and
loader checks. The GPU212 bootstrap contains helper CI 42995837743. The user
confirmed normal desktop/touch, then persistent lag after desktop swipes and
Settings scrolling.

Both administrator `GpuPerformance` requests returned status 0 and matching
IDs. The persistent log contains their paired begin/end markers and scheduler
snapshots; these records were absent from the online syslog stream.

- Before: `ab12728499f749e0ad0e314de95e2436`, at 114.107207 s.
- After: `0261cff349414e10bf71d327d0b6c822`, at 237.429695 s.
- The interval includes idle time; user gesture boundaries were not instrumented.

| Measurement between snapshots | Result |
| --- | ---: |
| New completed scheduler jobs | 134 |
| Queue 1 accepted to issued, 129 jobs | mean 0.100 ms, p95 0.159 ms |
| Queue 1 issued to observed completion | mean 18.058 ms, p95 26.649 ms |
| Jobs with DPU reader dependencies | 0 |
| GPU BO map calls | 449 |
| BO map total CPU time | 639,665 us, mean 1.425 ms |
| VM index phase delta | 543,697 us, mean 1.211 ms per map |
| VM table phase delta | 22,404 us |
| BO allocations | 107 calls, total 18,314 us |
| BO frees | 201 calls, total 67,457 us |

The VM index phase includes physical-tree insertion, linking cached aliases,
and the scheduler mapping-added observer. It is not all attributable to one
function until the changed implementation is measured. Scheduler issue-to-
completion includes hardware, IRQ and worker scheduling; it is not pure GPU
execution. The DPU report spans 240 frames and idle gaps up to 59.95 seconds,
so its submission interval cannot establish animation FPS.

4,269,824 contiguous log bytes and the full 67,108,864-byte slot were retained.
The stream was not sealed. Clearing/readback passed, Android boot partitions
were unchanged, and Data boot count advanced 189 to 190.

Evidence: `log/host/gpu-v212/gpu-stats-{before,after}.json`,
`log/host/gpu-v212/timing-persistent.json`, and
`log/device/nabu-boot-20261111-212/runtime-log/`.

## GPU213 change

`NativeAdrenoScheduler::mappingAdded` previously searched the VM physical alias
tree for every segment of every retained display backing, even for a newly
mapped BO with no shared physical bytes. This runs under the GPU service lock
inside the VM map index phase.

Each prepared display backing now retains a sorted physical interval index,
built once with the existing `NativeAdrenoPhysicalIndex` helper. Mapping-added
first tests the new BO's physical spans against this index. A nonoverlapping
backing requires no global alias-tree queries. A possible overlap follows the
original exact byte-range lookup and reservation creation unchanged.

The index contains CPU metadata only. It is released with the backing's pin,
does not retain extra surfaces, does not modify GPU/DPU page tables, and does
not bypass producer fences or retirement. Existing descriptor queries retain
`kIOMemoryMapperNone`. Stats snapshots add cumulative map/backing/skip/span-test/
alias-query counters under the existing GPU lock.

## Local validation

The actual scheduler and producer adapter passed ASan/UBSan host regression:
13 suites cover pending/submitted writers, physical aliases, late mappings,
multiple readers, close/fault/release, and the new interval index. New cases
exercise unsorted/nested/duplicate intervals, exact boundary nonoverlap,
mapping offsets, and descriptor reuse after the old pin is released.

The unrelated-map workload has a 1024-segment retained surface and 256 new
nonoverlapping BO mappings. It avoids 262,144 full VM physical-alias queries;
adding an actual shared mapping still performs the original lookup and blocks
the writer until display releases its read lease. This is an operation-count
regression, not a predicted device speedup.

Producer-enabled `NativeAdrenoPublish` and `NativeAdrenoScheduler` both compiled
for arm64-apple-ios16.5. The existing full kernel CI already runs the scheduler
host suite and compiles all GPU objects. Candidate linking must replace both
GPU187 objects with the GPU213 objects while preserving the other 62 objects.

Full CI and GPU213 device comparison are pending. This optimization targets
demonstrated CPU map work; the longer issue-to-completion duration and the final
continuous-frame target remain unresolved.

## GPU213 device result

Commit `55e1f07`, full CI 43005319897, both revised objects in the 64-object link,
and the unchanged GPU212 bootstrap passed the device run. Desktop and touch
remained normal; the user still reported obvious lag during the same gestures.

Paired persistent snapshots:
`6be194dbc95e405eb9fff94b7bd3c8b8` and `770ddac8ca584ab18712674488d74191`.

| Per-map measurement | GPU212 | GPU213 |
| --- | ---: | ---: |
| Samples | 449 | 123 |
| Mean BO map CPU time | 1.425 ms | 0.436 ms |
| Mean VM index phase | 1.211 ms | 0.062 ms |
| Mean VM table phase | 0.050 ms | 0.192 ms |
| Mean VM preflight | 0.144 ms | 0.136 ms |

GPU213 recorded 369 backing checks, all nonoverlapping, 8280 new-span tests,
and zero full alias-tree queries during this interval. Index time dropped
94.86% per map and total map time dropped 69.36% in these observed samples.
The scene mixes and allocation sizes differ; this is not a controlled FPS
benchmark or a claim of equivalent improvement to total frame time.

Queue 1 had 37 new jobs, mean accepted-to-issued 0.076 ms and
issued-to-observed-completion 19.417 ms, with no DPU-reader dependencies.
4,657,952 contiguous log bytes and the full 64MiB slot were recovered and
cleared/read back. Android boot partitions were unchanged; Data count 191.

The next investigation found the GPU completion source was still a software
callback invoked by the 10ms hardware worker, despite the DPU using real IRQs.
GPU214 connects that source to GIC332 before testing higher OPPs. Android
scheduling/OPP evidence is retained under `log/host/gpu-v213/`.
