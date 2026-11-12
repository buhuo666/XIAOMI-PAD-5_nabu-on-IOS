# GPU225：无像素变化的 layer1 清理原位交接审查

2026-11-12。只读审查；没有修改运行时代码、构建、提交或操作设备。范围为精确 `set=clear=2`、所有四层 surface/enabled/rect 均零的既有 `clearsInactiveLayer1` 路径。

## 判断

没有发现需要重复硬件翻帧的语义依赖，可以实现同 FIFO 内的原位事务所有权交接。当前 layer0 已经被真实硬件接受，清理的 layer1 在本驱动中从未启用；新事务没有修改 layer0 内容、映射或扫描配置。因此可以让清理事务继承当前 layer0，旧事务退出 ledger 的活动状态，而真实资源仍由新事务连续持有。需要明确区分 **旧事务退休** 与 **当前物理资源退休**。

这不允许把一般新像素帧标为 Displayed，也不允许将当前扫描资源释放或允许 GPU 覆写。下一次不同真实画面的硬件接受仍是释放当前 mapping、descriptor、surface/display-use、producer read lease 的必要条件。

## GPU225 运行证据

来源：`log/host/gpu-v225/default-ca-path.json`、`default-gpu-chain.json`、`trace-default/records.bin`，run `1794460266799983-scene0-repeat1`。正式1200帧；CA平均5.483498ms，整链平均23.602394ms。

以首个正式帧submit到末帧accept为分析窗口，1200个像素Present对应1801个scan-submit，窗口内有601个clear queued、600个inherit事件；边界会包含正式窗口外事务，不能直接把1801/1200作为所有正式帧的严格配对计数。代表性事务：

| 事件 | 时间（us） | 证据 |
| --- | ---: | --- |
| 像素 swap706 scan-submit | 234117161 | surface20、mapping706、scan sequence706 |
| 清理 swap707 queued | 234117313 | mask2 |
| swap706 accepted | 234124748 | INTF27864/27864 |
| swap707 inherits706 | 234124930 | 同surface20、同lease588 |
| swap707 re-map / scan-submit | 234125502 / 234125503 | mapping707、scan sequence707 |
| swap707 accepted | 234133084 | INTF27865/27865 |
| swap706 physical mapping retired | 234133245 | 旧mapping706由707替代 |
| clear707 complete | 234133256 | status0 |

清理自身确实多占一个刷新窗口，而且它继承的像素与 producer lease 没变。新方案只能消除这次无内容变化的 re-map/re-flip，不能据此预先宣布5ms/8.32ms目标通过。

## 当前关联与不变量

- `NabuDpuDisplay.cpp:617–662` 的唯一 FIFO worker 串行处理请求。清理只有在前一个 `flip()` 返回后才出队，因此正常情况下不存在另一个 worker 同时修改 `held` 或等待尚未接受的上一 Pending。
- `flip()` 在 `:544` 用 `scan.current_sequence+1` 构造真实硬件提交序号；该序号与 `held.swap`、mapping token 没有必须相等的不变量。此前看似相等只是每个事务都做一次flip的结果。GOP翻帧也独立消耗scan sequence。
- `NabuDpuPageTable` 通过 slot/token 管理 Active；`Mapper::accept/releaseRetired` 不读 CA swap ID。原位交接无需改变页表slot/token/generation。
- `held.swap` 是后续真实替换时需要完成的 ledger 事务。将它由A改为N，下一次B接受时原 `flip()` 会对N执行资源release和Retired，无需让N伪造一次scan-submit。
- `held.acceptedAt`、`scan.current_iova/current_sequence` 是已有真实接受的物理信息，应保持原值。`b->accepted`、`lastDisplayTime`、`timingFrames`、硬件counter、VSync序号均不能因清理交接增加或更新。
- producer read租约与surface/display-use由当前Held实际持有；只改swap归属不会使未来writer得到写权限。不能重新acquire这条read，否则会重新引入GPU221修过的“未来writer等待旧read、clear再等待未来writer”的循环。

## 最小实现建议

