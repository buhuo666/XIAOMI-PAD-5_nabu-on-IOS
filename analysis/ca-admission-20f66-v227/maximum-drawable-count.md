# Native CAMetalLayer count 2: supported control and validation boundary

2026-11-12, Asia/Shanghai. Static analysis of the same qualified original iPadOS 16.5/20F66 QuartzCore bytes. No production code, device, or CI changes.

## Recommendation

`maximumDrawableCount = 2` is an explicit native-supported value. For the next diagnostic, use a **newly created CAMetalLayer**, call the original setter with 2 before its first `nextDrawable`, and retain the original lowLatency setting, CA's internal three pages, IOSurface use counts, and DPU read leases. A menu-time setter on an already used layer is not an atomic three-to-two pool contraction and gives weaker evidence about the actual number of surfaces.

This may reduce the number of submitted images waiting for hardware. It does not establish improved callback-to-accept latency. Report callback→acquire, acquire wait, submit→accept, and callback→accept for the same measured rows; also report throughput, complete accepted-frame coverage, and drops/failures. A smaller submit→accept interval with the same total callback→accept interval means waiting moved before submission.

## Supported values and setter behavior

New assembly and function/call metadata are saved here as `188433c38.asm` / `188433c38-calls.json` and `188433cdc.asm` / `188433cdc-calls.json`.

- Setter `0x188433c50..5c` accepts only `(value & ~1) == 2`, i.e. 2 or 3, with a valid private object. Other values enter the original `raise:format:` path.
- Normally `0x188433c9c` stores the requested count at `_CAMetalLayerPrivate+0x7c`.
- `0x188433ca0..cc8` calls `CAImageQueueSetFlags(queue, 0x00400000, count == 2 ? 0x00400000 : 0)`. This is the original double-buffer queue mode, not just a changed getter.
- Getter `0x188433cdc..cf8` directly reads private+0x7c, or returns zero for a missing private object.
- This setter does **not** call `CFRelease`, unregister a surface, flush backbuffers, wait for a swap, or change a driver lease. It also contains no synchronization around its count assignment. Apply it before the render loop starts, not concurrently with `nextDrawable`.

The global at `0x1e1b9cde8` changes behavior: when true, the setter forces any valid requested value to 2. It is decoded below.

## Why an existing pool is not guaranteed to become physically two immediately

Pre-existing original `get_unused_drawable` (`analysis/cametal-20f66-v173/1882fcff8.asm`) first reuses the free list at private+0x30 (`0x1882fd024..d4`). Only when the list is exhausted, and its fourth argument requests the ordinary cap check, does `0x1882fd0ec..f8` compare allocated count+0x78 against maximum+0x7c before allocating.

The release callback is also not a strict instantaneous shrink:

- `release_sample`, `0x188433668..678`, first decrements the drawable-private refcount and returns unless it reaches zero.
- `0x1884336c8..d4` compares allocated count with `maximum + allowance`; the allowance is often 1, with a separate active-layer/time-dependent branch. Only excess beyond that threshold is destroyed. Otherwise `0x188433734..748` returns the object to the free list.
- `CAMetalDrawable dealloc`, `0x1882dae2c..54`, likewise waits for refcount zero before placing the private object on the free list. This path has no maximum-count trimming test.

Therefore an existing pool may retain three allocated or reusable objects even when the getter says 2. A fresh layer removes that inherited-pool ambiguity, although the ordinary implementation still has exceptional/offscreen allocation behavior described next. Do not count only the getter as proof of a two-surface runtime.

## nextDrawable and real recycling

The original `nextDrawable` source evidence is `analysis/cametal-20f66-v173/18821de60.asm`.

- Ordinary visible-layer operation calls `CAImageQueueCollect_(queue, 0, ...)` at `0x18821e0d8..e4`, then `get_unused_drawable(..., true)` at `0x18821e11c..12c`.
- If no drawable is available, it releases the private lock and waits on the original collectable semaphore (`0x18821e138..1cc`), then reacquires and retries. This keeps backpressure before new rendering rather than inventing a completion.
- There is explicit handling for a maximum of 2 at `0x18821e0fc..118`, in conjunction with shared queue flag bit27. It requires a suitable number of collectable/free slots before taking another drawable.
- The alternate path at `0x18821e368..3c4` calls `get_unused_drawable(..., false)`, which can bypass the normal allocated-count cap. It is reached when the layer/queue is not in the ordinary visible consumer state, or after other original conditions. This is why actual distinct surfaces and state transitions must be checked after warmup even for a fresh layer.

Do not change the original flags or fallback code to enforce a guessed bound. If the new test still uses three surfaces, treat the hypothesis as unverified and inspect why the native alternate path ran.

## Active IOSurface protection

Count 2 does not by itself make an active sample collectible.

