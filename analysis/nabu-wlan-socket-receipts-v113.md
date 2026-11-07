# 第113轮：区分DSP socket取包与DIAG响应

2026-11-07，Asia/Shanghai。第112轮仅证明本地发出了正确的root ID回复和一次
ULog 0900查询，仍无DIAG命令响应。原机MPSS接收路径及候选向量依据保存在
`log/host/wireless-v112/diag-rx-followup/findings.md`和`confirm-probe-spec.json`。

## 本轮差异

首次root ID应答和首次0900查询各设置一次QRTR confirm位；仅在实际发送成功后
记录端点和tick。其他控制消息、重复ID及后续ULog查询仍为0，每次启动最多两包。
type7回执沿用v1/v3头解析，要求原机CONTROL到CONTROL封装，按20字节负载中的
DSP node/port关联。回执无事务号，只接受本轮已发送且仍有效的唯一端点关联。
控制端点改变使两个关联失效；命令端点改变或移除使命令关联失效。

PFR退休ULog状态，但不单凭WLAN用户域崩溃认定root MPSS socket已销毁，因此
保留socket历史观测，并在回执日志注明PFR状态。任何回执都不能改变注册信息、
句柄、等待状态、CAL门槛或route_verified；只有实际0900 version1/status0响应
才能证明ULog通路。原机在复制和DIAG分派之前发送回执，收包不等于DIAG已处理。

## 已完成的本地验证

生产GLINK回放通过ASan/UBSan，报告位于`log/host/wireless-v113/glink-test/`。
完整root ID/0900发送字节与独立golden向量一致，总confirm恰好2；v1/v3回执、
错误端点和封装、发送失败、未请求回执、端点退休均覆盖。即使两类回执都到达，
没有正常0900响应仍超时放行CAL，route保持false。既有回归全部通过。

NabuGlink已按arm64目标编译，其他未变化对象复用v112，完成本地预链接和
return-trace四项标量回放。内核v113继续使用成功CI 42160433518/5009ad4的
核心基底与v79原版组件组合；bootstrap v108、蓝牙固件v78、modem固件v79沿用。
本地新模块构建与完整核心CI、实机结果分别记录。

主workflow新增Ubuntu协议回放job，将现有DIAG帧和GLINK sanitizer测试纳入
GitHub，并把nabu-wireless源码加入触发路径。核心/APFS及原生检查仍由原有macOS
job执行。本轮提交须两个job均成功才进入设备临时启动；当前尚未实机验收。

## 实机解释与验收

分别记录root/0900的本地发送、socket回执、DIAG正常/错误/超时响应。两类回执
均有时可继续定位DIAG消费者和分派；缺少某类只能说明取包或回执返回尚无证据，
不能唯一归因为丢包。Wi-Fi的FW_READY、INIT_DONE和真实联网仍独立验收。

用户确认桌面后读取WirelessInventory和BluetoothInventory，蓝牙核对既有偏好
及原生2005/200b/200c初始化。耳机保持留盒，实际音频仍留到声音服务阶段。
回Android且boot_completed=1后备份完整日志槽、恢复控制台，再清空回读。