1. 保留精确请求形态、原 `present()` 入队和背压；不要在SwapEnd入口直接完成清理，否则会越过前面尚未接受的像素事务。
2. 在worker的 `ClearInactiveLayer1` 分支执行专用原位交接，并结束本次worker循环，跳过producer wait、mapper map、`flip()`、ScanSubmit/Accepted。
3. 在同一 `stateLock` 临界区先确认当前无失败、当前清理ledger为Queued、没有先前 `ledger.failedThrough(clear.order)`、物理scan为Ready且没有待发布退休。确认当前Held对应已经接受的scan IOVA及活动ledger。已有mapper故障按原失败语义返回，不交接。
4. 保存旧swap/surface/lease/mapping token/scan sequence用于trace；只把活动Held的swap变为clear ID、kind标为继承清理。保持surface指针及引用、display-use、read指针、ops、leaseIdentity、producerFence、mapping全部字节及原acceptedAt连续不变。不调用Copy/Drop、prepare/complete、map/unmap/TLBI、acquire/release。
5. 在同一个临界区把clear ledger设为Displayed、旧swap ledger设为Retired，再唤醒waiters。不能用分别加锁的 `finishRecord()` 两次拼接，避免观察到“旧事务已退休而新事务未持有”的中间状态。不要持锁调用会重新加 `stateLock` 的帮助函数。
6. 保留成功clear统计和event51。现有 `completeInactiveLayer1Clear(...,inherited=true)` 可以保留新Displayed状态，但先前失败检查必须在所有权交接之前完成，不能先退休旧事务，随后才由completion发现前序Failed。初始GOP、没有任何surface时沿用无资源clear直接Retired，不能虚构Displayed或继承资源。
7. 下一真实像素B仍走完全相同的producer/map/scan/accept路径；只有实际接受后才释放N持有的旧物理资源并发布N物理退休。连续N1/N2/N3清理可多次转移事务ID，始终只有一个真实资源所有者。

当前 `inheritInactiveLayer1Clear()` 先增加同surface引用再交给 `flip()` 的实现应由专用原位路径替代或明确分离；不要仅让它返回旧mapping后再调用旧 `flip()`，后者会再次map并提交硬件。不要清空当前Held然后把空clear整体拷进去，否则会丢失租约和mapping。也不要改ScanoutCore或PageTable的真实接受/释放条件。

## Trace 与分析工具

现有event50为queued、51为complete，55为inherit（id新swap/a旧swap/b surface/c lease），应继续保留。现有55在GPU221–225中是硬件重翻之前的继承记录，不足以单独证明原位交接已提交，不能让历史解码把所有55直接当退休。

建议新增event56，例如 `InactiveLayerClearOwnership`：`identity=new swap, a=old swap, b=mapping token, c=unchanged scan.current_sequence`，在上述原子交接成功后记录。55提供surface/lease，56提供成功交接及未改变的mapping/scan身份；51提供clear完成与状态。实际事件名称可按项目约定选择。

原位交接 **不发event35 Mapped、36 ScanSubmit、37 Accepted、43 ScanAcceptedCounters，也不对旧A发event38资源Retired**。下一次B真实接受时，旧资源的event38归属于新的活动事务N。若把交接伪装成38，既有工具和后续调查会误以为此时物理页已可释放。

`analyze_nabu_gpu_chain.py:25–40` 已排除50/55的clear ID；普通像素帧仍要求唯一32/36/37/43与同surface/mapping/scan身份，因此新clear不会混入FPS或端到端成绩。建议把56也纳入明确的non-pixel集合，并测试没有硬件事件的clear不可被纳入像素成绩。

`analyze_nabu_ca_path.py:25–27,92–99` 当前只用event38解释SwapWait的退休。需在独立“事务完成”索引中加入56的old swap，并标明 `retirement_kind=ownership_transfer`，保持38为 `physical_resource_retirement`。不能无标签合并成一个物理退休时间。计算可唤醒CA的等待可以用二者，但资源生命周期证明只能用38和真实接受/交接链。历史无56文件的分析应不变。

## 必要主机与实机检查

主机应执行实际新的交接函数和worker，不能只修改替身flip的期望：

