# 持久 Data 接入

当前任务：实现 OS 持久化，仅接管分配给 iPadOS 的 64 GiB 区域（4 GiB ESP + 60 GiB 系统分区）。采用现有 APFS Data；完成标准是文件写入、正常刷新及重启后设置保留。

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


## QEMU 原版加载核对（2026-11-05）

`__PRELINK_INFO` 已放到所有静态组件末端，修复8796滑动地址范围未覆盖kext的问题。
原版corecrypto执行全部FIPS自检成功；并没有发现minicrypto抢先注册的证据。
AppleImage4的 `failed to get crypto algorithm: 2` 来自读取 `/chosen/crypto-hash-method`
失败，2为缺失属性错误码。补齐QEMU启动树的hash方法、mix-n-match策略和manifest节点后，
原版AppleImage4及APFS初始化均可执行，无内核panic。

APFS在异步线程中注册，kext启动返回0时立刻扫描会误报registered=0。
实际PID1查询得到原版`apfs` type24与内建`apfsro` type63并存；新增vfs_fsadd完成回调更新诊断。
QEMU独立3MiB Data的md1节点已被原版APFS接受，并读取NXSB、checkpoint和spaceman。
正确mount参数与旧驱动的路径字符串接口不同。当前普通挂载停在`invalid fsindex: -1`，
尚无文件创建/写入成功证据。继续核对卷索引和块设备接口，不直接进入实机测试。

证据：`log/host/apfs-native-v28/qemu-f-serial.log`、`qemu-h-serial.log`。
另纠正接口审计范围：旧190-slot/176-binding报告来自iOS17参考，不能作为20F66/8796已验证依据。

## 原生 Data 块设备接入（2026-11-05）

`md1s1` 别名已解决卷索引错误，但原版 APFS 接着返回 `fs iokit node was not found` 和 `apfs_iokit_mount_eligibility` 错误 1。该日志在 `build/qemu-apfs-v28/i/serial.log`。

新增 `org.nabu.driver.DataBlock`，直接将已安装的 Data 窗口（window 2）接到 IOBlockStorageDevice；UFS 的读取、写入和同步接口继续使用现有实现。QEMU 通过 `NabuDataDisk` 启动树属性把测试镜像接入同一设备类。源内核按 UUID 查找实际 IOMedia BSD 名称，并通过 `kern.nabu_data_device` 交给 PID1，以原版 APFS 的结构参数挂载 `/private/var`。

第一次独立设备编译因头文件宏组合暴露了未声明的 `vm_object_t` 失败；源内核成功。已经调整为独立 kext 编译宏，下一构建同时带有卷路径查询。QEMU 的 QMP 镜像保存已执行通过，文件写入及跨启动读回等待新设备编译、链接后执行。此阶段没有修改设备磁盘。

Actions `41978509370` 的内核、独立 Data 驱动及全部构建步骤成功。链接器补入跨越 ARM64 直接跳转距离的调用跳板和 split-kext 描述后，原版 APFS 识别 `/dev/disk1s1`，完成创建、30 字节写入、fsync、rename、卸载、重新挂载和逐字节读回。第二次独立 QEMU 启动加载上次保存的 Data 镜像，读到启动计数 1 并写为 2，文件读回和最终卸载仍成功，两次均无 panic。

结果在 `log/host/apfs-native-v29/qemu-persistence.json`；逐步日志为 `qemu-third.log` 与 `qemu-restart.log`。最初报告解析器误把含 NUL 的 30 字节载荷写为 29，已改正，汇总按串口实际结果生成。QEMU 的跨启动结果验证原版 APFS 文件系统路径；实机 UFS 挂载与设置保留仍需第二十八轮确认。

## 第二十八轮实机启动

`2026-11-05T14:35:29.489120+08:00` 已执行 `fastboot boot`，发送与 Booting 均成功，源提交 `b942eb7b5f3510b27c9cbab9ddfd0b3c50342de1`。
启动链采用原版 APFS + NabuDataBlock、bootstrap v8、`nabu-native-apfs=1 nabu-data=1`。日志使用已准备的 slot14（64 MiB），自动终止保持关闭。实机桌面、Data 挂载和设置跨启动结果等待用户操作及日志回收；当前只确认临时启动命令成功。启动输入和部署记录保存在 `log/device/nabu-boot-20261105-28/`。

