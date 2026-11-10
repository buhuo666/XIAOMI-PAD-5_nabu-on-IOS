# GPU187: native shared-page display candidate

GPU186 collection completed: 5,260,347 bytes of runtime log and the full 64 MiB
slot were retained; clearing/readback passed and Android boot partitions were
unchanged. Run UUID: `2e640ac85ba34d2086fa61e4dc1fc458`, APFS 157 to 158.
Sensors6 subsequently used the device; its current ownership record in AGENTS.md
takes precedence. This candidate has not prepared a log slot or operated it.

The panel and advertised mode are already 1600×2560 at approximately 120 Hz.
GPU186 still logged software pacing without hardware vblank. Its first native
swaps use a fullscreen linear BGRA layer0, or clear all layers. GPU184 qualified
ordinary shared IOSurface pages against GPU read/write, but did not qualify DPU
scanout, asynchronous compositor completion, or a sustained display rate.

## Candidate implementation

- `nabu-dpu=1` selects the new path; it never falls back to copying pixels.
- SwapEnd retains the original MiniIOSurface, adds independent shared use count,
  and captures a NativeAdreno read lease before queueing. A worker waits for
  accepted GPU writers; subsequent writes wait until the display releases the
  read lease. The two-frame queue preserves CPU/GPU/display overlap.
- DPU maps those original physical pages in independent APPS CB2 slots. Fixed
  upper tables remain immutable; only inactive/retired slot leaves change.
  The boot GOP retains an identity mapping during the one-time VIG handover.
- The inherited dual VIG address registers receive the same display IOVA, then
  one CTL flush. Acceptance requires both post-submit INTF counters to advance
  and the flush to clear. Only then can the old mapping be retired; invalidation
  and completed TLBI precede release of its GPU lease, use count and holder.
- GIC115 drives native notifications from actual INTF1 counter/timestamp
  observations. Foreign interrupt sources are not acknowledged as ours. CB2
  translation faults are polled at real vblank and mapping transitions, with
  CFIE disabled and CFRE enabled. Uncertain frames retain their resources.
- SwapWait mode0 means reader retired; mode1 means displayed. Polling incomplete
  work returns Busy. Explicit records handle out-of-order IDs and reject missing
  IDs. Modes2/3 use documented port policies; their complete Apple kernel
  semantics and SwapSignal are not claimed recovered.
- CPU clearing initializes one driver-owned original surface once, before its
  GPU read lease. Normal GPU output is not cleaned from a potentially stale CPU
  cache after completion. CPU-only generic producers remain unqualified.

The GPU scheduler overlay changes two physical-segment queries to explicitly
request raw physical addresses. Its real accepted-job reservations also cover
writers waiting to be issued, physical aliases, and new aliases added while a
DPU lease is active. This is independent of the legacy Mini `drawn` integer.

## Validation and outstanding qualification

Local production-core and binding fixtures cover register failures, both INTF
boundaries, active-slot preservation, complete 4 GiB table traversal, route
conflicts, TLBI failures, descriptor ownership, GPU dependency/alias scheduling,
notification close races, dropped/coalesced interrupts, and explicit swap
history. Existing display configuration and backlight checks pass.

New display/GPU backend objects compile for ARM64. Full Mini framebuffer and
IOSurface compilation requires Apple's XNU compiler builtins; vanilla local
LLVM is not a substitute. The full macOS CI kernel build remains required.
Receipts and raw native-ABI evidence are under `log/host/gpu-v187/`.

The actual Turnip frontend uses native timelines and immediate Mesa submission;
the runtime's held-group gate is disabled for Turnip. In this deployed stack,
Scheduled follows the IOConnect submission's acceptance by the kernel, so the
read lease captures its already accepted writer dependencies. Evidence is in
`log/host/gpu-v187/producer-bridge.md`.

Full macOS CI42788703892 passed at cac37fd, including the native framebuffer,
IOSurface and DPU compilation, producer fixtures and lifecycle fixtures. The
final candidate also includes a locally compiled/tested GPU close fix: a client
whose displayed surface outlives process exit is retained and reclaimed by the
existing completion worker after actual reader retirement, without a new idle
polling loop. Six concurrent close/retirement tests passed.

The candidate kernel is `artifacts/nabu-gpu-ready-v187/kernel.native-apfs.macho`.
It links 64 service/GPU/Hall objects, retains the Hall03 bootstrap and lock-screen
libraries, and passes checks of 8,978 actual direct branches, 2,731 far branches,
48 original component extents, and the actual loader's final memory layout.

The user chose to let sensor testing continue first. No GPU187 log slot was
prepared and no device deployment/boot was performed. After device handover,
test ordinary desktop scrolling, clear,
power changes, resource reuse and measured hardware acceptance/retirement.
No claim of repaired tearing or 120 distinct displayed frames per second has
been made before that qualification.
