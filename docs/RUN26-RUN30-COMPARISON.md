# 第二十六轮与第三十轮启动对比

2026-11-05，按用户指定，以能够进入桌面的第二十六轮为基线。

结论：第三十轮已经完成 libignition，当前桌面阻塞是启动包的服务文件权限
从 0644 变成 0777，导致 launchd 拒绝加载全部 387 个服务文件。

| 阶段 | 第二十六轮 | 第三十轮 |
|---|---|---|
| 用户观察 | 可进入桌面 | 停在 XNU 画面，手动回 Android |
| Data | RAM 临时卷 | 49 GiB 原版 APFS，挂载成功 |
| Image4 / ignition | blob 不可用，ramdisk ignition 完成 | selector 2212 的 11 次 AES 全部返回 0，ramdisk ignition 完成 |
| launchd 自身 | 完成 early boot | 完成 early boot，并继续加载服务 |
| 启动文件属主 | 387 项全部 root:wheel | 387 项全部 root:wheel |
| 启动文件权限 | 387 项全部 0644 | 387 项全部 0777 |
| SpringBoard | 成功启动为 PID 5，进入 running | 被拒绝，error 122：Path had bad ownership/permissions |
| 权限拒绝 | 0 | 774 次 bootstrap 拒绝（387 项分别用于 user/501 和 system） |
| 启动计数 | 不使用磁盘计数 | 0→1，fsync 返回成功；尚未证明跨启动读回 |

## 证据位置

- 第二十六轮 `log/device/nabu-boot-20261105-26/runtime-log/runtime.log`：
  420 行 ignition 完成；638–639 行安排并开始启动 SpringBoard；
  762–767 行确认 PID 5 和 running。
- 第三十轮 `log/device/nabu-boot-20261105-30/runtime-log/runtime.log`：
  445–450 行 Data 挂载与计数；475–496 行 AES 成功；526 行 ignition 完成；
  594 行 early boot 完成；1687、2079 行 SpringBoard 因权限被拒绝。
- 用 7-Zip 读取实际 APFS 镜像元数据：bootstrap v6 的服务文件为 0644，
  v8 为 0777；两者 uid/gid 都是 0。对比保存在
  `log/host/apfs-native-v32/bootstrap-permissions-comparison.json`。

第三十轮完整 64 MiB 日志单元已备份，恢复 400,592 bytes 正文至约 525 秒，
手动重启没有 END。对应 slot14 于 15:38 完成备份后清空。

## 已实施修正

打包工具现在直接设置 APFS 节点的 Unix 元数据，目录 0755、普通文件 0644、
程序及动态库 0755，属主 root:wheel，不再把 Windows/WSL 的宿主 0777 带入镜像。
新 bootstrap v9 的 387 个服务文件均经实际镜像读取确认为 0644。

Data 计数的文件和父目录改用 Darwin F_FULLFSYNC，请求完整媒体刷新；
失败会明确报告，不能当作保存成功。生成后的 PID1 主机测试已覆盖两次计数
及刷新失败保留旧计数。Data 块驱动补充实际写入及同步统计。
静态用户态程序、Data/AES 对象和预链接已构建成功，两个 bootstrap 容器
均通过 apfsck。本轮按既定要求不运行 QEMU，下一步第三十一轮真机测试。

## 持久化尚需确认

第三十轮启动时仍读到 0，第二十八轮的 1 未被读回。恢复 Android 后只读取得
Data 的 checkpoint 描述区，发现有效的 xid=1 和 xid=2，校验和均正确，
证明确实有新 checkpoint 写入磁盘。它不能单独证明计数或用户设置保存正确；
第三十一轮需要检查实际读回。快照和字段记录在
`log/host/apfs-native-v32/data-checkpoints-before31.*`。

继续使用已有 64 GiB 区域、已有 APFS Data 与固定软件 nonce key。
