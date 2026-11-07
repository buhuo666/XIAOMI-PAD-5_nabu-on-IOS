# v117 WLAN DMA平台审查

## 已修复的实机阻塞

NabuWlanDma.cpp复用USB的0xd0000局部SMMU窗口，但ArmSmmu4KProgram.c的
prepare要求完整2*global_pages*4096窗口。真实Nabu旧实测usb-v41/usb-events.txt:9
及usb-v42/live/usb-events.txt:9报告global pages=128、numcb=56，故要求0x100000。
原机FDT /soc/apps-smmu@0x15000000的reg也明确0x15000000+0x100000。
旧窗口必然导致ArmSmmu4KUnsupported，不能建立WLAN DMA context。

已仅将WLAN native mapping和ArmSmmu4KIo.register_bytes改为0x100000；USB定义不变。
check_nabu_wlan_dma.py由虚构pages64改为真实pages128/numcb56，全部context偏移
随之修正，并新增旧窗口在任何context写入前被拒绝的回归。最终ASan/UBSan通过：
log/host/wireless-v117/dma-review-test/report.json。尚非实机验证。

## 已核对的其它接口

- NabuWlanFault的global IRQ97及context IRQ表逐项对应原机FDT interrupts的SPI
  number+32；原机flags4为level-high，调用attach(edge=false)正确。不能以单一
  连续base代替其分段编号。
- qcom,actlr六项与原机FDT一致，0x640/0x641不匹配其中任何范围；没有依据
  给WLAN复制GPU/其它master的ACTLR值。
- 实际gic_v3_spi_attach按INTID排他登记、设定Group1/route/level并unmask；
  gic_v3_spi_detach先mask、移除slot，然后等待busy handler完成，满足fault
  对象remove要求。此为真实内核入口，不是测试stub。
- DMA tables以dc civac/DSB发布；页表映射32-bit IOVA到36-bit PA并采用4KiB页。
  runtime packet cache维护仍须由收发实现配对执行，本审查不替代数据面回放。
- lost只撤销资格而不释放；release_after_stop先fault所租streams，再按实际
  owned context检查关闭并TLBSYNC，成功后恢复原slot并释放。同步/状态不明时
  留存，不会因PFR直接释放正在被硬件引用的页表。
- 尚未证明实际空闲context/全局sCR0与ACTLR满足前置条件；失败会拒绝attach。
  需要实机记录具体选bank、status和故障。这是待测条件，不能提前报告DMA工作。

本次只修改父线程授权的NabuWlanDma.cpp和DMA测试；没有改固定ArmSmmu4K、
故障/控制器实现、生产boot流程，也没有操作设备。
