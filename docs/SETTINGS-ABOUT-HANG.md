# 设置“关于本机”卡住

2026-11-05，第三十一轮用户确认可进入桌面，已将语言改为中文；
点击“设置 → 通用 → 关于本机”后设置无响应，随后手动恢复 Android。

## 已确认的进展

- 第三十一轮日志记录 `boot record previous=1 current=2 fullfsync=ok`，
  证明在真实 UFS APFS 上读回了第三十轮计数。桌面权限修正也已获实机确认。
- 用户更改了语言，约 149 秒的日志出现 `com.apple.language.changed`。
  PID 138 随 SBRestartManager 退出，与语言切换一致。
- Data 块驱动最后记录累计 36,809 次写入、1,243,172,864 bytes，
  日志中的同步错误均为 0。这是累计 I/O，不代表已用空间。
- 完整 slot14 已备份，恢复 3,489,912 bytes 日志，无内核 panic；
  15:55 完成备份后清空。中文偏好是否跨启动保留仍需第三十二轮确认。

## 尚未定位的等待

语言切换后的 Preferences PID 178 和 224 都发生 watchdog 超时，退出码
`0x8badf00d`，记录为未能在 5 秒内正常退出。相应进程的 CPU 用量只有
0.044 和 0.041 秒，显示等待或阻塞的特征，不足以单独确定调用点。
另有 scene-update 的 10 秒超时。

Settings 打开时出现 Wi-Fi、CoreTelephony 等缺失服务请求，但这些记录也在
能响应的设置页面出现，因此目前不能将某一个缺失服务直接判定为根因。
没有改写“关于本机”的字段，也没有据此宣称它已修复。

第三十一轮仅采样了 SpringBoard，未采样 Preferences。第三十二轮沿用
`nabu-data-v32` 和 bootstrap v9，仅把采样改为 Preferences：启动采样器
30 秒后开始，每 2 秒一次，最多取 16 个线程，持续到手动重启。
自动终止仍关闭，仍跳过 QEMU。

## 第三十二轮操作和接续

进入桌面先确认语言是否仍为中文，然后打开“设置 → 通用 → 关于本机”。
若卡住，保留约 30 秒再手动回到 Android，回收对应运行日志。
分析连续的 Preferences 主线程与工作线程帧，结合本地 20F66 符号解析等待点；
需要原版反编译时复用已有证据或转 GitHub Actions。

第三十一轮输入和日志在 `log/device/nabu-boot-20261105-31/`。
本轮进度在 `log/host/settings-about-v33/`。

用户补充对照：RAM Data 启动时“关于本机”可正常查看，改为持久存储后才卡住。后续优先核对存储容量、可用空间、挂载信息与相关 IOKit 查询，仍以 Preferences 实际等待栈确认具体调用，不把服务缺失日志直接当成原因。

第三十二轮已于 `2026-11-05T16:02:19.134818+08:00` 执行 `fastboot boot`，发送与 Booting 均成功；源提交 `d8b02908bd11c210c5c2d1738fc3eea351a71e87`。同一内核和 bootstrap 下，仅调整了采样配置。实机确认和日志回收待进行，输入在 `log/device/nabu-boot-20261105-32/`，接续在 `log/host/settings-about-v33/continuation.json`。
