# WLAN DMA ownership implementation (not enabled on device)

New files: `patches/nabu-wireless/NabuWlanDma.{h,cpp}` and
`tools/check_nabu_wlan_dma.py`. This work does not change USB, storage, existing
SMMU contexts, bootstrap or build scripts. No native entry point is called by the
current wireless startup.

## Real allocation and translation

`nabu_wlan_dma_prepare()` uses the existing XNU IOMallocContiguous API to allocate
128 independent 64KiB WB chunks, each aligned to 16KiB, plus a separate 64KiB
table pool. Failure frees only allocations not visible to a device. The arena
occupies IOVA 0xa0000000..0xa07fffff, inside the board's 256MiB WLAN IOVA window.
Each chunk has a real CPU pointer and physical address; returned buffer IOVAs are
calculated from these mappings. Buffers never cross a chunk and do not share CPU
cache lines. The allocator is per-session and does not reclaim individual slices
while DMA might own them.

ArmSmmu4KBuild creates actual native-4KiB page tables for all 2048 arena pages,
with no executable leaf or table-pool mapping. It uses 32-bit IOVAs / 36-bit output
addresses, six table pages, RW normal-WB inner-shareable leaf attributes. CPU
cache publication uses real dc civac + dsb; noncoherent table walks are selected.
The consumer must call nabu_wlan_dma_sync before handing buffers/descriptors to
the device and after device completion before CPU access. The owner and buffers
must be serialized by a single device worker; the global configuration lock is
not a substitute for producer/consumer ownership.

## Board stream ownership

The actual FDT iommus specifier is SID **0x640, mask 1**, not one exact SID.
NabuWlanDma therefore uses two exact routes, 0x640 and 0x641, into one private
context. Selection reads the native SMMU geometry, refuses existing overlapping
WLAN routes, uses two invalid slots, and chooses a reset/unused stage-1 bank and
an ASID absent from enabled contexts. It does not borrow USB/UFS contexts, change
global registers, enable bypass, or reuse WCN6750's stream 0x1c00.

`attach(registrar, unregister, cookie)` holds hakios_smmu_lock through selection
and activation. The registrar is mandatory: it must install real bank/global
fault handling and establish the SM8150 bank's required ACTLR/security setup.
On registrar failure it must undo its own changes. The native registrar described
below implements this requirement with actual GIC APIs and board ACTLR evidence;
there is no boolean pretending to provide the prerequisite. The
client also must keep WLAN stopped or mission mode OFF throughout attachment.

Only the two reserved S2CRs are faulted before ArmSmmu4KProgramDisabledContext
programs and verifies the private bank. ArmSmmu4KAttachStreams then publishes
both exact routes. `observe()` validates actual context/stream registers; a fault
withdraws readiness. PFR calls `lost()` and retains all memory and tables.
`release_after_stop()` is only valid after actual PAS shutdown or equivalent
confirmed hardware quiescence. It faults owned streams, disables the matching
context and synchronizes its TLB before restoring the original invalid slots,
removing handlers, resetting that previously-empty bank and freeing allocations.
Any failed ownership check or TLB completion retains resources.

## Reused component and build wiring

The unchanged ArmSmmu4K-nabu checkout is already pinned by
`configs/sources.lock.json` to
`RigoLigoRLC/unixnu-arm-smmu4k@599ba82f96f3e10b0afbd784c040127d38e2683a`.
Its working tree was clean. Sources are locally present but ignored by the
outer repository; CI must acquire that pinned component before compiling.

When enabling this code in a subsequent candidate, compile and link these six
objects in addition to the existing wireless objects:

- NabuWlanDma.cpp
- NabuWlanController.cpp
- ArmSmmu4K.c
- ArmSmmu4KContext.c
- ArmSmmu4KProgram.c
- ArmSmmu4KStreams.c

The header uses the existing relative component path, so no new include path is
required. Do not add them to the in-progress v116 trial merely to compile unused
code. The production caller must invoke the native attachment entry point and
retain the owner for the whole WLAN service lifetime before setting resources_ready for
NabuWlanConfig. A successful prepare alone does not establish DMA readiness.

## Verification

`python tools/check_nabu_wlan_dma.py --output log/host/wifi-recheck-v114/wlan-dma-test`
passed ASan/UBSan using unchanged component code and software allocation/register
peers. The test independently walks all 2048 leaves to the recorded allocator
physical addresses, exercises partial allocation failure, alignment/chunk/arena
boundaries, exact two-SID routing, masked-route rejection, USB/UFS preservation,
ASID collision, runtime fault withdrawal, activation/TLB timeout retention and
successful hardware-stop-gated release. Software peers are not hardware evidence.

