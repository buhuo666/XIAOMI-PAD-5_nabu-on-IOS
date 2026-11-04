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

需要 macOS 的完整内核构建及六个实际代码范围的原生 LLDB 解码均由现有 GitHub Actions `bootstrap.yml` 执行。LLDB 输出逐范围核对原始指令哈希。构建和原生检查成功后才准备新的实机候选，尚未宣称此异常已解决。
