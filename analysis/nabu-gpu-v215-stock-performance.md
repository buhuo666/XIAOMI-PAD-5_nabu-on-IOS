# GPU215 stock performance

GPU214 confirmed real completion interrupts but did not improve the user's
desktop swipes or Settings scrolling. Complex DPU windows still spend
11-17ms waiting for GPU producer readiness. The port previously pinned the
GPU to the lowest stock257MHz level while Android uses higher stock OPPs.

GPU215 changes the default to this unit's highest stock675MHz level, with
raw ARC320 and DDR8363000KB/s from the selected Android FDT. Command-db still
derives the real GX/MX indexes and BCM votes. The retained shared CX384/MX
floor, GMU200MHz, CNOC100KB/s, off entries and firmware acknowledgements stay
in their existing order. The compressed HFI tables continue to select GPU
index1 and bandwidth index1; the original Android bandwidth usecase11 is
not an HFI index in this two-entry table.

The tracked Power header and GMU source overlays join the existing Power
and Service overlays. The Power class and HFI payload layouts are unchanged.
Only Power, GMU and Service objects replace their GPU214 inputs; the other
61 objects retain real completion IRQs, shared-page scanout and Hall.
The kernel core reuses the fully qualified GPU214 CI43011757018 output.
Changed GPU modules compile as ARM64, then undergo actual Power/GMU host
regression,64-object linking, branch decoding and loader-window checks.

The staged boot explicitly selects `nabu-gpu-khz=675000` and keeps120Hz,
live identity and the GPU212 bootstrap. HFI acceptance confirms the selected
request; the numeric frequency is not independently measured clock telemetry.
Actual frame-output improvement requires the ensuing device result.
