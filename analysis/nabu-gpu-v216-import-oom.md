# GPU216 FrameBench surface import OOM

2026-11-11。设备日志与已部署用户态来源的核查；未操作设备。修复的 macOS ARC/ASan/UBSan 与 iOS ARM64 重链/签名已通过，实机效果待验。

## 结论

修正版第五轮终止的直接原因已有明确链条：1600×2560 BGRA IOSurface 导入返回 `no-copy buffer: OutOfMemory(Device)`，随后两次 render encoder 为 `RenderPass(NoTargets)`。不是日志中 GPU fault/timeout 的表现。

用户态有两个不同层面的约束：Turnip 的独立 client IOVA 窗口及已释放 BO 缓存、frontend 的 IOSurface import 强引用缓存。Turnip 的 IOVA 回收只能触达已释放到其退休/缓存队列的 BO；frontend 仍强持的 NBBuffer 不会进入这些队列。frontend 原先在一次新导入成功后才 prune，并且 Device OOM 后直接返回 nil，没有释放自己的可撤销缓存引用再试。因此存在可修复的压力恢复缺口。但本轮数据不能证明是“8 个 surface 泄漏”；事实上已有明确释放证据。

## 已部署输入

`artifacts/nabu-bootstrap-gpu-v212/bootstrap-report.json:935` 记录 frontend 为 CI42757503932、commit `20faac26da133add515720f9b3c9ffb73c3085e5` 的已签名二进制，18,126,848 字节。其实际编译输入保存在：

`artifacts/ci/42757503932-attempt-1/nabu-owned-copy-pages-2/nabu-owned-copy-pages/frontend-source/NativeBridgeMetalFrontend.mm`

该来源包括先前 shader/resource aliasing/owned copied-pages 修复。此次核查使用保存的 frontend 源码；没有把当前 pin 的未应用补丁版本当作实机版本。

同一 bootstrap 的 Turnip 为 CI42607114009 继承的库；该库实际来自 CI42576001993，17,591,024 字节、CDHash `2efb6446d343ec4dd3e8ee699d912852ad9a41d3`。前两份 build-report 记录 copied-without-rebuilding，原构建报告列有 `turnip-darwin-bo-lifetime-v2-map.patch`、resource-submit-v2 等。保存的派生源码是 `build/mesa-v164-focused/src/freedreno/vulkan/tu_knl_darwin.cc`；关键计数/IOVA/host import 逻辑也可与 pinned patch 对照。此次未重复做二进制 hash 审查。

## 失败与 frame 数据

- `log/host/gpu-v216/syslog-live-3.log:200486`：`surface import refused at 110108000+fa0000 id40 1600x2560 42475241: no-copy buffer: OutOfMemory(Device)`；紧随其后两行是 `RenderPass(NoTargets)`。
- `0xfa0000` = 16,384,000 字节 = 15.625MiB，正好是 1600×2560×4。这个虚拟 CPU 地址不能当作 GPU IOVA。
- 修正版四个完整轮次的主表面一直是 IDs33/34/35。第一轮额外出现一次36、第三轮额外出现一次37。
- 第五轮 `1794404849141235-scene1-repeat2.csv` 的 frame414 等 drawable 1,023.434ms 后返回surface38；frame415返回39；两者 command 均完成。frame416/417 的 drawableID 为10424/10425，但 surface_id=0、submit=0。与 texture 导入失败、无 render target 的错误链一致。
- CSV 的 surface_id 与 Turnip BO handle 没有直接关联记录；下表不能据次序冒充精确跨层 identity 配对。BO 的 `sampled_us` 与 App CACurrentMediaTime 本轮也未校准，不能直接相减给出阶段延时。

## `imports=8` 是尝试次数，包含失败

`tu_knl_darwin.cc:1798–1817` 的 `darwin_bo_init_host` 在调用 recorded 版本后，无论 VkResult 是否成功，都会 `++profile.imports; profile.import_bytes += size;`。它是累计尝试数，不是当前驻留数，也不是仅成功次数。GPU216 的 `imports=8` 与 `import_bytes=131072000` 即8次完整表面大小的尝试。

`runtime.log:178639` 起的slot6/generation16统计：

| 项目 | 观察 |
| --- | --- |
| import attempts / bytes | 8 / 131,072,000 |
| IOVA-triggered cache evictions | 8 |
| allocation-triggered evictions | 0 |
| cache objects / bytes | 0 / 0 |
| pending objects / bytes | 0 / 0 |
| pressure waits | 9 |
| reaped | 18 |
| metadata objects / limit | 30 / 4096 |
| slow events / overwritten | 12 / 0 |

12条慢事件完整保留；这里“完整”只指慢事件 ring 没有覆写，不代表所有快事件均被记录。7条成功 host import（operation2）和3条成功 host release（operation3）如下，大小均16,384,000字节：

| slow seq | operation | handle | IOVA | 结果 |
| --- | --- | --- | --- | --- |
| 2 | import | 8213 | 0x11860000 | success |
| 3 | import | 8217 | 0x128dc000 | success |
| 4 | import | 8218 | 0x1387c000 | success |
| 5 | import | 8219 | 0x1481c000 | success |
| 6 | release | 8219 | 0x1481c000 | success |
| 7 | import | 8228 | 0x157c8000 | success |
| 8 | release | 8228 | 0x157c8000 | success |
| 9 | import | 16420 | 0x157c8000 | success |
| 10 | import | 8229 | 0x16768000 | success |
| 12 | release | 16420 | 0x157c8000 | success |

