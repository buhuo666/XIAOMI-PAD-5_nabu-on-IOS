# GPU191 recovery and GPU192 display IRQ handover

2026-11-10, Asia/Shanghai.

GPU191 remained black according to the user. Its complete 64 MiB slot was
backed up, then cleared with readback. The recovered runtime prefix is 808,996
bytes; it is not a sealed complete runtime log. APFS boot count is 170 and the
Android boot partitions are unchanged. Evidence is under
`log/device/nabu-boot-20261110-191/runtime-log`.

The committed checkpoints establish:

- Surface mapping, producer wait, inactive page tables and source preflight
  completed successfully.
- VIG clock registers at MDSS +0x12ac and +0x12b4 read 0xc0000ccc. Both writes
  to 0xc0000ccd completed their barriers and read back correctly.
- VBIF +0x200 read zero successfully.
- The final checkpoint is entry to the write of 0x11 to VBIF +0x200 at
  49.346146 seconds. No write-return marker, halt ACK or CB2 entry was saved.

Thus the prior hypothesis of a stalled first VBIF read is ruled out for
GPU191. The remaining boundary includes the halt write, its completion
barrier, any IRQ preemption and the following checkpoint commit. The log
does not yet prove that the bus transaction itself hung.

The code kept GIC115 and both interfaces' VSYNC/UNDERRUN sources enabled
while halting the active VIG readers. Its IRQ handler performs additional
MDSS accesses, a completion barrier and queues a high-priority callback.
There was no handover exclusion or callback drain. GPU192 addresses that
concurrent access and tests whether it explains the halt boundary; an IRQ
storm remains a hypothesis until hardware evidence is available.

GPU192 masks GIC115 and the owned MDSS sources under the IRQ lock, marks the
binding paused, releases the lock, then cancels/waits for the thread callback.
An already dispatched handler observes paused and performs no MDSS access.
Only then does the existing XIN halt/ACK, CB2 programming and XIN resume run.
Failures retain the paused state. On success, the driver saves the latched
status, acknowledges only its sources, reseeds the live counters and restores
interrupts. Masked frame advances do not create vblank notifications or
presentation completions. Current/retired IOSurface ownership is unchanged.

The candidate retains the same halt register writes/barriers, Hall objects,
system bootstrap and 120 Hz settings. Entry/return markers around IRQ pause
and resume, plus the existing MMIO markers, distinguish the tested boundary.
Persistent checkpoints still perturb startup timing.

Local checks passed: production IRQ core under ASan/UBSan (15 behavioral
groups, existing 41 injected failures plus all handover rearm I/O failures),
actual-code display lifecycle (10 groups), and ARM64 compilation of the IRQ
binding and display backend. The IRQ binding's maximum stack is 160 bytes.
Complete XNU CI and hardware acceptance are tracked separately in
`log/host/gpu-v192/continuation.json`.

## Hardware result

CI 42826799996 and the 64-object link/loader checks passed. The user reported
black screen again. Online syslog captured 691,865 bytes and confirmed IRQ
pause succeeded: fault=0, enable=0, IRQ/master sequence=3376, underrun=0/0.
The full persistent slot later recovered 798,598 bytes ending at the same
VBIF +0x200 write of 0x11, at 49.930372 seconds. There is no CB2 entry.
The 64 MiB slot was cleared/read back, APFS count is 171, and Android boot
partitions are unchanged. IRQ exclusion did not eliminate this stall.
