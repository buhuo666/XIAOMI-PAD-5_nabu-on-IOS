# GPU216 FrameBench drawable 回收路径调查

日期：2026-11-11。范围：本地只读源码和原版 20F66 缓存汇编分析；不操作设备，不修改生产代码或基准 App。

## 结论

当前最强线索是 **CAMetalLayer 图像队列的消费与回收节奏**。`nextDrawable` 不是单纯等待 GPU 命令结束：无空闲 drawable 时，它等待 collectable 通知，再执行 `CAImageQueueCollect_`，只有图像样本与 Objective-C drawable 的持有都释放后才能复用。原版检查的是图像队列状态、消费/显示序号，部分配置还检查 IOSurface 的全局使用状态。

原版没有在已检查路径中设置固定 23–27 ms 延时。layer 初始化的 nextDrawable 超时是 1 秒；不能将实测约 25 ms 归因于该超时，也不能仅缩短超时来提高真实帧率。

父任务提供的 revision2 原生 1600×2560 不透明场景数据为：每 60 秒 7200 次 CADisplayLink 回调、应用提交约 36–41 次/秒、nextDrawable 均值约 23–27 ms、编码约 0.74 ms、commit 约 0.08 ms、submit→完成回调观察约 2.5–3 ms。本调查未再次读取设备或独立重算 CSV；这些数据仍需父任务的最终六轮报告为准。完成回调观察值不是 GPU 硬件执行时间。

## 原版 20F66 证据

输入身份沿用 `analysis/cametal-20f66-v173/identity.json`：iPad7,11，QuartzCore 基址 `0x1881fb000`，UUID `dc2dd4c1-7866-3443-8050-fc915a0204c1`。分析直接读取已下载的原版缓存与 v2 指针，不重复哈希审计。

| 阶段 | 位置 | 已确认行为 |
| --- | --- | --- |
| 取 drawable | `-[CAMetalLayer nextDrawable]` `0x18821de60` | `0x18821e0e4` collect，`0x18821e12c` 取空闲项；耗尽后解锁并等信号；唤醒后重新 collect。 |
| 等待 | `0x18821e1b0` 附近 | timeout 从 layer private `+0x28` 读取；stub `0x1884c9608` 是 `dispatch_time`，`0x1884c9584` 是 `dispatch_semaphore_wait`。 |
| 回收通知 | `layer_collectable_signal` `0x188433fb0` | 原子状态 `+0x90` 改为 2；旧值为 1 时，对 `+0x88` semaphore 调用 signal，stub `0x1884c9578` 已解析为 `dispatch_semaphore_signal`。 |
| 可回收判定 | `CAImageQueueCollect_` `0x18826ee4c` | 遍历步长 `0x88` 的共享样本；状态 `0x22222222`、`0x33333333` 可进入 release；另有旧消费序号和同轮未消费样本丢弃条件。这里并未直接等待 GPU fence。 |
| 样本释放 | `release_image` `0x188271f40`，`release_images` `0x1882783a4` | 收集释放信息并调用注册回调；特定队列 flag 下会 decrement IOSurface use count。 |
| drawable 放回 | CAMetal `release_sample` `0x1884335f0` | 减 drawable private 引用计数；归零后将 drawable 放回 layer `+0x30` 空闲链表，或在超额时销毁。 |
| App 对象释放 | `-[CAMetalDrawable dealloc]` `0x1882dadcc` | 同样减少 private 引用；归零时放回空闲链表并通知等待方。因此只有 CA 回收、没有对象释放也不足以复用。 |
| 服务端显示退休 | `CA::Render::ImageQueue::did_display` `0x188283b74` | 检查样本有效性、先前显示时间与消费序号、样本显示序号是否落后于当前值；满足后将 `0x11111111` 改为 `0x33333333`，发 collectable 通知。 |

主要新增证据保存在 `analysis/framebench-drawable-20f66/`；旧的 nextDrawable/init/present 汇编仍在 `analysis/cametal-20f66-v173/`。

### 服务端通知链与关键条件

