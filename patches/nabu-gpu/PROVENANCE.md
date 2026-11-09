# Nabu 20F66 A640 hardware port

The build stages the pinned `nabu` source from `configs/sources.lock.json`,
currently commit `54b4f98457f8e9e232cc0a077c20d08d0b2f0ac9`, in this order:

1. `gpu/upstream/Adreno6xx`
2. `gpu/upstream/ArmSmmu4K`
3. `gpu/upstream/AdrenoPM4`
4. `gpu/a640`
5. `gpu/nabu`
6. This directory

The original sources and their license/provenance files stay in the pinned
checkout. The upstream Adreno6xx source is recorded there as
`RigoLigoRLC/unixnu-adreno6xx` commit
`83a0453e981567a30cecd6486bdb8b3b33d64683`. Files retain their SPDX declarations;
`NativeAdrenoA6xxPower.cpp` is GPL-2.0-only and preserves its Qualcomm copyright.
The service, CPU adapter, resource glue and new port/compatibility headers are
MIT; the namespace header is BSD-2-Clause-Patent.
`LICENSE-MIT` and `COPYING-GPL-2.0` reproduce the corresponding upstream texts.

These overlays change the integration points needed by the existing XNU 8796
and 20F66 system:

- `NativeAdrenoService.cpp` exports `nabu_gpu_start()` for the existing kmod
  startup owner, preserves the `nabu-gpu=1` gate and logs CPU page geometry.
  Without Metal publication it verifies the CP memory write and fence,
  observes hardware for one second, then stops CP and resets GMU. Mappings,
  page tables and host votes remain owned for the boot; this is not a claim
  of full runtime power management. The existing publication branch remains
  separate and is not enabled by the diagnostic build.
  State transitions publish `nabu-gpu-state` and a 24-word software snapshot
  `nabu-gpu-stats` under `/chosen` for the existing read-only service probe.
- `NativeAdrenoCpu.cpp` distinguishes 16 KiB VM allocation units from the
  4 KiB kernel and SMMU translation granules. Physical-page cache queries use
  XNU's `atop()` contract rather than an assumed shift.
- `NativeAdrenoA6xxPower.cpp` uses the current AOP mailbox and RPMh mutexes
  for complete transactions, sharing those transports with WLAN and ADSP.
  A TCS must be available and have no enabled commands before selection.
  Host CX/MX votes preserve the current modem/audio baseline's retained CX
  raw-level 384 floor and its command-db MX dependency. Separate TCS slots
  share the same APPS DRV2 voter. GPU/GMU HFI performance tables stay unchanged.
- `NabuGpuResources.cpp` keeps the A640 board/firmware input contract and
  replaces the reference ESP logger dependency with the current append-only
  runtime capture. Firmware inputs are reviewed when acquired by the host;
  the runtime checks their required presence and extent without another hash
  audit.
- `NabuGpuSmmuNamespace.h` renames the GPU SMMU function/global definitions
  so they cannot collide or bind to the WLAN driver's independent copy.
  It must be force-included in every GPU C and C++ compilation unit.
- `NabuGpuKernelCompat.h` maps the private data-array allocation macros to
  the matching public `IONew`/`IODelete` pair exported for 8796 kexts, retaining
  the original pointer-clear behavior at deletion. It is force-included in
  GPU C++ units only and leaves available native definitions in place.

No vendor firmware, Apple binaries or generated GPU object files belong here.
Hardware execution, rendering and 20F66 client compatibility require separate
device evidence; compiling these sources is not GPU validation.
