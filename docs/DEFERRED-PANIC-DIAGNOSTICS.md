# 暂缓：定时主动 panic 的日志缺失与调用记录不完整

记录日期：2026-11-04，Asia/Shanghai。状态：**按用户要求暂缓，进入 iPadOS 桌面后再恢复排查**。

用户已决定暂不把此项作为进入桌面的前置验收。当前主线转为系统存储挂载、用户态启动和桌面服务；工作区的 `configs/nabu-unixnu.toml` 已移除 `return_cpu=7`、`return_panic=1`、`loader_return_after=30`。这次只修改后续候选配置，尚未部署到设备。第九轮原始配置已冻结，不改写历史记录。无需为了这项暂缓问题继续安排实机重启或新的诊断构建。

## 问题现在是什么

定时任务正确解析到了目标 CPU 与 panic 参数，CPU 7 也进入了 `requested-panic` 回调，但屏幕报告中仍然没有 panic buffer 标记或预期的 panic 正文。另有一条 `xcall` 结果记录显示为混合文本，不能解释成有效返回码。

最初怀疑的“参数漏部署／早晚参数不一致／目标回调没执行”已被第九轮的新证据排除，不能沿用这几项旧假设。

## 第九轮实机证据

照片：[`screen-return-diagnostics.jpg`](../log/device/nabu-boot-20261104-09/screen-return-diagnostics.jpg)。SHA-256：`28d8ec7383b13190e4f1e8caf34caef1b02ffa9a7110acef134a86d92c1a047a`。

原图、放大的诊断区、结构化观察和启动收据都保存在 `log/device/nabu-boot-20261104-09/`；这些本地证据不随 Git 提交上传。

| 观察项 | 照片结果 | 可以确认的范围 |
|---|---|---|
| 返回画面 | `XNU CALLBACK REACHED`，REASON=0、CODE=0 | 已到达一般内核返回报告；原因码本身不能区分 panic 与普通返回 |
| 定时器标记 | `TIMER MARKER: YES` | 提供给报告器的日志包含到期标记 |
| panic 缓冲区 | `PANIC BUFFER: NOT SEEN` | 本轮日志中没有该标记；不能倒推 panic 分支未执行 |
| 主动 panic 正文 | `REQUESTED PANIC LINE NOT SEEN` | 未捕获预期的 `return_panic: ... on cpu 7` |
| 初始化参数 | CPU 0；`return_cpu found=1 value=7`，`return_panic found=1 value=1` | 初始化时参数正确 |
| 到期参数 | CPU 7；上述两组 found/value 不变 | 定时工作线程在 CPU 7 运行，晚期参数仍正确 |
| 目标回调 | `nabu_diag callback on cpu 7 mode=requested-panic` | CPU 7 已执行打印该行的回调分支；其后的完整 panic 处理流程尚未逐段验证 |
| 日志地址／长度 | `0x180C1C9C0`／`0x51BE`（20,926 bytes） | 本轮报告器接收的物理地址和长度 |

定时工作线程与目标回调都在 CPU 7。此次请求不能作为“CPU 0 向 CPU 7 发送调用”的验证，更不能代替全体核心之间的调度或 TLB 测试。

### 每核计数

以下是内核早期采样到返回前采样的结果，不是全机原子快照。

| CPU | MPIDR | timer | 已处理 signal SGI | 最后 INTID |
|---:|---|---:|---:|---:|
| 0 | `0x81000000` | 0 → 17 | 0 → 4 | 0 |
| 1 | `0x81000100` | 0 → 0 | 0 → 1 | 0 |
| 2 | `0x81000200` | 0 → 0 | 0 → 1 | 0 |
| 3 | `0x81000300` | 0 → 0 | 0 → 1 | 0 |
| 4 | `0x81000400` | 0 → 4 | 0 → 39 | 0 |
| 5 | `0x81000500` | 0 → 0 | 0 → 18 | 0 |
| 6 | `0x81000600` | 0 → 0 | 0 → 3 | 0 |
| 7 | `0x81000700` | 0 → 30 | 0 → 7 | 0 |

八个核心的 signal 计数都增长，CPU 0、4、7 的 timer 计数增长。其余核心在这段采样中 timer 为零，不足以判定定时器故障；本轮没有为各核强制安排定时负载。八核在线及各核 signal 响应已有实机证据，完整调度、IPI 压力与 TLB shootdown 验收仍未完成。

## 未解决的两项细节

### 1. panic 日志没有进入报告

静态代码提供了一条明确线索，但还没有进行针对性的实机确认：

