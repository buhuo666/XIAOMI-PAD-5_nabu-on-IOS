# 20F66 CA 短窗口诊断实现

日期：2026-11-12。父任务整合 GPU218；本项不部署设备、不修改 CA 配置、不加入 `CA_DISABLE_DETACHED`。保留 GPU217 的 `CA_FORCE_TIMER=1`，复现约28ms App完成→DPU入口延时。记录通过父任务统一 marker sink进入已有 GPUtrace，采样由其短窗口控制，不再做60秒基准。

## 可执行入口

- `userland/nabu/src/ca_frame_trace.c/.h`：无constructor核心，`int nabu_ca_frame_trace_install(nabu_ca_trace_sink)`。
- sink精确签名：`void(uint32_t event,uint64_t identity,uint64_t a,uint64_t b,uint64_t c)`。
- `userland/nabu/src/ca_frame_trace_entry.c`：仅 `NABU_CA_FRAME_TRACE` 精确为 `1` 且进程为backboardd时安装；调用父任务的 `nabu_ca_trace_marker`。安装结果与capabilities只在启动时打印一次，失败也可见。
- `tools/build_nabu_ca_frame_trace.py --output <dir>`：Xcode16.4、arm64-apple-ios16.5；生成可独立链接的 `ca_frame_trace.o`、constructor对象和 `libnabu.ca-frame-trace.dylib`，使用4096字节页ad hoc签名。无设备操作。
- `tools/check_nabu_ca_frame_trace.py --output <dir>`：主机ASan/UBSan实际源码测试；macOS用xcrun，Windows沿用项目WSL clang18。

## 为什么采用这些入口

项目现有 `bluetooth_compat.c` 已使用 `vm_region_64`、`vm_protect(...VM_PROT_COPY)` 修改已验证的const数据函数指针；FairPlay等使用dyld interposition，但本次CA调用含sharedcache优化stub和同镜像直接BL。项目没有已验证的ARM64内联trampoline基础，不能假设dyld能拦截内部BL。

本实现只修改已证的数据指针，不写可执行text，不复制/重定位原版指令，不安装异常断点。

四个原版vtable分别为：AppleDisplay `0x1d57ddc60`、IOMFBDisplay `0x1d57de420`、AppleRGBOutDisplay `0x1d57ebd00`、AppleCLCDDisplay `0x1d57ec520`。vtable函数区为表起点+16，三种槽位：

| 函数区偏移 | 原版目标 | ABI |
| --- | --- | --- |
| `+0x140` | `can_update` `0x18829cd88` | x0=Display*，w1=flags，w0=0/1；wrapper用uint32_t原样传回w0。原版所有返回分支明确写w0=0或1，不做归一化/改变判定。 |
| `+0x170` | `begin_update` `0x18825dda4` | x0=Display*，x1=Update*；wrapper保存原始x0返回，不猜返回值语义。 |
| `+0x178` | `finish_update` `0x188248568` | x0=Display*，x1=Update*，w2=flags；原始x0返回保留，未强制转换为bool。 |

12个槽位已直接核对原版cache解码指针，索引 `analysis/framebench-drawable-20f66/runtime-vtable-sites.json`。安装先验证QuartzCore UUID `dc2dd4c1-7866-3443-8050-fc915a0204c1` 与全部12槽原指针，全部数据页COW取得成功后才写槽。拒绝可执行页；结束后恢复原页保护。初始化后库须保持加载至进程结束，不实现有竞争的卸载恢复。

实际Display入口还读取 `display+0x318` 的IOMFB对象。IOMFB UUID必须为 `a8517801-7f27-3641-b977-c5831e37fe9f`，且对象内部dispatch槽 `+0x730`、`+0x750` 必须分别指向原版 `_kern_SwapEnd 0x1af12c530`、`_kern_SwapWait 0x1af12c648`；才以原子比较交换装入wrapper。未知后端或被其他观察器修改的槽保持原样并记录状态。该操作不依赖sharedcache外部调用是否可interpose。

`_IOMobileFramebufferSwapEnd 0x1af12cfa8` 以 `br [fb+0x730]` 转入后端；SwapWait `0x1af12c0f8` 同理使用 `fb+0x750`。SwapEnd wrapper签名 `int32_t(void *fb)`；SwapWait为 `int32_t(void *fb,uint32_t swap,uint32_t flags)`。因此无第三timeout参数误配，也不会吞掉额外参数。原版selector6内部仍构造timeout=0；原返回值/errno保留。

## 记录的覆盖与边界

**没有直接hook `prepare_layer0`、`CopyImageInfo`、`did_display` 或collectable函数入口。** 本实现直接观察已核验的Display virtual dispatch与IOMFB后端dispatch。Update对象树在finish_update调用原函数前按原版布局遍历，记录已经选择并保留的ImageQueue与共享sample状态；这不是选样前后成对记录。collectable发送/接收由父任务另一项内核IPC40402记录接续。

Update持有的树布局来自 `update_image_sample 0x18824fb8c–0x18824fbec` 和析构 `0x18823a1f4–0x18823a250`：begin在Update+0x2e0，end在+0x2e8，node+0x20是对象，仅对象+0xc==0x1a按ImageQueue解释。树遍历最多8节点、2个ImageQueue、32步；每个queue最多4个sample，超过上限发limit marker。无对象retain/release、无额外锁、无分配、无等待、无每帧日志；原函数返回后不读Update/queue/sample。