`did_display` 在 `0x188283c9c` 读取样本的显示序号，与调用时序号比较（`0x188283ca4`–`0x188283ca8`）。旧样本必须已经落后于当前显示，另外还要满足旧消费序号或已过时样本的条件。第一次看到该样本时还可能只记录 host time，稍后的显示回报才会推进退休。因此“GPU 完成”和“CA 宣布此 drawable 可回收”是两个事件。

在共享队列 flags `+0x0c` 同时设置 `0x04000000` 与 `0x08000000` 时，`0x188283cd8` 还调用 `IOSurfaceIsInUse`；仍在使用就跳过退休。**不能预设当前 CAMetal 路径一定走此分支**：init 设置的初值为 `0x24008000`（最大 drawable 数为 2 时另加 `0x00400000`），其中只有前一位；后续运行时 flags 是否改变需实际读取。

通知链是：

```text
did_display / prepare_layer0 / set_visible
  → CAShmemImageQueueCollectable (0x1882762fc)
  → Mach 消息 0x9dd2，或同进程 dispatch_async_f
  → __XImageQueueCollectable (0x1882e7be8)
  → CAImageQueueCollectable (0x1882d77bc)
  → invoke_collectable_callback (0x1882e113c)
  → layer_collectable_signal (0x188433fb0)
  → nextDrawable 唤醒 → Collect → release_sample → free list
```

`CAImageQueueCollectable` 在配置 queue 时经 `dispatch_async_f` 派发，否则直接调用。`invoke_collectable_callback` 本身也会等待同一 queue 上尚未结束的回调。因此服务端更新慢、Mach/dispatch 派发晚、回调互斥等待，都可能造成可见的 nextDrawable 延时；静态证据没有确定其中哪一项占据当前的 23–27 ms。

### IOSurface 语义核对

原版 `_IOSurfaceIsInUse` `0x1a389f840` 最终进入 `0x1a38a22d0`。普通路径直接读共享状态指针 `+0x70` 指向内存的 `+0x18` **整 64 位**，非零即 true；不请求内核通知，也不查询 GPU fence。

`IOSurfaceGetUseCount` 的普通路径则读客户端对象本地的 `+8` 两个 32 位计数并求和，不能用它替代全局 `IsInUse`。原版 increment/decrement 在客户端类别计数 0→1 与 1→0 时才进入 trap 0/1。

项目 `MiniIOSurface` 的共享 `+0x18` 两类别布局与此普通读取吻合：

- `build/nabu-display-sync/tree/iokit/Kernel/MiniIOSurface.h:83` 定义共享 useCount；
- `MiniIOSurface.cpp:777` 的 `MiniIOSurfaceDisplayUse` 调整 display 持有；
- `MiniIOSurface.cpp:1840` 的 `useCountCommon` 调整客户端类别持有；
- `patches/nabu-display/NabuDpuDisplay.cpp:252` 的 drop 减少显示持有；新帧取得真实 acceptance、旧映射退休后才执行 drop（约 431–450 行）。

当前这些函数没有另发 collectable 通知，但不能据此认定缺少 IOSurface 唤醒为根因：原版 CA 的通知由自己的共享图像队列/Mach 链路发送。应先确认运行时是否走 `IsInUse` 分支，再检查旧表面 useCount 何时归零与下一次 `did_display` 的关系。

MiniIOSurface 的 timestamp/indexed timestamp selector 24/33 当前返回成功但不写状态（`MiniIOSurface.cpp:1779`）。这是兼容实现缺口。原版 indexed timestamp 既有直接写 aux 内存路径，也有 selector 33 路径；目前没有证据把该缺口与 nextDrawable 延时直接连接。

### presentedTime 为零的解释边界

`layer_private_cleanup_callbacks` `0x188214650` 明确调用 `didPresentAtTime:0`（`0x188214700`–`0x188214708`）；CAMetalDrawable dealloc 也有同类路径。故 presented handler 被调用、但 time 为零，不能证明真实显示时间。这里只确认原版存在这种清理行为，并未证明 GPU216 正在走哪条分支。

原版 `initWithDrawablePrivate:layer:` 会从递增的 layer 计数生成 drawable ID 并写入对象 `+0x40`（已有 `18821e53c.asm`）；`drawableID` getter `0x188214cac` 返回该字段。历史上 ID 全零应单独核对实际对象/API 与采样值，不能把零当作硬件 frame ID。