## 第二十八轮回收与第二十九轮候选（2026-11-05）

第二十八轮未进入桌面。已回收完整 64 MiB slot14 快照，恢复 37,008 bytes 连续运行日志；手动重启没有 END 记录。日志明确记录 `/private/var mounted from /dev/disk1s1` 和 `boot record previous=0 current=1 fsync=ok`。launchd 输出 libignition 参数后停止前进，SpringBoard 尚未创建。对应日志单元已于 14:43 完成备份后清空。

先前 QEMU 诊断已把等待点收敛到 `security.mac.img4.ignition_blob`。软件 AES 已注册且自检通过；补发 `/defaults` 的 IOPlatformDevice 后，原版 AppleImage4 继续执行但出现 `performAES: 0xe00002c7`（不支持）。这仍是待修复错误，不能据此声称启动恢复。

第二十九轮采用 `artifacts/nabu-data-v30c/kernel.native-apfs.macho` 和现有 bootstrap v8。新加 NabuAES 诊断类记录请求长度、操作、密钥选择器、位数及返回码，不输出密钥内容，也未替换硬件密钥。launchd 线程采样安排在 60/90/120 秒；自动终止保持关闭。编译及预链接已成功，按用户要求不再运行 QEMU，直接进行真机测试。

沿用现有 49 GiB APFS Data 和 slot14 日志区，部署只更新现有 ESP 文件。实机需要确认 AES 错误参数、启动是否前进，以及若能继续到 PID1 挂载阶段，能否读回上一轮计数 1。主机记录位于 `log/host/apfs-native-v30/`。

第二十九轮已于 `2026-11-05T15:10:25.138671+08:00` 执行 `fastboot boot`，发送与 Booting 均成功，源提交 `61bb3168e1a19795708c83f3b12d0a79842aea21`。本轮跳过 QEMU，待用户观察及恢复 Android 后回收日志。确切启动包、源码、对象文件、部署记录保存在 `log/device/nabu-boot-20261105-29/`；接续记录为 `log/host/apfs-native-v30/continuation.json`。启动命令成功不代表进入桌面或持久化验收通过。

## 第二十九轮回收与第三十轮修正

用户确认第二十九轮停在 HALTED，已手动返回 Android。完整 slot14 只有 BEGIN，没有运行正文；已完整备份后清空。Actions 41986602232 的原版反编译确认 Image4 需要 selector 2212 的 AES-128，而现有驱动只接受普通软件密钥。第三十轮接入固定的设备软件 nonce key、延后 defaults 发布并保存失败诊断，仍直接真机测试。接口依据、密钥保存位置及实际限制见 [Image4 AES 初始化](NABU-IMAGE4-AES.md)。

第三十轮已于 `2026-11-05T15:28:33.923176+08:00` 执行 `fastboot boot`，发送与 Booting 均成功，源提交 `d733bfd913899ff812c8993de8dfecb5ac5e9308`。使用 `nabu-data-v31b` 和 bootstrap v8，仍未运行 QEMU；运行效果待用户观察及日志回收。确切输入和源代码保存在 `log/device/nabu-boot-20261105-30/`，接续记录为 `log/host/apfs-native-v31/continuation.json`。

第三十一轮已于 `2026-11-05T15:49:15.186531+08:00` 执行 `fastboot boot`，发送与 Booting 均成功，源提交 `1c8e56adcca6f0e03fa5c4a783ab5aa124a3290a`。输入为 nabu-data-v32 + bootstrap v9，仍跳过 QEMU；桌面和跨启动记录等待实机结果。确切输入保存在 `log/device/nabu-boot-20261105-31/`，接续记录在 `log/host/apfs-native-v32/continuation.json`。

## 第三十一轮实机读回与桌面

用户确认恢复桌面并把语言改为中文。实际日志记录 `previous=1 current=2 fullfsync=ok`，证明第三十轮计数被真实 UFS APFS 读回。后续同步均未记录错误，已完成物理文件计数的跨启动验证；中文偏好是否保留等待第三十二轮。新增“关于本机”页面卡住的问题，见 [设置关于本机](SETTINGS-ABOUT-HANG.md)。