NabuWlanDma and all four component objects also compiled with the existing arm64
kernel flags into isolated `*-arm64.o` files in that same directory. Build scripts
were not modified. Native runtime, IRQ handling, hardware coherency and actual
WLAN DMA remain unverified; there are no packet-delivery claims.

## Native fault/platform integration added after the initial slice

The previously mandatory-but-missing registrar is now implemented by
`NabuWlanController.{h,cpp}` and `NabuWlanFault.h`.
`nabu_wlan_dma_attach_native(owner)` passes real GIC register/mask/detach callbacks
to the DMA owner. It still has no boot-time caller and performs no live action
merely by being compiled.

The board's original FDT has 81 interrupt triples for apps-smmu: one global
SPI65 / GIC INTID97, followed by 80 context lines. They are discontinuous, so a
single context IRQ base would be wrong. Vendor arm-smmu.c assigns SMMUv2
`cfg.irptndx = cfg.cbndx` and requests `irqs[num_global_irqs + cfg.irptndx]`
(2295..2314). Thus bank55 uses SPI336 / INTID368. All FDT triples and ACTLR
entries are frozen in `tools/fixtures/nabu-wlan-smmu.json`, verified by the new
fault test; no WCN6750 MSI assumptions are used.

The native registrar calls the actual `gic_v3_spi_attach` with level-triggered
configuration. That function returns KERN_NAME_EXISTS before modifying an
already registered interrupt (gic_v3_irq.c 225..267). A conflicting global or
context owner is a concrete runtime ownership blocker: the code returns failure
instead of detaching it. Partial registration detaches only the line it acquired.
The existing detach operation masks and waits for any running callback to end.

ACTLR is also closed against board/vendor evidence. The original qcom,actlr
table has six ranges, none matching SID0x640/0x641 under the vendor mask-matching
rule. `qsmmuv500_device_group` / `qsmmuv500_init_cb` (5840..5900) retain zero
when `has_actlr` is false; the context records come from devm_kcalloc (4862).
The registrar checks that the newly leased bank's ACTLR is zero and adds no
0x103/0x303 override. `qcom,enable-static-cb` and secure-config-access properties
are absent from the original apps-smmu node. The vendor secure restore / TZ
context-format branches require static-CB (536..560, 1845..1858), and ICNSS's
domain setup (2647..2731) does not set a secure VMID. Therefore no security-mode,
SCM, global-reset or debug-bypass writes are justified or implemented here.

Interrupt capture is bounded and allocation-free. It reads owned context
FSR/FAR/FSYNR0/FSYNR1 and GR1.CBFRSYNRA, or global GFSR/GFSYNR0..2, atomically
publishes the first record, and masks only its acquired IRQ. It does not clear
the global fault (which may belong to USB/UFS), resume a DMA transaction, or
modify any context from interrupt context. The serialized WLAN worker calls
`nabu_wlan_dma_faults_native`; any pending fault calls owner.lost(), retaining
resources. The owner unregisters IRQs only during confirmed stop/disable cleanup.
Foreign global faults require a platform owner to resolve them; this WLAN code
does not invent attribution or erase them to force a retry.

Pinned original Xiaomi source was fetched once through the project proxy:
`MiCode/Xiaomi_Kernel_OpenSource@71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c`,
`drivers/iommu/arm-smmu.c` and `arm-smmu-regs.h`. Paths/provenance are under
`log/host/wifi-recheck-v114/smmu-source/`. IRQ/layout verification follows the
actual source fault handlers at 1665..1831. The native fault/controller object
compiled arm64. `check_nabu_wlan_fault.py` passed ASan/UBSan for the complete
FDT IRQ table, ACTLR matching, existing-owner rejection, partial unwind,
context/global snapshots, first-fault retention, and absence of SMMU writes.
Results are in `log/host/wifi-recheck-v114/wlan-fault-test`.

The later build additionally needs `NabuWlanController.cpp`. This completes the
concrete registrar dependency; actual free-bank/IRQ availability, hardware cache
coherency, and CE/HTC operation still require the production worker integration
and device evidence. Existing USB/UFS code, build scripts and boot flow remain
unchanged by this work.
