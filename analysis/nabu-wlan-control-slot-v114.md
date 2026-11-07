# 第114轮：同一DIAG控制socket能否再次取包

2026-11-07，Asia/Shanghai。第113轮已证实root control0:26与command0:27分别
开始取包，后续仍无REG/WLAN ID及0900响应。此轮只增加一个有界的控制槽观测。

## 原机依据与排除项

`log/host/wireless-v113/diag-consumer-followup/findings.md`闭合原机socket单槽：
conn+0x54非零时不再recvfrom。正常控制消费者c0945188复制，c09451dc清零，
解锁后才跳入c092a040；清零先于parser。因此再次取包最多证明槽再次可用，
不能证明首包已进入parser或ID赋值成功。连接初始化也可清零，且间接写入搜索
并不穷尽；结果须连同端点变化、PFR和连接记录解释。

已排除的候选：root ID字段/完整名字与原机一致，无额外padding要求；FEATURE
不是阻塞等待ID，也没有在已有socket mode2下重新切换连接的依据。原机type7
控制分派不要求CONTROL端口，不能把APPS确认包端口形式归因于无回复。
`command-framing-followup/findings.md`闭合TYPE_CMD→signal2→raw复制→按首字节
分派，现有四字节0900无需额外7e01/HDLC；diag_first_pkt初始化后继续处理同一
包，不是丢弃首包，也不构成发送预热命令的依据。

## 本轮受控差异

首次root ID回复按原有内容/时点发送，confirm=0；发送成功后缓存其实际完整
字节。在既有WLFW服务已出现且stage0版本查询可发的时点，先仅重复一次相同
root回复并设confirm=1，再发原来的单次0900（confirm=1）。不增加任意延迟，
不延长CAL，不以回执重试。首回复发送失败不缓存；重复包未成功发送则不记录
confirm，也不发送其后的0900。其他正常控制回复全部confirm=0。

每次boot仍最多两个confirmed包，每个端点只有一次。回执没有事务号，所以
不能保留首次root的confirm再确认重复包。控制端点变化会清除缓存并退休原有
ULog/回执关联；PFR后不再发送重复包，历史回执仍可记录。

重复root的回执仅表示该控制socket再次进入recvfrom。如果随后出现REG或
0900回复，也必须按真实内容记录，不能提前推定原因或将本诊断称为修复。
没有重复回执则取包/回执返回边界仍未知，不唯一指向pending slot卡住。

## 构建与验收计划

内核v114重新编译NabuGlink，其余对象复用v113；成功CI42160433518/5009ad4
核心基底、bootstrap v108及既有固件沿用。完整GitHub CI的核心和无线协议job
均成功后才临时fastboot boot。等待用户桌面确认，再运行WirelessInventory和
BluetoothInventory；核对重复包回执、实际DIAG响应、PFR、FW_READY/INIT_DONE
及既有蓝牙偏好/原生初始化，声音播放仍后置。

设备回Android且启动完成后，回收完整日志槽和连续控制台，备份后清空回读。
本轮之前APFS计数83。当前尚未进行第114轮实机测试。

本地生产协议ASan/UBSan回放已通过：首次不确认、成功后缓存、WLFW前不重复、
原字节重复仅一次、发送失败阻止0900、重复成功后0900发送失败不再重复控制包、
端点改变/删除及PFR退休、两次确认上限、收到回执仍无DIAG成功，既有回归均通过。
arm64编译、本地链接和return-trace四项回放通过；最终产物目录为
`artifacts/nabu-wireless-v114-final`（保留了先前仅日志措辞不同的未部署构建）。

另已找到原机VERNO wire00→c0943700→55字节响应，但公共response drain
c092b194..b1a4同样受动态root ID非零门槛限制，所以未把它加入本轮。
证据为`log/host/wireless-v113/root-version-probe/findings.md`。
