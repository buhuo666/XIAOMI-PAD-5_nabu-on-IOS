# 持久 Data 接入

2026-11-05：用户选择优先处理启动、触摸稳定和设置保存。

第二十六轮仍将 `/private/var` 挂在 RAM。当前候选通过 `nabu-data=1`
选择已安装的 49 GiB APFS Data，节点为 `/dev/nabu_data`，偏移和 UUID
来自 `configs/nabu-storage-layout.json`。不执行格式化；系统 OS、SystemOS
保持只读，日志区域使用独立的写入范围。

内核支持 BSD block read/write、512-byte 逻辑块的 4 KiB 读改写、FUA WRITE(10)
和 SYNCHRONIZE CACHE。对 Data 边界外的写请求整体拒绝，不截断后写入。
启动时检查 Data 容器 UUID、大小、NXSB 校验和；不要求可变数据与初始空卷哈希一致。

PID1 在复制初始种子前挂载该卷。已有偏好文件保留，仅补充缺失文件，
启动时清理 tmp/run/vm。显式启用 Data 但挂载失败时终止初始化并记录错误，
不让临时 RAM 桌面掩盖设置保存失败。`/private/var/db/nabu-boot-count` 使用
临时文件、fsync、rename 和目录 fsync 更新，日志记录前后计数供跨启动核验。

## 当前验证

- 设备只读预检：49 GiB 容器 UUID 和 NXSB 校验和正确；30 份 GPT 记录一致。
- 生成后的 UFS/Data 实际代码通过 ASan/UBSan：卷边界、系统/日志隔离、512-byte
  读改写、跨传输块、最后物理块、FUA/flush、传输错误和默认关闭。
- 现有日志写入与回收检查继续通过，包括 512 MiB 连续日志流。
- 生成后的 PID1 通过主机检查：APFS 选择、失败阻止 RAM fallback、临时目录清理、
  两次启动读取递增的实际文件记录。ARM64 静态源编译通过。
- macOS 原生链接、Apple APFS 实机接受、设置更改与重启后保留尚待验收。

本地证据在 `log/host/stability-v27/`。设备验收需先确认首轮挂载和计数，
再修改一个可观察设置，正常关机或重启，再次临时启动并核对设置和前次计数。
