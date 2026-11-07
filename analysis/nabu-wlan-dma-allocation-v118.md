# v117实机归档与v118连续内存分配修复

日期：2026-11-08，Asia/Shanghai。

## v117实机证据

用户确认桌面/USB正常，随后恢复Android；ADB确认bluetooth_on=0。
`log/device/nabu-boot-20261107-117/runtime-log`回收4,370,277字节日志，
64MiB原始槽完整备份后清空并读回确认。追加日志缺少最终提交头，
`complete=false`，不将已回收内容描述为正常关机的完整日志。
APFS启动计数86→87，fullfsync=ok。

`runtime.log:3178`起的内核错误明确为
`vm_page_find_contiguous(num=4,low=262143): found 0 pages`，随后才出现
`NABU WLAN DMA: allocation/table preparation failed`。16KiB内核页下，
262143为0xffffffff右移14位；这对应64KiB分配被限制在4GiB以下。
WLAN资源未准备好，因此没有发送PAS启动，不能据此判断旧固件PFR已解决。

蓝牙仍发布原生UART IOService；HCI 0x2005/0x200b/0x200c包含status=0回执，
并保留一次0x200b status=12与其后成功重试。没有新的耳机连接/音频验收。
WirelessInventory的软件字段确认两处wifid job不存在，IO80211Controller、
IO80211Interface、IONetworkInterface匹配数均为0，BSD只有lo0和utun。
详细结果在`log/host/wireless-v117/result-summary.json`及`software-summary.json`。

## 分配API原因与修复

当前内核源码`build/xnu8796-capacity/tree/iokit/Kernel/IOLib.cpp`的
IOMallocContiguous在physicalAddress非空时构造
`physicalMask = (0xFFFFFFFF ^ alignMask)`，经IOBufferMemoryDescriptor
向kmem_alloc_contig传递32位物理上限。64KiB超过16KiB页，确实进入
连续分配分支；旧回放只测试自造分配器，未覆盖生产native callback。

NabuWlanDma改用`IOMallocContiguous(bytes,16384,nullptr)`，取得实际wired
连续分配后用`ml_vtophys`取得物理地址。该入口已被现有USB驱动使用；
配对释放仍为IOFreeContiguous。WLAN的32位IOVA通过既有36位输出SMMU页表
映射到高物理地址，不要求物理地址本身小于4GiB。

补充真实分配块数量、高地址块数、首末PA和页表PA日志；失败分别记录
block allocation、table allocation、table build及ArmSmmu4K状态，
释放未暴露给硬件的内存后仍保留失败位置供报告。未改变固件请求顺序。

## 验证

`check_nabu_wlan_dma.py`直接提取生产allocate/release callback，使用
符合上述XNU分支的分配peer：请求physicalAddress时低地址分配失败，
不要求低地址时返回4GiB以上连续页。旧代码在prepare断言失败；修复后
验证128块及页表、全部2048个4KiB翻译、清零、分配失败回收通过。
另覆盖页表分配失败与构表失败的错误分类；原有SMMU租用、USB/UFS隔离、
PFR保留及PAS停止后释放测试继续通过。

DMA及CE/HTC运行时回放均通过ASan/UBSan，路径：
`log/host/wireless-v118/dma-test`、`runtime-test`。
此记录不代表实机DMA、FW_READY、HTC/WMI或网络扫描连接已成功；
arm64构建、完整CI及v118实机结果另行追加。

## v118构建、CI与部署

修复提交`51860319d07b08c7cf1a5a9bfbf2e658d637f36b`已通过本地代理推送。
arm64内核对象编译、内核链接和return-trace检查通过；完整CI
`42391045367`同一提交的全部job成功，无线协议ASan/UBSan及完整内核
编译/导出接口/容量/存储/显示检查均通过。

2026-11-08部署记录为`log/device/nabu-chain-20261108-002928/deployment.json`，
状态deployed-and-readback-verified。沿用bootstrap-recheck-v114的蓝牙和
软件探针；临时启动记录在`log/device/nabu-boot-20261108-118`，fastboot boot
返回成功。当前等待用户确认桌面与USB，尚未采集v118无线实机报告；
本记录不把启动命令成功当作桌面、DMA或Wi-Fi成功。
