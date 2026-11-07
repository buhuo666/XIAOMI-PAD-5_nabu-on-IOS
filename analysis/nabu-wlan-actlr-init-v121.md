# v120实机结果与v121 ACTLR初始化

日期：2026-11-08，Asia/Shanghai。

## v120证据

源码12c3432，完整CI 42393900862全部通过。用户确认桌面/USB正常；无线和
蓝牙报告读取成功。回Android后回收3,269,767字节日志，64MiB槽完整备份后
清空，boot分区未改变。日志缺少最终提交头，complete=false。APFS计数89→90，
fullfsync=ok，Android蓝牙读回0。

DMA仍成功分配128个高PA块和6页页表，CE资源准备完成；SMMU选择stage=4，
free-slots=2、used-banks=3、blocked-banks=52。首个拒绝bank54的offset
0xb6004为ACTLR，读回3。v120已越过SCTLR非零但M=0的检查，现停在ACTLR
必须预先为0的要求；尚未接入SMMU、尚未发送PAS启动。蓝牙固件初始化及
原生UART节点保持，HCI回执保存在result-summary.json。

## 源码依据

保留的原机vendor `log/host/wifi-recheck-v114/smmu-source/arm-smmu.c`：

- 第4862行以devm_kcalloc分配context bank软件记录，actlr默认0。
- qsmmuv500_init_cb第5877行起，仅在SID匹配qcom,actlr表时覆盖该值。
  原机FDT的六项均不匹配WLAN SID 0x640/0x641。
- arm_smmu_write_context_bank第1991行无条件写cb->actlr到实际ACTLR。

因此没有匹配配置不意味着要求硬件预先为0，而是初始化时应写0。v121只
补上当前已观察到的初始值3到WLAN配置0的过程，仍不选择其他未知ACTLR值。

## 实现

持有共享SMMU配置锁，选择无stream引用、SCTLR.M=0且ACTLR为0或3的bank。
记录原值，写WLAN ACTLR=0并屏障、实际读回。随后原故障IRQ registrar仍
独立核对ACTLR=0，再进入原stream fault、上下文编程与stream接入流程。

ACTLR读回失败或IRQ注册失败时，恢复原ACTLR并验证；未恢复成功则保持
Retained及内存所有权。另记录context_started，区分仅修改ACTLR与已编程
上下文，确认停止后的清理不会拿尚未初始化的program.context_offset访问
全局寄存器。正常停止须先关闭已编程上下文并完成TLB同步，再恢复原ACTLR。
运行时observe也核对ACTLR；外部变化使实例失效并保留资源。

增加attach各阶段及program读回诊断，使ACTLR、IRQ、stream检查、上下文
编程及stream接入失败可以在同一份报告中定位。

## 验证

以实测ACTLR=3更新旧回放，旧代码在attach断言失败。修复后ASan/UBSan通过：
高PA映射、非零禁用上下文、ACTLR=3→0、正常停止恢复3、忽略写入时拒绝、
IRQ失败恢复、恢复失败保留并在确认停止后恢复、TLB超时保留、USB/UFS隔离。
生产fault registrar未放宽ACTLR验证。结果在`log/host/wireless-v121/dma-test`。
arm64编译、完整CI和实机结果另记；未宣称SMMU或Wi-Fi已工作。