快照不是一致性事务：32位对齐字段按单次volatile load读取，64位字段由两个32位读取组成；共享生产者可更新，因此应保留raw与相应时间，不推导原子状态切换。对象由当前原版调用/Update持有，日志不跨帧保存指针以供随后解引用。

安装返回capabilities：bit0 Display槽，bit1 IOMFB后端槽可支持，bit2选后queue快照；成功通常7。bit1表示镜像身份允许尝试后端槽，不等于已看到真实fb调用；event113及实际108–112记录才证明该handle被拦截。失败值-3为原槽不匹配，-4为COW准备失败（未写槽），-5为已写槽后的保护恢复失败；-5仍保留透明wrapper以避免卸载竞态，应在启动日志中视为失败。

## 字段表

下表是传入统一sink的原始四个参数。`pair(lo,hi)=lo|(hi<<32)`。所有pointer/返回地址为当前进程真实VA，只有分析时根据已验证slide归一化；marker时刻由父任务内核记账提供。

| 事件 | identity | a | b | c |
| --- | --- | --- | --- | --- |
| 96 CanEnter | Display | flags | pair(page index,page count) | IOMFB pointer |
| 97 CanLeave | Display | 原w0结果 | flags | pair(page index,display+0x438) |
| 98 BeginEnter | Update | Display | update frame(+0xe0) | IOMFB pointer |
| 99 BeginLeave | Update | Display | entry时frame | 原x0结果 |
| 100 FinishEnter | Update | Display | pair(frame,flags) | IOMFB pointer |
| 101 FinishLeave | Update | Display | pair(entry frame,flags) | 原x0结果 |
| 102 Page | Display | pair(page index\|phase<<8,page+0 frame) | pair(swap ID,page+0x28 raw flags word) | page+0x10 surface pointer |
| 103 UpdateTimes | Update | +0x48原double位形 | +0x68原double位形 | +0x70原double位形 |
| 104 Queue | ImageQueue | shared pointer | pair(update frame,queue+0x94 last processed frame) | pair(shared flags+0xc,queue sample count+0x88) |
| 105 QueueWords | shared | pair(+8,+0x20) | pair(+0x14 queueID,+0x24) | pair(+0x28,queue+0x98 client port) |
| 106 Sample | shared | pair(index,surfaceID +0x38) | pair(state +0x3c,seed +0x40) | pair(display frame +0x58,first-use frame +0x5c) |
| 107 SampleTimes | shared | index | sample+0原double位形 | sample+0x28原ticks |
| 108 WaitEnter | IOMFB | pair(swap,flags) | 返回地址 | 0 |
| 109 WaitLeave | IOMFB | pair(swap,flags) | 原32位IOReturn | 返回地址 |
| 110 SwapEnter | IOMFB | request+0x50 swapID | request+0 requested timestamp | 返回地址 |
| 111 SwapLeave | IOMFB | entry时swapID | 原32位IOReturn | 返回地址 |
| 112 SwapLayers | IOMFB | pair(sid0,sid1) | pair(sid2,sid3) | pair(set,clear) |
| 113 FramebufferHooks | Display | IOMFB | 当前SwapEnd槽 | 当前SwapWait槽 |
| 114 SnapshotLimit | queue或Update | 1=sample截断；2=对象树截断 | count或pair(visited nodes,queues) | 上限4或walk steps |
| 115 SampleWords | shared | pair(index,valid +0x44) | pair(use count+0x54,+0x60) | pair(+0x64,+0x48) |

Page偏移相对 `display+0x3a8+i*0x30`，phase0为can_update之前，phase1为finish_update之前。Sample偏移相对 `shared+0x188+i*0x88`。`UpdateTimes`等double值保持bit形，离线按IEEE754解码，不经字符串或浮点换算。

## 验证与本轮问题拆分

`log/host/gpu-120fps/ca-frame-trace-check/report.json`：ASan/UBSan通过实际wrapper测试，涵盖原参数、64位x0/32位IOReturn、errno、输入对象字节不变、3页上限、4sample上限、非ImageQueue跳过、空树、UUID不匹配、12槽安装的预检查机制、第二页COW失败前回滚、未知dispatch槽保持原样。实际原版12槽已另从cache逐条核对。核心已用本机clang18成功编译arm64-ios16.5对象；完整Xcode签名dylib由父任务专项CI生成。

短窗口分析顺序：frontend PresentAfter→内核Mach入队/收到→BeginEnter→FinishEnter→SwapEnter→DPU present。CanEnter/Leave与WaitEnter/Leave用于证明page Busy或调用执行耗时；FinishEnter的queue/sample可确认当时已选哪个surface/seed。FinishLeave→原版Update析构/collectable仍没有用户态直接入口标记；IPC40402能提供通知边界，但不能据其缺失断言did_display未运行。若begin到finish前已耗尽约28ms，可进一步限定渲染/准备工作；若这些都快，则结合Mach与选后sample关系，缩小选样之前的等待。

诊断会增加bounded marker syscall与快照读取开销；同一短窗口需要保留原始时间和调用计数，不把本轮测到的绝对耗时当成零扰动基准。没有“120fps已通过”或“28ms已定位根因”的提前结论。
