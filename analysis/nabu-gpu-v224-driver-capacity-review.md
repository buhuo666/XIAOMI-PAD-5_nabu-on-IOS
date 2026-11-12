# GPU224：DPU 容量与 CA 单空闲页准入的边界

2026-11-12。只读代码和已保存的 GPU224 trace；没有操作设备或修改驱动。

## 结论

初始“CA 只有两页”的假说已被原始 event96 修正：已保存的 8488 次 can 调用均报告 count=3，首个正式帧报告 next=2。问题在于普通 `can_update_(flags0)` 检查两页并可能在第二页 Busy 时撤销第一空闲页的准入，不是页数不足。因此不应增加 CA 页数。

单空闲页准入候选也不需要扩大现有 DPU 页表槽数或软件 FIFO。DPU 并非只有两个映射槽：`NabuDpuPageTable.h:8` 已定义 32 个独立、每个 32 MiB 的槽；`NabuDpuDisplay.cpp:105–107` 的 `held[SlotCount]` 和 `queue[2]` 是两种不同资源。FIFO 的两个元素不含 worker 已取出的当前请求，也不含仍在扫描的 Active 画面。增加 FIFO 深度不会使硬件更快，反而允许更多排队延时。

使用原版 `can_update(flags1)` 保留单空闲页能否把整链减少一个刷新周期仍需真机验证。在已有一帧积压且提交与接受严格同速的状态下，单纯提早入队仍排在旧 Pending 请求之后；必须观察启动/过渡如何进入无积压稳态，不能从正常测量中删除不利帧。

## 驱动语义

- `NabuDpuMapper.cpp:499–538` 从 32 个槽里找第一个 Free，持有并 prepare 真实 descriptor，发布页表及 TLBI 后交付 mapping。没有按 CA 页号限制为两槽。
- `NabuDpuDisplay.cpp:617–657` 的单 worker 从 FIFO 取出后才等待 producer 并映射/翻帧。当前请求等待真实接受期间，后续请求可在 FIFO 中保留 surface 和 read lease，但不会同时重写硬件 Pending 寄存器。
- `NabuDpuDisplay.cpp:733–738` 只在两个 FIFO 元素都占用时施加背压；该等待在新的 ledger 插入和 surface acquire 之前。
- `NabuDpuScanoutCore.cpp:100–152` 同时只允许一个 Pending：Ready 才能提交，提交后验证 flush、两路 INTF 计数推进和 source/stride 读回。不能为了低延时覆盖尚未接受的 Pending。
- `NabuDpuDisplay.cpp:551–585` 保留新旧资源直到真实硬件接受，随后 mapper 将新页转 Active、旧页转 Retired，完成旧映射撤销/TLBI并释放旧读租约，最后发布旧 swap Retired。
- `NabuDpuPageTable.cpp:113–129` 明确拒绝释放当前 Active；`SwapWait(mode0)` 仍必须等待 Retired，mode1 才能在 Displayed 时成功。增加 CA 页不需要改变这些条件。

原生 CA 已有“当前扫描页 + 待显示页 + 可准备页”的容量。硬件实际仍为单 Active + 单 Pending；队列元素与 CA 页没有一一固定映射关系。

## 原版 can_update(flags1) 独立审查

来源为现有 `analysis/framebench-drawable-20f66/188235f54.asm`、`18829cd88.asm`、`18825dda4.asm`、`188248568.asm`，以及 `analysis/ca-phase-20f66-v223/18846bf04.asm`、`188478624.asm`。

- `0x188236020–60cc`：仍最多检查 `min(count,2)` 个候选页；bit0=1 只跳过遇到 page flags低2位为2时写 `display+364=4` 的步骤。
- `0x18823610c–6110`：传给真实 SwapWait 的阻塞/非阻塞选择由 **flags bit1** 控制；flags1 的 bit0 不把 mode0 退休查询换为 displayed 查询。
- `0x18823627c–62e4`：Busy 页没有走 `0x188236150–61f4` 的 swap清零、unref和free计数增加；bit0=1 使 w22=0，保留此前已经清理成功的 free count。第一候选本身 Busy 且没有空闲页时仍返回 false。
- `0x188236364–63e0`：bit0=1 不递减 `display+364`；并参与 `display+9f2` bit51 的单空闲页标志，detached 路径下可能有不同结果。最终 free count 仍受同一状态字 bit32 的扣减，bit0并不绕过该条件。
- 外层 `can_update` `0x18829cd88` 仍保留 display enable、mode、虚方法和状态门禁，并只采用内部原函数结果。
- `begin_update` `0x18825e840` 读取 `display+358` 作为真正准备页。对 GPU224 已观测的 next2空闲、page0 Busy 状态，flags1 保留的正是 next2，不是正在扫描的 page0。

对上述观测状态，完整调用原 `can_update(flags1)`、随后维持原普通 render(flags0)，未发现提前复用或释放 Active 页的路径；仍需真机及边界回归。不能把这一结论扩大成所有 CA 状态均已证明，也不能把 can 返回强制改为 true。

**它与完整 immediate render 不等价。** `render_for_time` 的 flags bit0 会同时传给 display vtable+150（`0x18846c498`）并写到 `Render::Update+328` bit8（`0x18846c50c`）。只改变 can 参数不会设置这些值。`finish_update` `0x1882487f8–8854` 用 Update bit8 和空闲页数/其他条件决定是否增加一个周期到 requested 时间；flags0 可能保留该时相行为。该差异目前首先构成绩效/排程未知，不是已有证据证明的提前释放。最小候选以原 flags0 调用失败且下一页资源确实全空为门槛；原非零 flags 和原定时参数保持不变。这是资源门槛，不声称能够追溯某次异步 can 调用是否来自 context timer。

