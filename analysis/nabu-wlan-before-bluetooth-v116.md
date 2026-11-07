# 第116轮：共享供电独立，WLAN先于蓝牙固件启动

第115轮补XO后仍同PC首次PFR。原机Android在约12.5秒报告WLAN ready，bt_power
probe约20.7秒；当前Nabu历轮先运行BT ROM关/开脉冲、下载patch/NVM，再启动modem。
原生bluetoothd Reset发生在首次PFR之后，不能解释它；早期BT固件的顺序影响未排除。

将四路共享LDO开启移到独立nabu_wireless_power_on，仍采用752/1800/1304/3312mV、
HPM7/enable1、原有10ms等待。对于level4/5，供电成功后先运行modem/WLAN启动，
随后才配置BT UART、发ROM脉冲和下载BT固件。level2/3保留蓝牙单独路径，level1
不启动无线。供电失败时两者均不开始，但仍发布已有错误报告。

这是一项有原机时序依据的对照，尚不能认定它解决故障。当前GLINK仍有原试验
窗口；如果首次PFR消失并收到ready，立即继续常驻生命周期和实际数据面接入。
未开启虚假网络接口，未通过缺失DMA资源强发WLAN_MODE。

生产启动函数回放及既有蓝牙原生传输ASan/UBSan通过。旧蓝牙测试缺少IOLog桩的
编译问题同步补齐，只代表测试桩修正，未改HCI回复或蓝牙传输。另将独立WLAN_CFG、
WCN399x CE ring代码及源协议fixture加入CI回放；它们尚未在v116生产路径激活。

验收：供电先于modem、WLAN首个PFR/FW_READY/INIT_DONE结果先于任何BT ROM脉冲；
之后蓝牙transport和原生初始化正常，桌面USB无回归。完整CI后才部署。

## 第116轮完整回收与第117轮接线

第116轮594bb860的完整CI42385432816通过后临时启动，桌面和USB正常。首次PFR
仍为PC=b019b9bc，发生在30.111秒、任何蓝牙ROM脉冲之前；没有FW_READY/INIT_DONE。
这排除了BT先启动是当前首个PFR必要条件。蓝牙后续发布UART服务，原生2005/200b/
200c最终status0；一次重复200b返回12随后正常，保留真实记录。64MiB原始槽和
2,485,091字节连续日志已备份，清空回读通过；未封口，APFS85→86、fullfsync成功。
设备已回Android，蓝牙关闭。证据log/host/wireless-v116/result-summary.json。
