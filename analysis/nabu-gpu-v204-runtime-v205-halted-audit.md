# GPU205：暂停取数期间只读 SMMU 的对照

2026-11-11，Asia/Shanghai。GPU204的分段结果见
`nabu-gpu-v203-runtime-v204-stage-timing.md`。首次SMMU写入前，源/路由检查已耗时214181µs，
旧上下文读取61752µs。尚未证明画面在首次写入前已黑，也不能把长耗时直接当作总线延迟。

本轮使用显式启动参数`nabu-dpu-halt-audit=1`扩展现有DpuHaltResume诊断：

1. 在暂停前准备并审查独立的临时Mapper对象，尚不写任何上下文/路由寄存器。
2. XIN0/4确认暂停后，只读复查源、全部路由、ASID及继承CB2上下文/FSR。
3. 不编程TTBR、SCTLR、ACTLR或TLBI，无论只读检查成功或拒绝，都先尝试恢复自己的XIN。
4. 恢复后释放从未交给硬件的临时页表池，再输出实际耗时、SCTLR和只读检查状态。
5. 沿用独立HaltResume的IRQ/双vsync/underrun检查及GOP写入解冻。

真正的显示Mapper指针仍为空，结果明确`halt_audit_requested=true`、`smmu_programmed=false`、
`smmu_changed=false`。主机消费者要求只读状态成功、实际SCTLR仍为0xe0和有效计时。
这项对照用于区分“暂停/读取”与“启用翻译”；不冒充页表接管通过。

本地实际Mapper测试确认整个1MiB模拟APPS寄存器区在只读对照前后逐字节相同，
`active/programAttempted`均未置位；ASan/UBSan与ARM64通过。Display全文ARM64对象
269896字节，最大函数栈784字节。11组实际诊断准入/生命周期/IRQ隔离回归通过，新增
普通HaltResume、只读成功、只读失败但仍恢复并释放资源三种情形。消费者9成功/7失败，
已有21个错误IRQ/配置声明拒绝仍通过。

复用GPU201助手/启动包，保留Hall/120Hz/trace0。下一步完整CI、64对象链接/加载器、
新日志槽和临时启动；先Snapshot，再只读HaltResume并取得用户画面反馈。正常画面确认
之前不进行真正的ActivateGopPolled，后续仍不在画面异常时ResumeIrq/FlipGop。

当前Android/USB在线，Data182；GPU204日志已回收清空读回。目标active，GPU205未部署。

## GPU205 实机结果

提交e44559a，完整CI42963052903、64对象链接/分支/加载器通过，部署读回并临时启动。
用户确认桌面与触摸正常，GPU ready/Snapshot通过。只请求DpuHaltResume只读对照，
请求ID `f6e5d9f5bc9a47589dda2a524ef77dde`，没有请求真正的页表接管、ResumeIrq或FlipGop。

持久化日志确认只读状态0、audit2042027µs、SCTLR0xe0，halt13µs、resume8945µs，
恢复状态0；新IRQ/双vsync各13、无新增underrun，最终status0/programmed0/frozen0。
用户仍确认背光亮但纯黑，AFC及独立IORegistry读取超时。这证明翻译启用不是这种黑屏的
必要条件，但尚未区分单纯长暂停与暂停期间读取的作用。后续优先消除长暂停窗口。

完整64MiB槽及3,303,236字节有效连续前缀已保存至
`log/device/nabu-boot-20261111-205/runtime-log/`。运行流未正常封口；清槽读回通过，
引导分区未变，Data183，设备Android/USB在线。目标active。
