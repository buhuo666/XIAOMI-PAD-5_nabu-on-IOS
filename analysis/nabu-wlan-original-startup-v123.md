# v122实机SMMU成功与v123原机WLFW顺序对照

日期：2026-11-08，Asia/Shanghai。

## v122确认结果

源码3a41240、完整CI 42397178490全部通过。用户确认桌面和USB正常；回收
无线、蓝牙报告后返回Android，蓝牙读回0。2,944,627字节有效日志和64MiB
完整槽已备份并清空。缺少最终提交头，complete=false；boot分区未改变，
APFS计数91→92、fullfsync=ok。

WLAN流槽6/7的标准FAULT写入读回仍为0x200ff，替代TYPE编码后均为0x20000，
qcom-encoding=1。bank54、ASID55、6页4KiB页表及0x640/0x641精确流映射
实际接入成功，host resources ready=1，PAS命令5返回成功。

后续WLFW完成MSA授权、CAP、feature、BDF的26,328字节、CAL和MAC请求，
仍发生wlan_process PFR，PC=0xb019b9bc。FW_READY=0、INIT_DONE=0，实例
失效后CE未启动，HTC/WMI收发为0。由此确认内存/SMMU阻塞已越过，但没有
解决原固件异常，也没有Wi-Fi扫描、连接或数据面成功证据。
蓝牙原生UART服务和HCI成功回执保留；软件报告仍无wifid job和Wi-Fi接口。

## v123单变量对照

直接核对已保存的原机vendor源码
`log/host/wireless-v76/source/vendor/drivers/soc/qcom/icnss.c`，
icnss_driver_event_server_arrive第958行起的顺序为：
供电→KNEL IND_REGISTER→MSA_INFO→实际授权→MSA_READY→CAP→dynamic feature。
当前Nabu在IND_REGISTER和MSA_INFO之间多发送0x34 HOST_CAP；该额外请求
不是本段原机路径的一部分。此前保存的二进制分析可见
`analysis/nabu-wlan-host-cap-review-v117.md`，本次代码改动以原机源码顺序
和v122实际请求日志作为直接对照依据。

本轮只取消该HOST_CAP请求及其特有的错误94例外处理，成功注册直接进入
原step2 MSA_INFO。保留后续历史step编号，避免改变GLINK的MSA授权、
CAL诊断窗口等调用条件；transaction按真实发送次数计数，因此整体减少1。
SMMU、供电、BDF/CAL/MAC内容、KNEL/DMON端口及服务失效策略均沿用v122。
这是待实机验证的初始化对照，不是已证实的固件PFR修复。

## 验证

旧代码对原机顺序断言失败；修改后WLFW及生产GLINK/QRTR ASan/UBSan通过。
GLINK新回放从真实queue发送KNEL注册，实际接收回复后紧接MSA_INFO事务2；
等待时拒绝迟到HOST_CAP回复，MSA回复后仅一次实际授权调用，随后发送
MSA_READY事务3及CAP事务4。BDF分片、官方CAL字节、MAC、真实ready门控、
失效及迟到回复测试保持通过。
证据：`log/host/wireless-v123/{wlfw-before-fix,wlfw-test,glink-test}`。
arm64构建、完整CI与下一轮实机结果另记。

## v123实机结果与回收

源码2b17b8d，完整CI 42398403753两个job均成功后临时启动。用户确认桌面和
USB正常。真实请求已按KNEL注册直接进入MSA，没有发送额外HOST_CAP；SMMU
仍成功接入bank54/ASID55、slots6/7，128个DMA块全部位于4GiB以上。
PAS启动及BDF/CAL/MAC请求成功，但45.132167秒仍报告
`EX:wlan_process:0x1:WLAN RT:0x14b:PC=0xb019b9bc`。
FW_READY和INIT_DONE均为0，CE、HTC/WMI未启动，Wi-Fi尚不能扫描或连接。
因此取消额外HOST_CAP没有解决原固件异常，不能据此继续猜测BDF或电源改动。

76.971430秒PAS命令6成功，随后DMA清理返回false而旧status仍为0，资源被
保留。该日志没有指出失败寄存器；v124单独修复离线已证明的清理读回不一致，
并记录失败阶段、偏移、期望值和实际值。清理问题发生在首个PFR之后，不能
将其当作这次首次固件异常的解释。

蓝牙UART服务和0x2005/0x200b/0x200c成功响应保留，0x200b的一次status12及
后续成功均按原始日志记录。本轮耳机留盒，没有新增耳机配对/回连操作验收。
软件清单仍无wifid job、IO80211/IONetwork接口，BSD只有lo0/utun。

用户返回Android且蓝牙关闭后，回收2,910,094字节连续日志及完整64MiB原始槽，
清空回读成功，boot分区未改变。日志缺少最终提交头，complete=false；APFS
计数92→93、fullfsync成功。611在PFR、重启、结束三个阶段均为4096字节全零，
TFTP没有新增转储请求，仍未取得BADVA/LR或完整异常上下文。
证据：`log/host/wireless-v123/result-summary.json`及
`log/device/nabu-boot-20261108-123/runtime-log/runtime.log`。
