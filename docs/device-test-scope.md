# 真机测试写入边界

用户在分区完成后明确要求：设备项目测试只能使用刚创建的项目空间。
此约束取代此前为了分区而授权清空 userdata 的临时操作权限。

## 允许的设备项目空间

4096 字节逻辑扇区，以下 LBA 均含首尾：

| 分区 | 块设备 | 起始 LBA | 末尾 LBA | 用途 |
| --- | --- | ---: | ---: | --- |
| nabu_esp | sda35 | 107603712 | 108652287 | 4 GiB FAT32，测试工具、引导材料和报告 |
| nabu_system | sda36 | 108652288 | 124380927 | 60 GiB，当前未格式化，后续系统空间 |

项目不再写 userdata、metadata、Windows ESP / 系统 / 数据、boot_a/b、
vendor_boot、dtbo、vbmeta、固件或 uefivarstore，也不修改 GPT、活动槽位、
BCD、BootOrder / BootNext。不要把项目文件推到 `/sdcard` 或 `/data`。
本轮只对 sda35 写入；sda36 保持只读、未格式化。

PC 文件和临时恢复环境的 RAM 不属于上述设备持久分区。
诊断恢复镜像只允许通过 `fastboot boot` 临时加载，不能 flash。
Linux 的块设备只读标志只作用于当前内核，不代表随后 UEFI 也会只读。

## 已完成的实机存储测试

2026-10-22，在没有挂载磁盘文件系统的临时 root 恢复环境中：

1. 重新解析六个 LUN 的主备 GPT 并校验 CRC；新三分区边界与已完成的分区
   记录一致，原有条目身份未变，内核容量及起点一致。
2. 其他分区全部设置 kernel read-only；sdb–sdf 整个 LUN 也设为只读。
   sda 原始整盘只用于读取 GPT，不是写目标。
3. 仅将 sda35 挂载到 `/tmp/nabu-project-esp`。写入 16 MiB 随机测试文件，
   核对 SHA-256、sync、卸载，重新只读挂载后再次核对哈希。
   测试文件已删除，其他持久文件只位于新引导区。
4. 新引导区部署了已验证 run 39779752907 的 ARM64 UEFI 探针：
   `\EFI\NabuDiag\NabuProbe.efi`，14336 字节，
   SHA-256 为 `3eb983d3682a3a34cf8e72f16fdf53ca7ade46f55426b443cc0059b38505c7d0`。
   同目录保存版本 manifest 和恢复环境硬件观察报告。
5. 测试前后 11 个受保护启动 / ESP 分区的完整哈希一致，
   六个 LUN 前后边界一致，Windows 系统 / 数据卷边界样本一致。
   全部分区已卸载，测试后 sda35 也设为只读。

执行器 `tools/deploy-project-probe.py` 只允许固定项目文件名和随机测试文件，
拒绝覆盖已有文件；检查实际 GPT、内核边界、挂载来源及所有受保护哈希。
它不重启、不刷写、不格式化、不运行 EFI，不调用旧 userdata 初始化器。
真实设备记录保存在 PC 的
`build-artifacts/device-observations/project-probe-deployment-20261022/`，
不提交原始备份或私有设备日志。

## 硬件观察的实际限度

临时恢复内核观察到 MemTotal 11,733,112 KiB，以及覆盖扩容内存地址段的
Linux System RAM 范围。正常 Android 的 MemTotal 为 11,766,512 KiB；
不同内核的保留内存不同，不能把差异理解为扩容失效。
本次没有读到 fb0 的几何或 stride 元数据。
这些是 Linux 观察，不是 UEFI 内存图、GOP 或已分配给 XNU 的内存。

**探针只是部署到设备，并没有在 UEFI 中执行；XNU 也没有真机启动。**
现有 UEFI 仍需确认可手动加载文件的入口、自动启动行为和变量持久化路径。
在证明旧 UEFI 不会自动启动 Windows 或写入允许范围之外的存储前，
不自动 RAM-boot 旧 UEFI，不添加默认 EFI/BOOT 或 startup.nsh。

可确认的手动入口建立后，从明确识别的新 nabu_esp 运行无参数探针；
需要保存时，仅从该卷调用 `--save`。探针源码将报告写到应用自身所在卷，
但这不限制固件其他组件的写入行为。不能把 Linux 只读标志当成 UEFI 的
持久写入隔离，也不能用模拟器通过替代此设备的 GOP / EL / 内存报告。
