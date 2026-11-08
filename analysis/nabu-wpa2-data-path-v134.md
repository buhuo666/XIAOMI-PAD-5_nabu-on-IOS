# 第134轮候选：WPA2关联与数据接口

第133轮已回收，APFS103，设备Android、蓝牙关闭、USB连接。尚未构建/部署第134轮镜像，以下是实现和主机验证，不能算实机联网成功。

- 保留同一个en0，native WPA2 join经过真实backend认证/关联/密钥完成、JOINED状态和native连接代次提交后才发布BSD link。off、leave、重关联、普通失联、fatal撤销旧资格。接受off后锁存实际关闭，不能被紧随的on吞掉。
- 256项动态分配TX队列复制mbuf，固定worker直达nabu_ath10k_driver_transmit；排队成功与backend返回/错误分别记录，不等于空口完成。off/leave/rejoin/withdraw清队列并等待active TX后才进raw控制；普通loss/fatal立即关准入，fatal不在GLINK/恢复回调等清退。RX仅在committed关联时复制到legacy ifnet异步输入。
- connection_loss接到普通失联；group-rekey失败保留EIO但不视为firmware fatal；restart_hw异步请求runtime清退。PSK请求在PSK+SAE混合AP上保持PSK，不擅自升级。
- 20F66 CARD_CAPABILITIES只置bit3(CCMP)、bit14(RSN)。读取完整592字节ASSOCIATE，version/key_version1、mode2、auth_lower1、auth_upper8，接受cipher6/32字节PMK或cipher10/8..63字节口令；所选RSN必须为CCMP/PSK且不协商PMF。其他模式同步拒绝，不把开放/企业/FT/SAE降级成PSK。原版普通口令也会派生PMK，已改正原注释。证据：log/host/wireless-v134/security-contract/REPORT.md。
- probe新增实时DT/IOService defaults属性以及BSD IP地址，用于区分尚未解释的busy节点与接口联网结果。

主机：实际adapter源码ASan/UBSan覆盖mbuf复制、容量/错误、旧包清除、active TX与off/rejoin/fatal交错、普通失联及晚到join；runtime原有5项通过；station实际源码26项通过；修改的arm64内核对象本地编译通过。安全parser实际源码770项、backend SAE开/关87项测试通过；完整CI结果另记。

后续实机需由用户在设置输入凭据，分别验收握手、DHCP、IP、双向流量；同时保留原生蓝牙初始化基线。未验证耳机/音频，未宣称互联网已可用。