## 项目 Metal 前端生命周期

已检查源 pin `AdrenoMetal baad47ca22b181bf0ef0d08412d3ed1f96945e16`，与 `configs/sources.lock.json` 相符：

- `src/AdrenoMetal/NativeBridgeMetalFrontend.mm:1115` 的 `presentDrawable:` 将 `[drawable present]` 注册为完成 handler，因此真正向 CA 插入图像是在 GPU 完成之后；FrameBench 的 app completion handler 后注册，在相同 handler 序列中位于 present 之后。
- `:1165` 在完成时清空 surfaces/resourceOwners，`:1180` 清空原 completedHandlers，临时 handler 数组执行结束后释放；没有看到明显“已完成 command 永久持有 drawable”的源码路径。
- FrameBench 每个 render block 有独立 autoreleasepool（`userland/nabu/apps/FrameBench/main.mm:152` 附近），绘制循环本身没有把 drawable 存入跨帧容器。

这支持将取 drawable 长等待优先归到 present 之后的 CA 消费/退休阶段，但不是运行时资源释放证明。若有 runtime handler 的 autoreleasepool 或额外持有问题，仍需对象 dealloc/空闲链表时间确定。不要将 present 提前至 GPU 完成之前，除非同时实现并验证可靠的 producer fence 传递。

## 下一轮具体任务与判定

| 优先级 | 工作 | 必须记录 | 判定与后续 |
| --- | --- | --- | --- |
| 1 | 对齐同一次帧的应用、CA、内核事件 | App frame、IOSurface ID、drawable ID；nextDrawable 开始/结束；present 插入；CA 消费序号/状态；DPU submit/accept/retire；旧表面 useCount 归零 | 先确定哪段构成约 25 ms。App 表面与合成输出表面可能不同，按真实映射关联，不能只按最近时间配对。 |
| 2 | 测 collectable 通知延时 | 服务端置可回收时间、Mach send/receive、invoke callback、semaphore signal、nextDrawable 返回 | 若已可回收但通知晚，优化派发/互斥路径；若通知快而状态晚，继续显示退休。 |
| 3 | 核对显示序号与退休 | did_display 当前序号、样本 `+0x58`、消费 seed、样本状态；DPU 真正接受的序号 | 修复缺失/滞后的显示完成回报；每次真实 acceptance 推进，不用伪造 vblank 或提前退休换取表面速率。 |
| 4 | 核对全局 surface 持有（条件项） | 队列 flags；`IsInUse` 分支实际次数；DPU/客户端类别分开计数 | 仅在 gate 实际生效且持有延迟已证实时调整 drop；保留真实硬件读租约。 |
| 5 | 核对对象持有（条件项） | 私有 refcount、CAMetalDrawable dealloc、release_sample、空闲链表入队 | 若 CA 已释放但对象迟迟未释放，缩短已完成 handler/对象寿命。 |
| 6 | 同场景验证 | 两类场景各三轮；nextDrawable P50/P95/P99；提交/完成/真实唯一显示帧率；丢帧及尾延时 | 120 fps 的周期为 8.333 ms；必须看真正扫描出的新画面和长期帧间隔，不能只用 CADisplayLink 或完成回调数量验收。 |

可以先利用已有完整持久化日志核对 DPU 输入间隔与 App 提交间隔；若完整日志中服务端供帧已明显慢于 App，优先定位 CA 消费/合成推进。要区分延迟发生在 CA 之前还是之后，至少补齐 present 插入与 collectable 的边界事件；只增加 GPU 计时不能回答这个问题。

## 证据边界

REA 已连接，但此次 native session 没有可用 provider：配置的 Ghidra 路径不存在，Hopper 不支持当前 Windows，IDA/Kuna 未配置。本次沿用项目已有 Capstone 原版字节解码，未声称获得反编译器 CFG 或 REA native Evidence。函数上界取下一个本地符号，直线常量注释仅为辅助；未知间接目标保留未解析。若后续需要完整反编译，按项目规则交 GitHub Actions，不在本机安装额外引擎。

本报告没有修改 GPU/DPU/IOSurface/App 实现，没有安装、重启或操作日志槽。当前设备继续归父任务 GPU216；120 fps 目标尚未验收通过。
