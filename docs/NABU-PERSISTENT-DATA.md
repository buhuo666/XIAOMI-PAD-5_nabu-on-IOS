# 持久 Data 接入

2026-11-05：用户选择优先处理启动、触摸稳定和设置保存。

第二十七轮结果：启动约 25 秒时创建 `/private/var/Keychains` 返回 EROFS，
初始化主动停止，SpringBoard 没有启动。这不是数据库初始化耗时。
根因是当前编入内核的 HakiOS APFS 驱动强制 `MNT_RDONLY`，不是 Apple 的完整 APFS 驱动。
上一候选只验证了块写入与模拟挂载，遗漏了实际文件系统的可写能力。

第二十六轮仍将 `/private/var` 挂在 RAM。第二十七轮候选通过 `nabu-data=1`
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
- macOS Actions `41959293411` 原生编译及全部检查通过；下载后 14 组检查与 26 个内核代码范围复核一致。bootstrap v7 已经独立 APFS 提取回读。
- 第二十七轮实际挂载只读，目录创建失败。设置保存未实现。恢复 Android 后得到 29,557 bytes 日志；GPT 与 14 个引导分区一致，日志单元已备份后清零。

本地证据在 `log/host/stability-v27/`。设备验收需先确认首轮挂载和计数，
再修改一个可观察设置，正常关机或重启，再次临时启动并核对设置和前次计数。

## 第二十七轮后续核对

完整49 GiB回读摘要仍为初始空APFS的 `2f85c3caa09fb77d1db1ccbf345a3eef5263e962f70a126d725c93586c907a43`，
本轮没有保存用户设置。当前内核已经链接 HFS+ 挂载、mkdir、create、write、rename、fsync
实现；主机准备的49 GiB HFSX日志卷已通过fsck，尚未写入设备。
用户已选择保留 APFS，要求修改内核实现读写，并明确范围仅为分配给 iPadOS 的64 GiB区域。HFSX主机候选不部署。
证据和接续记录在 `log/host/data-v28/`。

## 原版 APFS 接入候选

本地20F66原版APFS闭包含8个组件、7个KPI条目。对当前8796内核的显式指针计划
解析12,117处，其中6,963处指向内核，均有唯一目标；91,590条相对寻址编码通过范围检查。
这些结果尚不证明ABI和运行时兼容。

新增 `nabu-native-apfs=1` 加载入口、8796稀疏prelink索引适配和本地预链接工具。
该模式将已有只读读取器单独命名为`apfsro`以服务当前启动镜像；原版驱动独占`apfs`。
主机检查覆盖关闭路径、加载失败、两套操作表区分；下一步原生构建及QEMU执行原版加载，
然后接入IOStorageFamily设备并验证实际创建/写入/fsync/重启读回。
不将取消MNT_RDONLY或“挂载返回成功”当成完整写入实现。
