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
进一步定位发现寄存器打印函数唯一已识别的直接调用点随后进入trap和无限循环，
另有上下文处理分支绕开该打印点；不能据此认为本次可恢复PFR已写入环。
详见[打印路径范围](nabu-wlan-qurt-printer-v108.md)。

## 构建结果

源码提交`1cc6340`的macOS Actions `42336668179`成功，Objective-C/ARM64编译、
CoreFoundation链接及签名检查通过；产物为134,768字节。联合内核编译、链接与返回
入口补丁回放通过，TX/RX函数栈帧分别464/160字节。bootstrap已通过apfsck，两个
相关LaunchDaemon仍以mobile执行。偏好写入和实际HCI结果等待第108轮实机验证。

第108轮用户确认桌面/USB正常。mobile原生偏好同步及精确/有效读回均false，
新bluetoothd PID181打印single-advertising选择，随后两个实时采集窗口未见718
重启。真实扫描统计分别出现241、74、43、4、0、247条广播事件，均0 dropped，
并有真实Discovered device日志。设置界面、配对及跨重启仍待验收；原始2005/200c
状态须回收console日志核对。Wi-Fi仍同PC异常，FW_READY/INIT_DONE均0。
