# v124 WLAN 停止清理读回修正与失败定位

日期：2026-11-08，Asia/Shanghai。

## 实机边界

v123 源码 2b17b8d 在 PAS command=6 成功后记录：
`NABU WLAN DMA: stop cleanup incomplete; bank/tables/buffers retained status=0`。
这只能证明本地清理布尔检查失败；旧日志没有阶段、寄存器偏移或读回值，
不能把本次找到的 TCR2 不一致直接认定为该次实机失败原因。
固件 PFR 仍在 0xb019b9bc；本修改不处理其原因，也不改变 WLFW 请求顺序。

## 已证明的问题

`src/ArmSmmu4K-nabu/ArmSmmu4KContext.c` 的
`ArmSmmu4KValidateContextReadback` 明确允许 TCR2.TBI0/TBI1（0x60）
写 0 读 1。`ArmSmmu4KDisableOwnedContext` 使用同一验证规则确认上下文归属，
再验证 SCTLR=0 并完成 ASID 失效与 TLBSYNC，成功后才清除 must_retain_tables。

原 `NabuWlanDma::release_after_stop` 随后将 TCR2 清零并要求严格读回 0，
因此同一个库认可的上下文可以成功接入、停止、同步，却在最后清理时永久
保留全部内存。离线 MMIO peer 持续令 TCR2 的 0x60 位读为 1，同时模拟
实机 Qualcomm FAULT 编码和原 S2CR=0x200ff、ACTLR=3，旧代码在
`release_after_stop` 成功断言处失败，记录位于
`log/host/wireless-v124/dma-cleanup-before-fix/test.stderr`。

原机 vendor 代码的 `arm_smmu_destroy_domain_context`
（`log/host/wifi-recheck-v114/smmu-source/arm-smmu.c`）仅停 SCTLR 后释放
页表，没有要求 TCR2/MAIR 等配置全零。本次仍保留现有清零流程，只让 TCR2
接受库已有的 0x60 读回例外；其他非零位继续拒绝。未修改固定版本 SMMU 库。

## 变更

- 停止流程保留 PAS 已停止这一调用前提、流槽归属检查、完整上下文归属
  检查、SCTLR 停用读回与 TLB 同步条件。
- FAULT 和恢复流槽操作记录实际读回；内存释放仍要求完整清理成功。
- 每次清理重置本次状态与读错误标记。读、写或屏障失败报告 IoError；
  本地读回不符报告 StateMismatch，避免失败仍显示 status=0。
- 失败日志增加 phase、offset、expected、actual、readback、bank，以及
  SMMU 库的 program-phase、disabled、tlb-sync、retain。
  readback=0 表示本地值未成功读取，不应把 actual=0 当作硬件读回。

阶段编号：1=归属检查，2=流槽 FAULT，3=库验证/停用/TLB 同步，
4=恢复流槽，5=清空上下文配置，6=恢复 ACTLR，7=全部完成。
阶段 3 由库管理寄存器，offset=0 且 readback=0；应结合 status 与
program-phase/disabled/tlb-sync/retain 判断。其他阶段记录首个失败位置。

## 验证

`python tools/check_nabu_wlan_dma.py --output log/host/wireless-v124/dma-cleanup-test`
经 WSL clang-18 完成 ASan/UBSan，退出 0。保留的原有场景仍通过：高于 4GiB
的真实分配回调、2048 页翻译、USB/UFS 流隔离、ACTLR 初始化/恢复、Qualcomm
流槽编码、PFR 后保留、TLB 超时后可重试。

新增直接验证：

- 合法 TCR2 0x60 读回与 Qualcomm 编码组合可完整清理，ACTLR 恢复为 3，
  两个流槽恢复原始值，129 个分配全部释放。
- 清零时出现额外 TCR2 0x80 位仍失败并保留内存；日志定位阶段 5 及实际值。
- 流槽被外部改写时不进行任何清理写入；上下文根被改写时不停用该上下文。
- FAULT 写被忽略、SCTLR 停用被忽略和 TLB 超时均拒绝释放，并记录失败阶段。
- 归属读取失败报告 IoError/readback=0；ACTLR 恢复写失败报告阶段 6、
  IoError/readback=0，已分配内存继续保留。

测试故障清理采用恢复模拟寄存器映像后释放测试内存，未增加生产代码的
部分清理后重试机制。实机需要 v124 新日志才能判定 v123 的真实失败点。
arm64 对象构建、内核链接及 return-trace 检查已通过，输出位于
`artifacts/nabu-wireless-trace-v124`。完整 CI 与实机验证尚未完成。