- Normal `CAImageQueueCollect_(queue, 0, ...)` accepts the original collectible states and old queue generations. Its `0x18826eef0..ef60` logic is unchanged by the setter. The setter only changes queue flag bit22, not these per-sample states or producer completion.
- `ImageQueue::did_display`, `0x188283cb4..ce8`, retains the `0x0c000000` shared flag test and calls original `IOSurfaceIsInUse` before converting the sample into collectible state. Count 2 adds `0x00400000`, which does not remove either of those gate bits. The GPU227/previous traces showed these relevant shared-use bits set; the count-2 trace must verify them again.
- DPU's current Held surface, mapping and producer read lease remain owned by the driver until a real replacement is accepted. The public layer count setter has no path to release those driver resources.
- Actual `release_drawable` releases that private object's IOSurface/texture only after its original reference ownership permits it; the driver has its own independent retained scan resources.

This is static evidence against immediate release by the setter, not an unconditional proof that every native CA state can progress with only two drawables. With one active image and one submitted replacement, failure to receive a real replacement/retirement or collectable notification can stall the next acquisition. The test must preserve and measure that truth; no fake retirement, discarded submitted frames, or early driver drop is permitted.

The original bit22 also affects `Updater::prepare_layer0` flags at `0x1883a6888..8a0` (adds flags `0x600` under the original conditions). This behavior must be considered part of the native count-2 mode. It was not simulated or proven by the getter/setter alone.

## Menu-time change versus a new layer

Both 2 and 3 are accepted on a valid existing layer. The native setter performs no synchronous destruction, so a menu-time call is not intrinsically a request to release the current scanout. However, menu visibility does not prove that prior CA/DPU resources have retired, and the retained free-list/max+1 behavior makes an already-used layer a poor way to prove a new pool size.

Prefer creating the diagnostic's count-2 layer before first rendering, after the previous diagnostic render queue has finished. Use the public native setter; do not invoke the internal flush helper to force shrinkage. Removing the old layer from the hierarchy may trigger ordinary CA cleanup, while the driver must still keep its real active scan resources until replacement. Wait for/observe the normal new layer and its warmup; do not equate layer removal with hardware retirement.

## Default integration which respects explicit App values

This property is not initialized through `+[CAMetalLayer defaultValueForKey:]`. The original initializer `0x1882235e8..5fc` writes private+0x7c directly: 3 normally, or 2 when global `0x1e1b9cde8` is set. The getter also reads that field directly. Merely overriding the class default-value dictionary would not establish a count-2 default.

The global is **CA_FORCE_DOUBLE_BUFFERING**. The original `init_debug` string-table/boolean-array mapping identifies index 120, name-pointer entry `0x1d57ffae0`, and byte `0x1e1b9cde8` (retained in `flag-candidates.json`). It is a real environment/preferences input, but because `setMaximumDrawableCount:` subsequently forces even explicit 3 to 2, it does **not** satisfy the requirement to respect the App's requested value.

A bounded future default policy could call the original native setter with 2 immediately after the original standard CAMetalLayer initializer returns, before the caller receives the layer. Then all later explicit App calls with 2 or 3 continue to the original setter unmodified. Do not clamp that setter or silently change getter results. Alternate, copy, coder, and subclass initializer paths need their own review before claiming complete system-wide defaults. No such implementation is included here.

FrameBench currently explicitly writes `maximumDrawableCount = 3` in `prepareRenderer`. For a count-2 diagnostic, the test must explicitly select 2 and report it. A system default that respects explicit App values should not secretly override FrameBench's explicit 3.

## User-constraint audit

Searched current `AGENTS.md`, `docs/SPECIAL-STEPS.md`, and the two supplied pasted histories:

- `C:/Users/buhuo/.codex/attachments/77f52753-6fc2-46b4-ab52-8ddfcdcb7664/已粘贴的文本.txt`
- `C:/Users/buhuo/.codex/attachments/631453d2-f88f-4114-b23b-b046958d8933/已粘贴的文本.txt`

The matches for retaining `3drawable` are assistant-authored candidate/baseline records and commands which prepend those records to AGENTS. Within this search boundary, no direct human instruction requiring exactly three drawables was found. The current user goal specifies latency limits. Treat three as the recorded baseline unless another directly quoted user instruction is found; do not invent a new approval requirement from that baseline. This bounded result does not assert that every older chat has been searched.

## Verification evidence to keep

For the same measured rows, preserve: selected count/readback; unique surface IDs and the reuse cycle; App callback/acquire/submit/complete/present times; CA's selected sample; real DPU acceptance and retirement; occupancy before each submission; per-row and aggregate callback→accept alongside submit→accept; complete coverage and hardware cadence. Keep CA's own three page records unchanged. If throughput falls, frames are absent, or nextDrawable times out, report that failure rather than calling lower submitted-frame latency a success.
