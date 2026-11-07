# 第110轮：原配对跨重启直连通过

2026-11-07，Asia/Shanghai。复用第108轮内核和bootstrap，用户确认桌面、USB正常，
并确认直接选择原有OPPO Enco Air5 Pro配对条目即可连接，无需重新配对。

## 实测条件与结果

第109轮重新配对后，耳机留在盒中；Android蓝牙关闭，启动前ADB读回
`bluetooth_on=0`。第110轮进入iPadOS后才取出耳机，未改蓝牙偏好或配对数据。

- 原生单广告偏好的stored和effective均为false；PID62启动时自动采用该设置。
- 同一次原生Reset之后，随机地址设置2005、扫描参数200b及扫描启动200c都收到
  控制器status0。后续恢复前缀中没有新的HCI Reset或reason718重启。
- 原生服务成功查找既有Link Key；恢复前缀中没有新的Pairing Completed或
  UserConfirmation事件，与用户确认的“原配对直接连接”一致。
- AVRCP Target、Handsfree Gateway、A2DP Source、GATT均连接result0；
  A2DP完成AAC-LC、44.1kHz协商。音频实际播放仍按用户安排留到声音服务阶段。

这证明上述条件下的配对保留与跨重启重连可用。第109轮失败可能与切换系统期间
的状态变化有关，但本轮成功不能唯一证明Android改写了耳机端配对记录。

## 磁盘日志与持久化

首次回收已保存完整64MiB槽，但随后GPT只读核对报`short GPT read`，未进入清空。
该备份保留于`log/device/nabu-boot-20261107-110/runtime-log/`。重试成功，正式结果为
`log/device/nabu-boot-20261107-110/runtime-log-retry-1/`：

- 完整槽备份67,108,864字节，恢复连续日志3,896,291字节。
- `clearing.json`状态为`cleared-and-readback-verified`；采集及清空后的GPT核对通过。
- 日志未封口，停止原因`no committed record header`；只能报告已恢复的连续前缀，
  不能把完整原始槽备份表述为完整运行日志。
- 行479：APFS启动计数79→80，`fullfsync=ok`。
- 行3379：自动选择单广告；行4377：后续原生Reset；行4873、26737、26741：
  2005/200b/200c实际成功响应。
- 行33495、33978、34572、35637：四项服务连接成功；行35403：AAC-LC协商。

已提取脱敏摘录`log/host/wireless-v110/runtime-evidence.txt`，并更新
`result-summary.json`、`live-result-summary.json`、`continuation.json`及本轮
`trial.json`、`run.json`。重试后设备为Android，启动完成，蓝牙设置读回0。

## Wi-Fi独立结果

行3320仍为`EX:wlan_process:0x1:WLAN RT:0x14b:PC=0xb019b9bc`；行29348记录
26,328字节板参数已确认，但FW_READY与INIT_DONE均为0。本轮没有改变WLAN固件
或驱动，也没有取得Wi-Fi扫描、连接或与蓝牙共同联网使用的结果。

下一步继续追踪固件已有ULog/DIAG读取接口，形成有实际数据出口的诊断候选。
蓝牙保持本轮已验证基线；Wi-Fi异常根因、实际音频播放及无线共同使用仍未解决。