- A（pending）→N→B：N不得越过A真实接受；N完成后A ledger退休、N显示；同一个A mapping/surface/read仍活动；B真实接受之前N的mode0 Busy，之后资源仅释放一次。
- N期间 `current_sequence`、INTF计数、mapping token/generation、MMIO写次数、GPU writer屏障、引用数和display-use不变；清理不增加pixel accepted、scan-submit或接受marker。
- 连续至少149个清理：ledger可复用已结束旧事务，实际mapping token和scan sequence始终不增加，引用和租约维持单份；最后真实B释放一次。
- A失败/mapper故障/前序ledger失败：N失败，旧owner和资源不变；不得先交接再标失败。GOP无surface、重复ID、非精确clear形态和queue满保持旧协议。
- future writer已等待当前read：清理既不等待它也不放行它；B实际替换后再放行。保持原有锁顺序，waiter只能看到完整事务交接。
- trace样例区分50/55/56/51事务交接与32/36/37/43真实像素接受，保留旧225 trace兼容性。

`check_nabu_dpu_inactive_layer_clear.py` 当前替身flip会给每次clear增加sequence/token，`ordered_a_n_b`、`active_pixel_and_clear_stream`、`backpressure`和future-writer用例需要改为实际原位交接期望。`check_nabu_dpu_flip_gop.py:692` 的 `inheritedPrimary` 当前主动证明每次clear重映射/翻帧；应改成在同一个真实Active映射上交接，再用真实B替换及真实GOP返回证明最后释放。保留普通flip/mapper/scanout失败回归，不能把物理接受前释放的检查删掉。

实机仍按同一15秒场景全体正式帧检验CA<5ms、整链<8.32ms及尾部。要求clear数与所有权交接数吻合、clear无硬件翻帧、每个普通像素提交都有真正接受、无nil/command failure/fault；还需检查结束回菜单和重复测试不冻结。此报告只支持实现候选，不代表安全性或性能实机验收已完成。


## GPU226 实现与主机结果

经父任务批准，已实现上述原位交接：runtime只改 `NabuDpuDisplay.cpp` 和事件声明 `NabuFrameTraceEvents.h`。同FIFO worker在stateLock内先检查failure/failedThrough及真实Ready状态，再将current Held.swap与两个ledger阶段一起交接。活动surface引用/display-use、producer read、mapping token/slot、current IOVA和真实scan序列均保持；下一不同真实画面仍执行原map/scan/accept/release过程。旧重复clear re-flip的读租约转移分支已移除，clear直接完成本次worker循环。

原位clear只有55继承、56事务交接、51清理完成；**没有新增35/36/37/38/43物理marker**，不增pixel accepted、不刷新lastDisplayTime。真实B接受时仍对N持有的旧mapping发38并释放一次。parent负责相应分析器，并已完成区分事务交接/物理退休的回归。

主机结果（`log/host/gpu-v226/`）：

- `inactive-clear/report.json`：10组实际present/worker/交接/wait与FIFO回归，通过ASan/UBSan，覆盖A pending不能越过、连续清理、前序失败、mode0/mode1和租约连续。
- `flip-gop.json`：24组实际Display/ScanoutCore/PageTable/Mapper回归通过，检查77,824,000个原始像素。149次连续交接逐次断言真实scan结构、硬件寄存器、计数、mapping generation/token、引用数、display-use、read及acceptedAt均不变，marker严格只增加55/56/51。下一真实B替换成功才释放一次；B的map失败、flush不完成、退休TLBI失败三条路径仍保留旧资源，未删减此前物理安全测试。
- `lifecycle.json`：19组原生生命周期、VSync ABI/时间基、并发通知、ledger/wait回归通过。
- `display-arm64/report.json`：真实Display对象ARM64编译通过，319,784字节；新event56头已同步到隔离编译树两处。没有更改旧221产物或226continuation。
- `git diff --check`通过；独立只读review由父任务安排并报告无阻断。

以上为主机软件和编译检查，不是实机延时、实际屏幕或硬件接受验收。本任务没有commit/push或设备操作。