- 当前 ADT 生成器没有提供 `pram` 节点及 `/chosen/embedded-panic-log-size`。
- XNU 的 `pexpert/arm/pe_init.c::check_for_panic_log()` 依赖这些属性建立 `gPanicBase`。
- `osfmk/kern/debug.c::debug_log_init()` 在 `gPanicBase` 为零时直接返回，ARM64 的 `debug_buf_base` 初始也是空。
- `loader_return()` 只有在 debug buffer 指针和长度有效时才追加 `--- panic buffer ---` 及其中正文。

因此，**缺少 panic 区域导致没有可复制的缓冲区**是优先核查的解释。尚未在第九轮记录 `gPanicBase`、`debug_buf_base` 和 `debug_buf_size` 的运行时数值，也未完整定位 panic 的每个阶段，不应写成根因已经实机证实。

恢复排查时，可先记录这些字段，再决定为 loader 提供有界的 RAM panic 区域，或为通用平台补充可靠的 panic 文本捕获。不要为了让屏幕标记变成 YES 而伪造正文或绕过实际 panic 路径。

### 2. xcall 结果行不是完整记录

照片原文：`nabu_diag xcall target=7 result=07 from cpu=7`。

它混合了“请求行”和“结果行”的片段，与源码中任一完整格式都不一致，**不能把 `07` 当成返回值 7 或成功码**。当前两个格式共用 `loader_diag_route` 字符数组；目标回调可在改写该数组期间中断调用线程并走向停机，因此部分覆盖是合理解释，仍属于根据代码与照片作出的推断。

以后应使用分开的请求／结果记录，或者保存固定宽度字段并通过完成标志发布；未发布结果时明确显示“返回值尚未记录”。不必为记录日志而等待一个将主动 panic 的目标回调完成。

## 可复用的构建与冻结输入

| 项目 | 记录 |
|---|---|
| 成功的 macOS Actions | `41765915458`，attempt 1 |
| 内核构建提交 | `f89d0d19e2f4c9136bb1b6c055238711cbdd27ed` |
| 第九轮启动工具提交 | `585d29c81a60c4319842ed58ca121b4f1e330d00` |
| 内核 | `mach.development.bcm2837`，17,106,424 bytes |
| 内核 SHA-256 | `1a252b0f5506123f228cea5e009abb68d710e35a75ca60bf4025f9bc36f6a3b5` |
| EFI | 沿用 v8，具体大小与哈希见该运行目录的 `efi-build-report.json` |
| 部署收据 | `log/device/nabu-chain-20261104-112123/deployment.json` |
| 运行收据 | `log/device/nabu-boot-20261104-09/run.json` |
| 诊断补丁 | `patches/8796/loader-return-diagnostics.patch` |
| 主机及原生检查 | `tools/check_return_diagnostics.py` |
| 屏幕报告实现 | `patches/darwinboot/NabuKernelReport.c` |

macOS Actions 的完整编译、导出合同、原生接口、SMP／页表及返回诊断检查均成功。下载后核对两份内核与补丁哈希，并把六个范围的 1,499 条 LLDB 指令与实际待启动内核逐字节对照。这些检查不替代实机结果。

第九轮已恢复 Android。回读确认 30 份 GPT 元数据和 14 个受检引导分区哈希一致。新增交接日志 `handoff-19DFF73A.txt` 为 7424 bytes，SHA-256 `d19b5e1d652e9f387399fd8244c2fc349a1076afaff2e4a449ab4c9885926966`。

## 恢复排查时的顺序

1. 先确认进入桌面的主线进展，再决定是否恢复这项暂缓问题。不要用第九轮旧配置覆盖后续桌面配置。
2. 读取本文件、`screen-observation.json` 和冻结的 `chain/`，保留现在已取得的八核、参数和回调证据。
3. 修正诊断记录的发布方式；记录实际 panic buffer 状态，并验证正文捕获。若要测试真正跨核调用，明确记录不同的发起 CPU 与目标 CPU。
4. 需要 macOS 的内核构建和原生 LLDB 校验继续使用 GitHub Actions。
5. 真机仍只用 `fastboot boot`；保存每轮候选与回读收据。不得修改 GPT、Android 引导分区或活动槽。

此前调查过程和云端验收详见 [RETURN-DIAGNOSTIC.md](RETURN-DIAGNOSTIC.md)。本文件是暂缓时的状态快照，不表示 iPadOS 桌面、全部 12 GB 内存或磁盘 Data 持久化已经验证。
