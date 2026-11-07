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
