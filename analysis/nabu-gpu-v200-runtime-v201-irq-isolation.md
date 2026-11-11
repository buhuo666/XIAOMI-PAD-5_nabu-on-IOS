# GPU200 实机结果与 GPU201 中断隔离

2026-11-11，Asia/Shanghai。完整四阶段 GPU 目标 active。

## GPU200 实机证据

GPU200 内核提交 `e015fdffab8ada7c3a5e6bddc5969a1a44ebf27e`。
完整内核 CI42940474475、helper CI42940473297、64对象链接、分支检查、
加载器与 APFS 读回通过后临时启动。用户确认桌面和触摸正常。

- 同启动 Snapshot 通过：50,107µs 窗口两路各推进6帧，GOP地址未变。
- HaltResume 通过：halt14µs、resume11µs，ACK解除、原clock位恢复；
  两路计数、vsync与新IRQ各推进6，无新增underrun，GOP gate已解除。
- ActivateGop 请求 `f3543ed54eae4be0937ddfc20ce5e764` 发出后，
  用户确认持续黑屏。AFC结果读取和另一次独立IORegistry读取均超时。
- 没有发起 FlipGop，没有声明接管、翻帧或黑屏修复通过。

完整恢复目录 `log/device/nabu-boot-20261111-200/runtime-log/`：
`slot-01.bin` 67,108,864字节；`runtime.log` 3,261,109字节有效前缀。
`report.json` 无终结记录，原因 `no committed record header`；不是有序终止。
`clearing.json` 清槽读回成功；`run.json` 确认Android引导分区未变。

持久化日志比在线syslog更完整，关键事件按记录顺序如下：

1. 172.717369：XIN quiesce返回成功。
2. 173.869009：CB2 active，root `0x1f1e94000`、ASID65534。
3. 173.890157：IRQ rearm返回，fault0，双计数20633，enable `0x3c000000`。
4. 173.890282：GOP identity enabled返回。
5. 首次 mapper 快照返回 `status=0 active=1 poisoned=0 context=1 routes=1
   identity=1 pages=4000`，TTBR `0xfffe0001f1e94000/0xfffe000000000000`，
   SCTLR `0x27`、FSR `0x400`、GFSR0、TLB0。
6. mapper-read、identity-takeover、resumed-counters-read 的同步 checkpoint
   均有返回标记；最后持久化行是176.333999的resumed-counters-read checkpoint返回。
7. 下一段源码先取得IRQ样本，再进入counter-sample；两者均没有后续持久化证据。

FSR原始值 `0x400` 与本驱动FaultMask `0xc00001fe` 相与为0；
因此不能把FAR `0x1acc7fddffcff`、FSYNR0 `0x2e087f` 或STREAM `0x3ff6`
单独解释为一次有效的新翻译故障。该快照也不能证明此后没有故障。
没有故障PC，也没有足够证据把最后记录对应的下一条源码认定为卡死点。

GPU200已经排除了“尚未读回接管上下文”的证据缺口，NC GOP属性调整未解决黑屏。
IRQ恢复与接管后的实际扫描仍同时发生，需拆开实机对照。

## GPU201 两步控制

保留普通ActivateGop和生产初始化路径。新增：

1. `DpuActivateGopPolled`：同启动Snapshot/HaltResume通过后准入。
   复用实际prepare/quiesce/CB2/resume流程，但保留已暂停的显示IRQ。
   检查真实mapper/fault、双路帧推进、原GOP地址/clock与实际IRQ源屏蔽位，
   成功后解除GOP gate，供用户观察原桌面；结果明确IRQ尚未验收。
2. `DpuResumeIrq`：只有同启动接管通过且IRQ尚未验收时准入。
   冻结/排空GOP写入，单独rearm；重新取得基线，检查新IRQ/双vsync增量、
   无新增underrun以及mapper读回。成功后解除gate并允许FlipGop。

IRQ基线读取增加进入/返回标记。没有修改硬IRQ处理、SMMU寄存器编程顺序、
GOP NC页属性、普通IOSurface WB属性或故障后资源保留策略。
翻帧必须同时满足mapper和IRQ成功；轮询控制成功不计为完整接管验收。

## 主机验证

- 完整Display ARM64对象：257,192字节，最大函数栈784字节。
- 显示生命周期12组、原翻帧19组通过；原始像素检查73,728,000个。
- 新隔离回归执行实际diagnosticRequest、diagnosticWorker、runDiagnostic、
  initializeMapper及收尾代码，连同实际ScanoutCore/PageTable/Mapper读回。
  7组覆盖准入、轮询→快照→独立IRQ→翻帧、原完整路径、单路停顿、mapper
  故障、屏蔽位丢失、IRQ rearm失败和旧IRQ样本。ASan/UBSan通过。
  初次SMMU硬件编程与IRQ绑定为替身，不能代表实机成功。
- 实际worker结果消费者接受7个成功字典，拒绝5个失败及9个错误IRQ验收声明。
- 高位TTBR统一按unsigned64位解析；ASID65534的signed表示通过2组，
  6组错ASID/地址仍被拒绝。

结果在 `log/host/gpu-v201/`。仍需完整云端构建与新实机验收。
