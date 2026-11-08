# 第134轮候选：WPA2关联与数据接口

第133轮已回收，APFS103，设备Android、蓝牙关闭、USB连接。以下为构建前的实现记录；本轮已完成部署与联网实测，结果见文末。

- 保留同一个en0，native WPA2 join经过真实backend认证/关联/密钥完成、JOINED状态和native连接代次提交后才发布BSD link。off、leave、重关联、普通失联、fatal撤销旧资格。接受off后锁存实际关闭，不能被紧随的on吞掉。
- 256项动态分配TX队列复制mbuf，固定worker直达nabu_ath10k_driver_transmit；排队成功与backend返回/错误分别记录，不等于空口完成。off/leave/rejoin/withdraw清队列并等待active TX后才进raw控制；普通loss/fatal立即关准入，fatal不在GLINK/恢复回调等清退。RX仅在committed关联时复制到legacy ifnet异步输入。
- connection_loss接到普通失联；group-rekey失败保留EIO但不视为firmware fatal；restart_hw异步请求runtime清退。PSK请求在PSK+SAE混合AP上保持PSK，不擅自升级。
- 20F66 CARD_CAPABILITIES只置bit3(CCMP)、bit14(RSN)。读取完整592字节ASSOCIATE，version/key_version1、mode2、auth_lower1、auth_upper8，接受cipher6/32字节PMK或cipher10/8..63字节口令；所选RSN必须为CCMP/PSK且不协商PMF。其他模式同步拒绝，不把开放/企业/FT/SAE降级成PSK。原版普通口令也会派生PMK，已改正原注释。证据：log/host/wireless-v134/security-contract/REPORT.md。
- probe新增实时DT/IOService defaults属性以及BSD IP地址，用于区分尚未解释的busy节点与接口联网结果。

主机：实际adapter源码ASan/UBSan覆盖mbuf复制、容量/错误、旧包清除、active TX与off/rejoin/fatal交错、普通失联及晚到join；runtime原有5项通过；station实际源码26项通过；修改的arm64内核对象本地编译通过。安全parser实际源码770项、backend SAE开/关87项测试通过；完整CI结果另记。

后续实机需由用户在设置输入凭据，分别验收握手、DHCP、IP、双向流量；同时保留原生蓝牙初始化基线。未验证耳机/音频，未宣称互联网已可用。


## 第134轮：原生WPA2联网通过（2026-11-08）

源码4d5bf5906e739712b1dffb4e7bf949f8358cec19，完整CI42446906692和probe CI42446906693全部通过。临时启动后用户确认桌面正常；设置选择WPA2网络后出现对勾，Safari新网页及刷新正常。122.140秒真实join返回0、JOINED；en0取得192.168.137.104；主机4次Ping全部成功。首次原版ASSOCIATE实际为592字节、auth1/8、cipher6和32字节PMK，符合原件合同。

313.468秒poweroff成功、331.353秒poweron成功；用户反馈需重新选择网络，365.607秒第二次join成功，网页恢复。自动重连未通过，先核对wifid是否发起请求，不自行增加内核自动连接策略。蓝牙开关可操作，开启后用户确认网页仍正常，bluetoothd原版栈初始化完成；未验证蓝牙配对或音频。

用户补充蓝牙开启时正进行浏览器测速下载，因此285–486ms的那组Ping受不同流量负载干扰，撤销蓝牙共存故障假设；关闭蓝牙后的8次Ping为1–2ms，只记录条件和结果。553.412秒接口累计发送187473帧/19429284B、接收420816帧/619760495B，丢弃2出/0入；不能把这些累计数当作吞吐基准或全部空口完成。

用户新报告状态栏有Wi-Fi图标但信号强度显示不正确。GET106 RSSI_BOUNDS的16字节请求和GET17 NOISE的52字节请求被拒，GET16 RSSI合同及原版信号格计算正在核对，尚未确定修复。实时DT和IOService的defaults都含AAPL,ignore=1、sleep-disabled=1、compressor=2，busy节点依然存在；InterfaceNamer COMPLETE正常快速发布，原因仍未解。

已回Android、蓝牙关闭、USB连接。7,294,588字节连续日志和完整64MiB槽已备份清空；无终止记录，不称为正常关机封口。APFS103→104、fullfsync成功。证据：log/host/wireless-v134/result-summary.json及log/device/nabu-boot-20261108-134/runtime-log。尚未部署第135轮。
