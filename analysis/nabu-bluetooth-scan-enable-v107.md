# 第106轮扫描启动失败与第107轮诊断

2026-11-07，Asia/Shanghai。

第106轮用户确认桌面正常，USB及155项应用清单可读。完整日志证实slot18已安装，
执行时七项host选择均为0，真实native会话的2007、200b均返回0，越过了旧的712。
下一条200c（LE Set Scan Enable）总包长6字节，控制器返回十进制18，即0x12
Invalid HCI Command Parameters；原生daemon以718重启。发现与配对仍未通过。

首次原生会话位于现有96条全局TX记录限额内，尚未见2005 Set Random Address。
生命周期A/B/C诊断仍会在独立Reset区间发送204a，不应把这一条误判为slot18失效。
首个原生会话的成功参数设置与失败启扫必须按该Reset边界解释。

原版静态分析表明，200c生成器传enable=1，duplicate-filter字节入口限制为0/1。
非AppleTV平台预期选择类型1的随机地址槽；这不是已经测到的200b参数。
既有Core5.4 Vol4 PartE §7.8.11规定，own-address type为1/3且未先设置随机地址时，
enable=1应返回0x12。原版生成了本地随机地址的日志，也不能代替控制器接收2005。
因此随机地址前置条件是当前较强假设，尚不能只凭错误码修正duplicate-filter。

第107轮只增加2005/200b/200c的实际参数日志。完整H4帧到达后，在TX队列锁内、
消费前复制最多7字节；只有整包发送成功时输出。沿用96条全局命令限额，报告实际
参数长度和采集长度。不改命令、响应、IBS或地址策略，复用v106 bootstrap。
ARM64编译/链接及返回入口四种回放通过；独立复核确认复制/输出时序未改变传输。
完整原生依据与复核见`log/host/wireless-v107/bluetooth-scan-enable-analysis.md`。

第106轮8,366,323字节有效日志及完整64MiB槽已备份并清空回读，APFS计数75→76，
fullfsync成功；无最终提交头。设备已回Android，准备第107轮参数采集。

## Wi-Fi并行结果

第106轮仍PFR PC=0xb019b9bc、FW_READY/INIT_DONE均0。静态定位到QuRT的8KiB字符环
DSP VA=0xc1ad6038，ELF PH15给出的装载PA候选为0x8f2d6038；游标/容量另有地址。
这不是运行时页表或APPS权限证明。匹配Android驱动存在shutdown后ramdump的流程，
但仍受dump开关、VMID及minidump/encryption条件约束。

本机Android只读查询得到enable_ramdumps=0、enable_mini_ramdumps=0，MSS IRQ列表
没有qcom,ramdump-disabled。没有修改这些设置，也没有读取固件私有内存；尚未取得
本次BADVA/LR。完整结构和gate证据分别见`log/host/wireless-v106/wlan-candidate.md`
及`log/host/wireless-v107/wlan-ramdump-gates.md`，实读结果为同目录
`android-ramdump-readonly.json`。第107轮继续保持WLAN实现不变。
