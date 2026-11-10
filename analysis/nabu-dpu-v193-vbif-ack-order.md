# GPU193: poll the VBIF ACK before a completion barrier

2026-11-10, Asia/Shanghai.

GPU191 and GPU192 both ended at entry to VBIF +0x200 write 0x11; GPU192 had
already masked GIC115 and MDSS IRQs and drained callbacks. Both traces showed
successful clock writes/readbacks and a zero halt-request read. Neither
reached CB2 programming. GPU192's complete slot and 798,598-byte runtime
prefix are backed up and cleared; APFS count is 171.

The fixed MiCode nabu source (71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c) shows:

- `sde_hw_set_halt_ctrl` reads and writes CTRL0 via SDE_REG_READ/WRITE.
- `sde_reg_write` uses `writel_relaxed`; `sde_reg_read` uses `readl_relaxed`.
- The ARM64 relaxed accessors issue the Device store/load without a following
  `dsb sy`. The caller proceeds directly to polling CTRL1's real ACK.

The newly downloaded accessor sources and their provenance are saved in
`log/host/gpu-v192/reference`. Existing register definitions are unchanged.

Our code instead executed `dsb sy` immediately after the halt-request store,
before the first readback or ACK. Trace mode added another such barrier in
the write callback and then synchronously committed the log. GPU193 removes
these pre-ACK completion waits for VBIF. It retains the request readback,
requires both hardware ACK bits, and executes the existing full barrier only
after those bits are observed. Resume verifies the cleared request before
its barrier. MDP clock/scanout, page-table and IRQ barriers stay unchanged.

Diagnostic calls between the VBIF request and return from ACK polling are
suppressed so logging cannot reintroduce a completion barrier there. The
entry checkpoint is still committed before the write, and the quiesce result
is committed after polling returns. A returned store is not called a hardware
ACK, frame completion or surface retirement.

The production core passed ASan/UBSan fixtures including a deferred-halt-ACK
model that rejects an early completion barrier, partial/missing ACK, request
ownership, resume preservation and dual-frame retirement. This models the
source protocol; it does not prove that an early barrier caused the physical
hang. ARM64 core and display compilation passed (core maximum stack 128 B).

The candidate retains GPU192 IRQ exclusion, Hall, the current bootstrap and
120 Hz settings. Complete CI, deployment and visual acceptance remain
separate and are tracked in `log/host/gpu-v193/continuation.json`.
