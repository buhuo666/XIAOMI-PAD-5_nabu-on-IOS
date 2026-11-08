# 第135轮候选：真实RSSI通知与状态栏信号观测

第134轮已通过原生WPA2关联、IPv4、网页访问/下载、手动重连。用户补充顶部Wi-Fi图标为灰色且零格；自动重连未通过。测速下载期间的高Ping不能归因于蓝牙，相关假设已撤销。当前设备Android、蓝牙关闭、USB连接，APFS104。

20F66原件合同见log/host/wireless-v135/signal-contract/REPORT.md：GET16的52B布局与现有实现一致；SpringBoard使用MobileWiFi的ScaledRSSI以及RSSI字典的RSSI_CTL_AGR，关联时采用clamp(ceil(3*scaledRSSI),1,3)，未关联时0。因此灰色零格不能仅解释为RSSI弱；缺少持续通知也不能单独证明初值关联状态正确。NOISE17和RSSI_BOUNDS106不参与该scaled公式，不伪造噪声或范围数值。

补齐原生APPLE80211_M_RSSI_CHANGED事件39：payload180字节，仅+0 RSSI有效、+4真实i32 dBm，其余指标未置有效。runtime每1000次poll采样一次；原生层先抓实例/连接代次和读者寿命，在锁外读取backend state，再串行校验仍JOINED、目标/实际电源、无取消、同连接后发布。off/leave/lost/fatal/newjoin/detach跨采样不会发旧信号；不以重复LINK事件代替信号变化。

只读WirelessNativeSignal收集GET16/17/106原始返回和错误，再通过原件验证的MobileWiFi API记录currentNetwork是否存在、ScaledRSSI和RSSI_CTL_AGR/RSSI_UNIT。只记录连接布尔值与信号数值，不复制网络身份或凭据。下一轮以用户观察和两层状态确认，尚未实机验收。

重连复核见log/host/wireless-v135/reconnect-review.md：331.353秒开电后15次扫描及SCAN_DONE成功，目标AP出现，但逐请求日志304.659秒已达800条上限；不能断言wifid未发ASSOCIATE。下轮让SET19/20/22结果继续记录，不擅自改变内核standing策略。

主机实际源码：station37项（新增11个信号取消/寿命用例）ASan/UBSan和严格编译通过；adapter与event39实际编码测试通过；runtime5项通过；修改的arm64 runtime对象编译通过。完整CI、部署与图标验收结果待后续记录。


## 第135轮结果：信号格修复已验收（2026-11-08）

源码bec9c699153d5c4ec863a93c9a1a25365e15ecb1，完整CI42449579323及probe CI42449579312全通过。桌面正常。用户手选WPA2网络后确认顶部信号格正常、网页正常；关闭Wi-Fi再开启仍需手选，之后信号格及网页再次确认正常。底层读回RSSI=-42dBm，en0仍取得192.168.137.104。日志首次RSSI event39于93.749秒出现，前16条实际值-45..-41dBm；没有用固定满格或伪造噪声/范围。

关联分别于92.943、336.529秒成功；poweroff266.541、poweron281.367秒成功。SET19/20/22日志已取消旧800条上限，本轮poweron到用户手选前没有ASSOCIATE请求；继续核对wifid自动加入条件，不先改内核自动连接策略。

诊断MobileWiFi manager可创建但CopyDevices为NULL：原件确认客户端/服务端要求com.apple.wifi.manager-access Boolean true，而此probe缺少，不能用该诊断空列表解释SpringBoard。其补权修改尚未部署。用户UI结果与原生RSSI日志足以确认本轮图标修复；尚未测试实际远近变化与各档信号阈值。

蓝牙清单正常返回；本轮蓝牙处于关闭，HCI Reset及deepsleep/idle生命周期成功、共享资源保留，没有原版Stack initialization complete日志，不能沿用上一轮当作本轮开栈验收。

设备已回Android、蓝牙关闭、USB连接。6,086,093字节连续日志及完整64MiB槽已备份清空，无终止记录；APFS104→105、fullfsync成功。证据见log/host/wireless-v135/result-summary.json及log/device/nabu-boot-20261108-135/runtime-log。
