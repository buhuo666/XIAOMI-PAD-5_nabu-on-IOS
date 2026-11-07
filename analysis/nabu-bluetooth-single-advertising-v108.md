# 第108轮：原生单广告偏好与运行后参数采集

2026-11-07，Asia/Shanghai。

第107轮桌面及USB正常，原生200b载荷为`00e00130000100`，Own_Address_Type=1；
200c载荷`0101`合法，但真实响应0x12。首个完整原生Reset区间未发送2005，
厂商fd48创建多广告实例返回1。依据固定20F66原版路径，该失败跳过后续标准随机
地址提交，能解释扫描启动失败；设置候选仍需实际2005/200c响应验证。

完整64MiB槽已备份清空回读，恢复10,508,786字节连续日志，未有最终提交头，
不标为完整封口。APFS计数76→77、fullfsync成功；WLAN仍PFR PC=0xb019b9bc，
FW_READY/INIT_DONE均0。证据位于`log/device/nabu-boot-20261107-107/runtime-log`。

## 原生偏好动作

新`BluetoothUseSingleAdvertising`由配对主机显式请求，以mobile用户调用
CFPreferences设置`com.apple.MobileBluetooth.debug`中`LE`字典的
`SupportsMultipleAdvertising=false`。保留原字典其他键，记录uid/euid、原值、
同步结果、精确域及CopyAppValue有效读回。`success`仅表示偏好写入和读回通过。
BluetoothInventory增加这一单项的只读查询。

原版chip构造读取该键，随后打印`Overriding Multiple Advertising support - disabled`
和`Using a single advertising instance`。下一次bluetoothd自然重启才会重新构造，
动作不主动结束进程。原有七项extended/periodic选择仍保持原策略，标准single分支
使用系统生成的随机地址提交2005。不改变HCI包、返回值、控制器能力或固定地址。
完整静态证据见`log/host/wireless-v107/bluetooth-random-address-native-path.md`。

## 运行后采集

原有96条TX/RX全命令记录通常在桌面反馈前已耗尽。第108轮在各自上限之后，
额外为Reset、2005、200b、200c保留各256条TX/RX的console日志；参数最多7字节，
仍只在完整包发送成功后记录。额外行使用`NABU BT HCI LATE`，不占32KiB无线报告。
应通过实时syslog和回收日志读取，不能只看WirelessInventory判断后续没有命令。

验收顺序：桌面确认后取无线及蓝牙基线，启动syslog采集，再请求新动作；检查偏好
同步和两处false读回、新daemon的single日志、同一Reset后的2005/status0、
200b/status0、200c/status0，随后再核对真实广告事件及发现/配对。原版single的本地
完成回调不可靠地传播2005错误，必须以控制器实际响应为准。

## Wi-Fi同步排查

继续复用匹配Android驱动与MPSS反汇编，追踪WLAN可恢复保护域异常是否进入已找到的
QuRT字符环打印路径。Android两个ramdump开关当前为0，现有QuRT环地址只是ELF装载
候选；本轮没有据此读取DSP私有内存或变更dump设置，WLAN初始化实现保持v107。
