# Pad 5 电源与时钟

2026-11-05，用户要求优先修复电池、电量计、PMIC、RTC。第三十三轮候选已完成
主机编译、预链接与读数测试，实机效果尚未验证。

## 硬件依据

本机 Android 的 bms 驱动为 `qcom,fg-gen4`，设备树将 FG 放在 PM8150B 的 SPMI
slave 2：SOC `0x4000`、BATT_INFO `0x4100`、RRADC `0x4200`、MEMIF `0x4300`。
SMB5 充电器也在 slave 2。PM8150 RTC 在 slave 0 的 `0x6000`，告警块为 `0x6100`。
参考手机的 ADSP 电池路径及旧 PM6150 电压估算不适用于这里。

寄存器依据为 MiCode `nabu-r-oss` 提交 `71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c`
中的 `fg-util.c`、`qpnp-fg-gen4.c`、`fg-reg.h`、`smb5-reg.h`、`smb5-lib.c`、
`qpnp-rtc.c`。下载记录及本机 FDT 摘录位于 `log/host/power-v33/`。

## 本轮修复

`patches/nabu-power/NabuPower.cpp` 沿用已验证的 SPMI v5 EE0 observer 通道和
`hakios_spmi_lock`，与 PMIC 按键共享总线锁。仅发送寄存器读命令。

- 从 FG 的硬件 MSOC 读电量；对 SOC、ADC 和副本做一致性检查。
- 读取电压和有符号电流，按 Qualcomm 比例换算，再转换成 Darwin 的充放电符号。
- 从 BATIF、USBIN、SMB5 状态读取电池存在、USB 插入和充电阶段，发布 IOPMPowerSource。
- 从 RTC 的 `0x6048` 读取连续秒计数，并处理低字节进位。
  `capture_nabu_power.py` 在 Android 下采集同一秒的 RTC 与 UTC，保存差值；
  部署工具通过 `/chosen/nabu-rtc-offset` 传递。每次启动重新读取硬件秒数，
  调用 XNU 的 `clock_set_calendar_microtime`，修复从 1970 年开始的系统日期。

首次采集：Android 电量 100%、约 4.438 V、24.5°C；RTC 与 UTC 差值为
1,740,980,100 秒。校准分辨率为一秒，时间基准来自设备 Android。
这个差值不随正常重启改变，启动耗时由实际 RTC 新读数计入。

本轮不写稳压器、充电限值、FG SRAM 或 RTC 硬件计数。未实现温度、学习容量、
循环次数的 FG SRAM 读取，也未实现新的充电控制／温控策略、RTC 告警唤醒和
iPadOS 手动校时偏移的持久化。8720 mAh 设计容量来自本机电池配置；未知项目不填固定读数。

## 验证与启动输入

`NabuPowerReadingsTest.cpp` 通过 ASan/UBSan：电量端点、ADC 换算、正负电流、
充电状态、副本不一致、总线读失败及 RTC 跨字节进位。
RTC 差值经过 ADT 编解码读回；全部 Python 修改通过语法检查。
ARM64 内核对象编译、符号解析及预链接成功。

候选内核为 `artifacts/nabu-power-v33/kernel.native-apfs.macho`；继续使用
bootstrap v9、原有 APFS Data、原有 nonce key。自动终止关闭，跳过 QEMU。
日志读取电池每 5 秒采样，约每 30 秒记录；powerd 只采集四次线程栈。

实机应检查桌面日期、电量显示，以及拔插 USB 后充电图标是否变化；随后手动
回 Android 回收日志，对比真实电量计读数、RTC 增量及系统日历。

第三十三轮已于 `2026-11-05T16:26:37.887161+08:00` 成功发送 `fastboot boot`，源提交 `86ed211`。
电源与 RTC 实机结果等待用户操作及日志回收，确切输入在 `log/device/nabu-boot-20261105-33/`，接续在 `log/host/power-v33/continuation.json`。
