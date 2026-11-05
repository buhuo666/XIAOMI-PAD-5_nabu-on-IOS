# Pad 5 电源与时钟

2026-11-05，用户要求优先修复电池、电量计、PMIC、RTC。第三十三轮已确认
进入桌面，电量显示及 USB 插拔状态有效，RTC 正常走时。显示时间错误来自
US/Pacific 初始时区；第三十四轮用户已确认时间正确，USB 图标仍约 5 秒更新。
第三十六轮用户已确认 USB 插拔响应正确，日志确认平台 UUID 修复消除了固定等待。

## 第三十六轮验收与可用基线

用户反馈：“这次正确了，设备已恢复安卓”。本轮 `gethostuuid rc=0 elapsed-ms=0`，
即成功返回且耗时低于日志的 1 ms 分辨率。四次 USB 电源切换后，PMRD 从
`kPMPowerSource` 到 `kPMMinutesToSleep` 的间隔分别为 7.596、6.748、7.145、
7.698 ms，第三十五轮约 6 秒的偏好等待已消失。诊断进程同一 uptime 时钟下，
对应 IOKit 与 IOPS 回调仅相隔 1–2 ms。该间隔不是物理插拔到屏幕绘制的测量；
图标响应以用户实机验收为准。

电量计与 PMIC 未记录读失败或副本不一致，RTC 持续走时。APFS 启动计数
`6→7`、`fullfsync=ok`。完整 64 MiB slot14 已备份，恢复 1,823,628 bytes
日志；用户手动重启，因此日志流没有 END。该槽于 17:40:39（Asia/Shanghai）
清空并回读确认。30 份 GPT 记录和 Android 引导分区检查通过。

可用基线保留 `artifacts/nabu-power-v36/kernel.native-apfs.macho`、稳定平台 UUID、
原有 RTC 校准及 Image4 key。移除启动参数中的密集 powerd 栈采样，bootstrap
采用已验收的 v10（与本轮 v12 使用同一 PID1 程序，387 个启动任务，没有临时
power-trace 任务）。诊断工具源码保留供后续按需使用。

精确结果在 `log/host/power-v36/device-results.json`，关键日志在同目录
`power-events.txt`。MiniIONetworkStack 仍报告 registry busy=1；本轮不作为
“关于本机”修复的证据。下一项基础工作为真实 FG 温度、学习容量及循环次数读取；
完整充电／温控策略、RTC 告警和手动校时偏移持久化尚未实现。

## 第三十五轮定位与第三十六轮平台 UUID 修复

第三十五轮用户仍报告两种图标延迟均未改善，已手动回 Android。
日志确认充电阶段在插入后约 0.5 秒就被读取并发布；断开时 IOKit 回调也及时进入。
诊断进程在 74.314 秒进入断开回调，80.330 秒才继续处理 IOPS 回调；
插入时对应 86.184→92.201 秒，均约 6 秒。旧诊断在回调内同步调用
IOPSCopyPowerSourcesInfo，会阻塞自己的事件循环，因此不能直接把后一个时间
当作 IOPS 通知的发送时刻。内核 PMRD 也在切换电源后停顿约 6 秒才更新偏好。

IOKitUser 2022.120.2 的 `copyActivePreferences` 读取 AC/Battery/UPS 三组偏好。
每组 `copyPreferencesForSrc` 调用 `getHostPrefsPath`；平台 UUID 缺失时，
`gethostuuid` 等 1 秒并失败，随后 `IOPMCopyFromPrefs(NULL, ...)` 再等一次。
三组共六次 1 秒等待，与日志的固定停顿吻合。
当前通用 ARM 平台只根据 Apple unique-chip-id/chip-id 生成 UUID，而本机 ADT
没有这些字段，也没有发布 IOBSDGetPlatformUUID 所等待的 IOPlatformUUID 资源。

第三十六轮从 Android 的真实 Qualcomm SoC id/serial 派生稳定的端口 UUID，
以 `/chosen/nabu-platform-uuid` 传入，在平台 provider 上设置标准 IOPlatformUUID
属性并发布同名 IOKit 资源，接通原版 gethostuuid。SoC 为 SM8150/id 339，序列值
仅保存在本地采集记录。该 UUID 用于本机偏好命名空间，不冒充 Apple ECID；
没有填写 Apple unique-chip-id/chip-id 字段，也不更改现有 Image4 nonce key。

诊断程序改为分别记录 IOKit 与 IOPS 回调，移除回调中的同步快照请求，
并直接记录 gethostuuid 的返回码与耗时。powerd 栈采样改为每 500 ms，
用于候选未解决时捕获实际等待调用。稳定 UUID/不同设备区分/ADT 回读测试通过，
内核与诊断程序已编译链接，第三十六轮验收已确认消除等待，见上方记录。