## GPU224 证据与条件推演

来源：`log/host/gpu-v224/{default-ca-path.json,default-gpu-chain.json,trace-default/records.bin}`，run `1794458352632490-scene0-repeat1`。1800/1800 正式帧完整关联，CA 总平均 5.407488 ms，整链平均 15.202478 ms。全体都有一次旧 swap Busy 后等待退休，平均 4.252383 ms。

首个正式帧：

- App submit 152134187 us，present return 152136612 us。
- 当时当前扫描 swap712；swap713 已在 152134436 us 提交硬件，尚未接受。
- CA 查询旧 swap712 得 Busy；swap713 在 152141058 us 接受，swap712 在 152141221 us 退休。
- 当前帧 swap714 的 scan-submit 152142783 us，接受 152149391 us。

即使在本次 present 后立即让 swap714 入 FIFO，已经 Pending 的 swap713 仍占用首个硬件接受机会。这说明不能在同一条现有稳态记录上把等待直接删掉并声称已优化。

另做有限的余量推演：对各正式帧取 App submit 后的第一个真实事件39 VSync，将观测 scan-submit 减去该帧 `last_busy_to_retired_ms`。这是假设此前积压已经消除、其他成本不变时的可用时间，不是实测新调度：

| 指标 | 平均 | 最小 | 最大 |
| --- | ---: | ---: | ---: |
| App submit → 首个后续真实 VSync | 6.814798 ms | 6.171 ms | 7.018 ms |
| 假设移除退休等待后，scan-submit 到该 VSync 的余量 | 2.530213 ms | 1.143 ms | 2.951 ms |
| 实际接受时间 − 该首个 VSync | 8.387680 ms | 8.366 ms | 8.436 ms |

1800 帧的条件余量均为正，支持继续研究原生 CA 单空闲页准入；不证明新路径的额外成本、首帧积压、硬件锁存或像素正确性，也不能据此把 8.32 ms 目标标为通过。

## 最小候选与验证范围

最小候选应局限于原版 CA 单空闲页准入机制，保留 GPU224 base timer、3 drawable、真实 swap 退休、producer fence 和 DPU 单 Pending。不要同时扩大 DPU queue 或更改 Scanout acceptance，这样能单独判断 CA 页准备是否解开等待。

现有主机回归可覆盖 `check_nabu_dpu_page_table.py`、`check_nabu_dpu_flip_gop.py`、`check_nabu_dpu_display_lifecycle.py` 和 `check_nabu_dpu_inactive_layer_clear.py`。后者已有真实 admission/FIFO/SwapWait 的背压测试：一个 worker 阻塞、两个 FIFO 元素占满时第四请求等待，按序推进后成功，Active 租约持续保留。若驱动代码不变，不需要为了三页而重写队列实现。

新 CA 候选应补至少这些状态回归：next空闲+第二页Busy；next Busy+无已清理页；next为current页被跳过；两个页均已退休；bit32保留状态；原非零flags透传；只影响已安装的四个display表及满足资源条件的调用；shutdown取消与原锁顺序。真机需从菜单进入相同 15 秒场景，并保留 warmup/首帧过渡和全部正式帧。核对单空闲页是否选中、正式帧首次can是否成功、FIFO residence/depth、首个VSync是否接受同一swap/surface、三张App surface与CA页复用、结束菜单的layer1 clear，以及零nil/command failure/driver failure。均按同一测量帧报告CA与整链均值、P95/P99、最大值和超标帧数；不以吞吐120/s替代延时验收。


## GPU225 候选实现与主机验证

已在 `ca_context_timer.c` 实现双 opt-in：`NABU_CA_CONTEXT_TIMER=1` 选择已有timer，`NABU_CA_SINGLE_FREE_PAGE=1` 额外选择4个display can槽，共6槽。第一次完整原can成功或原flags非零直接透传；只有false/flags0才在原page mutex+368下检查count3、next<3、next!=current，以及next页frame/swap/renderref/surface/fence全零。解锁并恢复首次原can返回时的errno，再完整调用同一predecessor(flags1)，返回其真实结果；第二次返回后不再访问对象。检查仅是重试提示，原方法自己重新上锁和验证。

观察库合并链接到同一timer dylib，由timer constructor先安装trace、后安装timer；不链接原trace constructor。观察器只新增已安装can指针getter，不改变原行为。安装只接受精确20F66 native can或本库成功安装的traced_can，每个槽保留自己的前驱，trace因此能记录两次真实flags0/flags1。观察器-5恢复保护失败时getter返回0，timer遇对应未知前驱则整体拒绝六槽安装，不盲覆盖。待应用的启动包应移除单独trace注入，保留timer注入，运行日志预期trace capabilities63、timer slots6/single-free-page1。

主机检查位于 `log/host/gpu-v225/context-timer-host-check/report.json`。保留108组调度/ABI；新增153组单空闲页条件、errno/原raw返回、真实observer串联及真实线程在检查后将页改忙的回归；72组六槽安装/准备失败/保护恢复失败/未知前驱场景。ASan/UBSan、原观察器76 marker回归、timer和observer ARM64对象编译通过。builder/check脚本已加入合并观察器构建和测试。主机用平台替身模拟原can边界，不能替代原版CA实机验证；运行收益、普通render flags0保留的时间行为、积压转态与画面正确性均待上机。
