# v118实机结果与v119 SMMU拒绝位置诊断

日期：2026-11-08，Asia/Shanghai。

## v118确认的进展

源码5186031，完整CI 42391045367成功。用户确认桌面和USB正常，随后返回
Android且bluetooth_on=0。回收3,390,938字节日志；64MiB槽完整备份后清空，
boot分区读回未改变，APFS计数87→88、fullfsync=ok。追加日志缺少最终提交头，
仍为complete=false。证据目录：`log/device/nabu-boot-20261108-118/runtime-log`。

真实日志确认128个64KiB DMA块均在4GiB以上，首块PA=0x1a8f4c000，
末块PA=0x1ab3c0000，页表PA=0x1ab40c000、6页；12个CE ring和4852个buffer
资源准备完成。第117轮低物理地址连续分配失败已在实机上越过。

随后native attachment失败，state=Prepared、status=0、bank=0。
由代码路径可知尚未选择出有效bank，未进入ArmSmmu4K编程/stream接入，
也未发送PAS启动；仍不能评价原来的固件PFR或Wi-Fi扫描连接。
蓝牙UART服务、HCI 0x2005/0x200b/0x200c成功回执保留，同时记录一次
0x200b status=12及后续重试。软件层仍没有Wi-Fi网络接口。

## v119诊断改动

原select()多个提前返回均留下status=0，缺少精确原因。新增SelectionTrace
记录阶段（1识别、2全局控制、3stream扫描、4bank扫描、5选择完成）、
实际ID/sCR0/GFSR、空闲slot数、被使用/非零/ASID冲突bank数。
冲突stream记录实际slot/SMR/S2CR；非零bank记录首个拒绝bank及offset/value。
对应失败状态区分Unsupported、IoError、Fault、StateMismatch、Busy。

bank寄存器检查顺序及条件保持原样，仍在第一个非零值停止检查该bank，
不清除现有配置，不复用被引用的bank，也不写共享全局控制。
native runtime在失败时发布上述信息，以便下一轮依据实测值修正实际阻塞。

## 本地验证

DMA ASan/UBSan回放通过。新增断言覆盖全局控制不匹配、已有WLAN stream、
全部候选bank非零，检查具体诊断值、零MMIO写入及未安装IRQ；原有高PA
分配/页表翻译、正常attach、PFR保留、停止后释放及USB/UFS隔离继续通过。
日志：`log/host/wireless-v119/dma-test`。arm64构建、完整CI和实机结果另记。
