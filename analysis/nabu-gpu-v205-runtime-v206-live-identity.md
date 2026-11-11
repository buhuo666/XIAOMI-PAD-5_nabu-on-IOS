# GPU206：旁路下预置，切入原GOP恒等映射

2026-11-11，Asia/Shanghai。GPU205未编程SMMU也复现黑屏，2.04秒只读暂停的完整证据
见`nabu-gpu-v204-runtime-v205-halted-audit.md`。目标active。

## 新路径与依据

Arm IHI0062D.a §2.4（PDF60页）规定M=0时不使用Stage1页表；§16.5.29（312页）规定
M位不可缓存于TLB，完成使能写入后到达的事务使用新值，跨越该写入的事务可以使用旧或
新值。本地规范为`log/host/gpu-v202/smmu2-da-spec.pdf`。

本轮通过`nabu-dpu-live-identity=1`选择GOP专用路径，保留原停取数实现供对照。
资格限定继承SCTLR0xe0、CBAR0x1f000、CBA2R1，原GOP地址与拓扑不变，所有4000页
都映射回同一物理页、表池已发布到PoC、ASID无冲突、全部路由读回一致。GOP写入门冻结，
显示IRQ保持屏蔽。

先在M=0保持旁路时写CBA2R/CBAR/TCR/TTBR/MAIR/ACTLR，校验整套暂存值与SCTLR0xe0，
完成实际TLBI/TLBSYNC及路由复查。最后一次写SCTLR启用已完成的恒等映射，并检查上下文、
FSR/GFSR和全路由。两种地址转换状态都指向永久GOP物理页，不改变源地址，也不写VBIF
HALT或DPU寄存器。CBAR只取Stage2旁路的最弱属性；新的GOP叶仍Normal NC。

返回后沿用双计数、GOP样本、独立IRQ恢复与翻帧准入。报告明确identity_live_requested，
总执行时间与零XIN暂停时间分别记录，不为未执行的11阶段旧路径伪造时间。若新路径在
实际改写上下文后失败，保留冻结与映射，不因没有DPU地址写入就误判为未发生硬件变更。

## 本地验证

- Display全文ARM64编译通过；Mapper实际代码ASan/UBSan与ARM64通过。
- 实际TLBI写回调检查：此时SCTLR必须仍为0xe0，TTBR/TCR/MAIR和全部4000页已就绪、
  原表页已发布；最终M=1且完整快照通过。缺失GOP页在所有寄存器写入前被拒绝。
- 同一模型的DPU/VBIF写接口直接失败，新的实际Mapper调用仍成功，证明该路径没有这些写入。
- 13组实际诊断/接管回归通过，包括新路径成功及MMIO已发生的失败冻结；消费者10成功/
  8失败及28个错误IRQ/配置声明拒绝通过。
- 19组实际翻帧/返回GOP/生命周期回归通过，检查73,728,000个原始像素。

复用GPU201助手/启动包，去除GPU205的halt-audit=1，保留Hall/120Hz/trace0。仍需完整
云端编译、链接/加载器、部署读回及实机视觉验收。上机先普通Snapshot/HaltResume，再
ActivateGopPolled；只有画面正常才ResumeIrq/FlipGop。尚无本轮实机通过结论。
