# 定时返回与 CPU 7 诊断

2026-11-04，第八次临时启动照片确认 `TIMER MARKER: YES`，但 `PANIC BUFFER: NOT SEEN`，也未找到预期的 `return_panic ... on cpu 7`。仍显示八核在线与 framebuffer 初始化。REASON=0、CODE=0、LOG BYTES=`0x4B86`。这证明提供给报告器的日志包含定时器到期标记，不能据此认定 CPU 7 主动 panic 成功。

照片保存在 `log/device/nabu-boot-20261104-08/screen-timer-no-panic.jpg`，SHA-256 `bcfa90e120044a1d1ad33fcab52cce9615a107f595b5b713b3154ea865a2bcef`。返回 Android 后 30 份 GPT 元数据和 14 个受检引导分区哈希一致。新增交接日志 `handoff-19EBB78D.txt`（7424 bytes，SHA-256 `e66f9e4e23f8ea28670a3ae1c6035ed130e8dc4bc9a29779515ab9f429df1da4`）包含完整的 `loader_return_after=30 return_cpu=7 return_panic=1`。这确认 loader 的交接输入，尚不证明定时到期时内核仍读取相同内容。

REA 确认本轮冻结内核是 arm64 Mach-O，SHA-256 `a2bc4d4292214639fc4f1dce938c830a8bfdde72102b33b2db81fe995d318a98`。其 Windows Ghidra 后端不接收该格式，未获得 REA 原生反编译。另用 WSL LLVM 读取实际机器码：`loader_return_timer` 中保留两个参数解析调用及 `cpu_xcall`，`loader_return_test` 保留普通返回与主动 panic 两个分支。

对相同内核的实际 `PE_parse_boot_argn` 指令进行主机 Unicorn 仿真，在人工设置的 `PE_state.bootArgs` 指针及本轮参数下，得到 cpus=8、loader_return_after=30、return_cpu=7、return_panic=1。四次都返回找到参数，输出旁的哨兵不变。收据为 `log/host/return-diagnostic-08/parser-emulation.json`。这仅排除该输入下可复现的解析错误，不建立实机晚期参数、缓存一致性或中断处理的事实。

`patches/8796/loader-return-diagnostics.patch` 给现有返回路径加入观测，保留原有目标选择、panic 模式和失败后的本核回退策略：

- 初始化与定时到期时分别记录实际解析返回值、参数值、所在 CPU 和有界命令行。
- 发出 `cpu_xcall` 前记录目标；若调用返回，再记录结果。目标回调也记录其实际 CPU 与模式。异步回调可能早于调用者写入结果，只有请求记录时不能擅自认定返回码。
- 返回前在消息／panic 缓冲区之后追加诊断摘要，以及各核初始化时与返回时的 SGI／timer 计数。计数是独立采样值，不是全机原子快照；计数变化不替代跨核调度或 TLB 测试。

`tools/check_return_diagnostics.py` 从生成后的实际 C 文件提取路由和格式化代码，以 ASan／UBSan 检查 8 个场景：未启用定时器、正常／panic 目标回调、xcall 失败、无效或缺失目标、早晚参数不同、长命令行。IRQ、调度及硬件关闭动作在这些主机测试中使用替身，不能作板上证据。

需要 macOS 的完整内核构建及六个实际代码范围的原生 LLDB 解码均由现有 GitHub Actions `bootstrap.yml` 执行。LLDB 输出逐范围核对原始指令哈希，尚未宣称此实机异常已解决。

## macOS Actions 验收与第九轮候选

Actions `41765915458`、提交 `f89d0d19e2f4c9136bb1b6c055238711cbdd27ed` 全部通过：完整构建退出码 0、导出合同、原版／候选接口分析、SMP／页表检查及返回诊断原生检查。此前两个失败分别来自主机检查的 macOS `__unused` 重定义，以及错误要求优化后仍保留每个静态变量名；后者改为核对日志格式和实际调用指令，未改变内核诊断补丁。

| 产物 | bytes | SHA-256 |
|---|---:|---|
| `mach.development.bcm2837` | 17,106,424 | `1a252b0f5506123f228cea5e009abb68d710e35a75ca60bf4025f9bc36f6a3b5` |
| `mach.development.bcm2837.unstripped` | 22,904,104 | `cd3e9e0e4cb62dd435838a1648aa85fba60896cde2178522ae5ee575131a7c6a` |

下载后核对全部内核和项目补丁的哈希，将六个原生代码范围的 1,499 条 LLDB 指令逐字节与待启动的 stripped 内核对照一致。初始化处三次参数解析、定时回调处两次参数解析、`cpu_xcall` 及早晚格式化调用均存在。验收收据为 `log/host/return-diagnostic-08/ci-candidate-verification.json`。

第九轮采用此内核，沿用 v8 EFI、原有临时 boot.img 及 `loader_return_after=30 return_cpu=7 return_panic=1`。重点记录末尾的 `nabu_diag init`、`expired`、`xcall`、`callback` 和各核计数；实际结果仍需屏幕及恢复 Android 后回读确认。

2026-11-04 11:21:23（Asia/Shanghai）完成部署并回读全部 5 个文件，收据 `log/device/nabu-chain-20261104-112123/deployment.json`。11:22:09 执行第九次 `fastboot boot`，发送与 Booting 成功，源提交 `585d29c81a60c4319842ed58ca121b4f1e330d00`。运行目录 `log/device/nabu-boot-20261104-09/` 已冻结启动链、macOS 构建报告、原生指令与主机检查、部署收据和 boot.img。新内核的 `XNULDRST` slot 在文件中唯一且尚未绑定。当前仅确认启动命令成功，未确认新诊断在实机执行。