## 第三十四轮结果与第三十五轮候选

第三十四轮确认上海时区修正有效，APFS 计数 `4→5` 且 F_FULLFSYNC 成功。
日志完整回收后已于 16:45:33 清空 slot14。

日志中 `USB poll=250ms` 生效，88.252 和 110.681 秒的断开发布均落在完整
电量采样的间隔内。99.084 秒插入时 USB=1、charging=0、SMB5 state=7；
到 102.617 秒的完整采样才发布 charging=1、state=4。
上一版快速检查了插线标志，却没有同样检查充电阶段，这是一个已确认的遗漏。
它不能单独解释用户观察到的断开图标延迟。

第三十五轮将 USBIN 和 SMB5 阶段一起纳入 250 ms 轮询，任一变化立即刷新并发布。
针对 USB 不变但充电阶段改变的回归测试已通过，原有电量换算、失败处理和 RTC
进位测试也通过。

同时放入只读 `org.nabu.power-trace` 诊断进程，订阅 IOPMPowerSource 的
IOGeneralInterest 和 IOPS 电源变化回调；每次记录同一开机时间轴上的回调时间、
IORegistry 的 ExternalConnected/IsCharging、IOPS 的状态。它不写电源状态。
工具用 LLVM 18 构建 ARM64 动态可执行文件，23 个导入均已在本机原版 20F66
dyld 导出树（含 libSystem 转出）找到。实际运行及回调是否到达仍需实机确认。

公开 PowerManagement 1436.120.6 中的 BatteryTimeRemaining.m 也使用该
IOKit interest 通知，并发布 IOPS 通知；本轮使用源码理解接口，未据此假定
设备上闭源程序的具体延迟。下载记录在 `log/host/power-v35/PowerManagement/`。

候选为 `artifacts/nabu-power-v35/kernel.native-apfs.macho` 和 bootstrap v11；
保留第三十四轮的 PID1 时区修正。两个 APFS 容器检查通过，7-Zip 独立读回
388 个启动任务（原有 387 + 临时诊断 1），权限均为 0644，诊断程序为 0755。

## 第三十三轮结果与第三十四轮修正

用户确认日期正常、电量可见，USB 拔插均延迟超过 3 秒。完整 64 MiB 日志单元
已回收并于 16:31 清空。实测 arbiter 为 `0x50000000`，三个 PMIC slave 0/2/4
分别报告 subtype `0x1e/0x20/0x1f`。电量计 MSOC=255，即 100%；电压在
4352–4416 mV 之间，拔线期间电流为 -813/-466 mA，USB=0。未记录总线读错误或
电量计副本不一致。APFS 计数 `3→4`，F_FULLFSYNC 成功。

RTC 连续记录 5 秒增量，初始 UTC 为 `1793867236`，即 08:27:16 UTC。
launchd 随后显示 `2026-11-05 00:27:20`，而 Asia/Shanghai 应为 16:27。
bootstrap v9 的 var.skel 确实把 localtime 指向 `zoneinfo/US/Pacific`。

第三十四轮将 USB 检测改为 250 ms，检测到变化立即刷新电池并发布状态；
完整 FG 读数和 RTC 仍每约 5 秒读取。该周期是驱动检测间隔，最终图标延迟还需
实机确认。当前仍为 observer 轮询，尚未接入 SPMI 中断。

bootstrap v10 在 launchd 启动前把旧模板的 US/Pacific 链接一次性改为
Asia/Shanghai，并持久化迁移标记；后续用户选定的时区不再被覆盖。新 Data
初始模板也使用 Asia/Shanghai。未改变 UTC 校准值，继续沿用第三十三轮的 RTC 差值。

主机验证通过：时区迁移、写入失败保留原链接、迁移后的重启和用户后续时区选择；
Data 挂载与文件同步回归；静态 PID1 编译、内核对象编译及链接；两个 APFS
容器的 apfsck；7-Zip 独立读回上海时区和全部 387 个 launchd plist 的 0644 权限。
候选为 `artifacts/nabu-power-v34/kernel.native-apfs.macho` 和 bootstrap v10。

以下为第三十三轮的实现记录。

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

第三十四轮已于 `2026-11-05T16:42:03.571381+08:00` 成功发送 `fastboot boot`，源提交 `555dd73`。
时间与 USB 图标响应的实测结果待用户确认；输入在 `log/device/nabu-boot-20261105-34/`，接续在 `log/host/power-v34/continuation.json`。

第三十六轮已于 `2026-11-05T17:32:14.586514+08:00` 成功发送 `fastboot boot`，源提交 `481ca90`。
平台 UUID 查询及 USB 图标响应均已验收，确切输入与回收日志在 `log/device/nabu-boot-20261105-36/`，接续在 `log/host/power-v36/continuation.json`。
