# GPU187 black screen / GPU188 VM page-number fix

GPU187 booted and the native USB/GPU readiness check passed. Live IORegistry
reported 1600×2560 at 120 Hz, selected direct scanout, and producer registration
status zero. The user reported a black screen. The complete 64 MiB log slot and
4,767,693 bytes of runtime log were recovered and cleared with readback; Android
boot partitions were unchanged. APFS advanced from 165 to 166.

The first frame was rejected before any display-context handover or scanout
address change:

```
NabuGPU: cpu_geometry vm_page=16384 kernel_map_page=16384 ... status=00000000
NABU DPU MAP table-cache page=0 pa=0x1d08f8000 attr=0x7 need=0x6
NABU DPU: swap=1 surface=2 failed=0xe00002c7 scan-phase=1
```

`pmap_cache_attributes` accepts a VM page number. Its `ptoa(pn)` uses the native
VM page size, which is 16 KiB in this boot. The mapper incorrectly divided the
physical address by the 4 KiB SMMU table granule. Pmap reconstructed a different
address outside managed RAM and returned its default I/O attribute, 7. This
does not establish that the allocated table itself had I/O caching.

GPU188 uses `atop(pagePhysical)` for this pmap API, matching the qualified
NativeAdreno CPU cache query. SMMU table indexing and mapping stay at 4 KiB.
The noncacheable table requirement, publication barriers, original IOSurface
pixel pages and retirement rules remain in place.

The actual mapper fixture now models pmap's VM page-number conversion with both
4 KiB and 16 KiB VM pages. Wrong 4 KiB page numbers in the latter case reproduce
attribute 7; the production mapper must query the correct pages throughout all
2053 table pages. Existing mapping, route ownership, fault/retirement and ARM64
checks pass. Accepted-frame diagnostics now include observed IRQ/vblank counts
for the next device qualification, and the static refresh log names the selected
hardware path accurately.

GPU188 still requires its rebuilt kernel and a real device test. GPU187 did not
qualify direct scanout, absence of tearing, or 120 distinct frames per second.