因此7个成功导入中至少3个已释放；其余最多4个可能仍存活，快释放未记录时还可更少。第8次尝试是失败路径，不能按8个活跃导入计算125MiB驻留。7个成功导入的最后一个结束于 `0x17708000`，与 reported peak_mib=375 相符；该字段由kernel维护，需以其定义区分IOVA高水位与内存字节数。

slow seq11 是一次 `vkAllocateMemory()` 的16,777,216字节申请失败，status=`fffffffe`（VkResult -2）；此时 handle=0、iova=0、cached=0、pending=0。host import失败本身没有慢事件，不能仅凭seq11断言失败只发生在这个普通分配阶段。runtime 的原有行为会在import OOM后尝试 copied buffer，随后普通分配也可能失败：`buffer_descriptor.rs:550–556,1281–1323,1603`。新增修复不扩大这条原有copy路径。

## IOVA 与缓存控制流

slot6启动日志明确为 `va_start=10400000 va_bytes=7e00000`，即 `[0x10400000,0x18200000)`，126MiB。`darwin_allocate_iova` 在这套 client heap 找连续区间；失败返回 `VK_ERROR_OUT_OF_DEVICE_MEMORY`。`darwin_bo_init_host_recorded` 先尝试IOVA，失败调用 `darwin_reclaim_cache(...DARWIN_EVICT_IOVA,1,size)` 后再分配一次，然后才发 kernel BoImport。因此纯用户态 IOVA不足可能完全不增加kernel BoImport/BoMap失败数。

`darwin_reclaim_cache` 选取已完成的 cached BO交给worker真正释放；pending BO须等真实fence。它不可能解除仍被frontend/runtime对象持有的导入。126MiB窗口、保留的IOVA高水位、8次IOVA cache eviction、0次allocation eviction、最终cache/pending均0，共同支持IOVA压力；单凭这些还不能区分整个窗口占满与连续空洞不足，下一版应报告窗口的live bytes、最大空洞与失败申请大小。

实际frontend源码：

- `:207` `pruneHeldImports(false)` 只移除 `CFGetRetainCount(surface)<=1` 的held项。
- `:249` `holdImport` prune后把NBBuffer强持入map；map没有数量/字节上限。
- `:271` miss直接调用no-copy bridge；失败立即返回，未先prune或进行cache压力重试。
- `:1191` command completion会 `trimHeldImports(false)`，系统内存压力才 `trimHeldImports(true)`；独立IOVA不足不等于系统发出memory pressure。
- NBTexture `buffer` 为strong属性；command `_surfaces/_resourceOwners` 及Rust runtime继续保存实际工作所需的资源。cache强持只是额外复用持有；删除cache引用本身不授权提前完成GPU或释放仍被这些所有者引用的页。

还有一次性的顺序问题：原 `holdImport` 将可释放NBBuffer移到 `released` vector，但 vector直到函数返回、mutex析构后才真正drop。新miss在成功导入之后才调用它，所以能释放的旧缓存不能帮助当前分配；在OOM时甚至到不了该prune。

## 已实现的窄修复与验收

新增 `patches/nabu-metal/NativeMetalSurfaceImports.inc`，由 `tools/build_nabu_surface_import_cache.py` 只替换已部署frontend里的cache区域，其余源码与Rust archive/Turnip均继承CI42757503932的输入：

1. cache miss在锁内先prune可释放项，锁外实际drop，然后重锁并重新查询weak cache。并发创建者已成功时直接复用。
2. bridge确切返回 `no-copy buffer: OutOfMemory(Device)` 时，仅一次清除held cache额外strong引用，在锁外实际drop，再重查weak cache并尝试导入。Host OOM、Invalid、device lost等不进入此恢复。
3. 每次失败的CFRetain配平，先保存错误文本，避免后续释放覆盖thread-local last error；第二次仍失败保留真实失败，不循环重试。
4. 不修改NBTexture、command、runtime的所有权和完成条件；不增加复制或像素读回；原runtime的兼容copy行为保持既有范围。

`tools/check_nabu_surface_import_cache.py` 直接编译该生产inc，使用真实Foundation ARC/IOSurface及故障注入bridge：覆盖释放后重入mutex、miss前实际释放、精确Device OOM/单次retry、texture持有与模拟pending runtime持有、64并发调用复用同一import、解锁期间另一创建者胜出。GPU执行和Rust runtime在该测试中是模型，不能宣称真实GPU生命周期已验收。

本地 `--stage-only` 已证明仅cache区段替换，Python语法检查通过。macOS专项 `.github/workflows/gpu-surface-import-cache.yml` 的 CI43040953235（head `bbe4ebacfa2e81fb1dd1b429d2c73badda6ae8f0`）已完整成功：真实ARC/IOSurface、ASan/UBSan和64并发/错误恢复测试通过；frontend ARM64重链、iOS16.5检查、签名和既有出口检查通过。

产物已下载审查，回执 `log/host/gpu-v216/surface-cache-download-review.json`。新库：`artifacts/ci/43040953235-attempt-1/nabu-surface-import-cache-1/nabu-surface-import-cache/libnabu-metal-frontend.dylib`，18,126,848字节，CDHash `82dd2e85e9bc553c308e42c020f7ba8c93dda915`；保存的编译inc与当前生产patch一致。

部署只能替换GPU212启动包中的这一份frontend库，保留GPU212实际使用的system factory bundle与helper。该artifact复制来的427575输入还含旧bundle/helper，不能整包反向覆盖已经合格的新系统发现/诊断组件。Rust archive与Turnip未改变。

之后仍需原生分辨率六轮、共享页正确性和10分钟持续测试，核查新导入/释放计数、最大IOVA空洞、错误与画面。CI不是设备GPU生命周期或120fps验收。
