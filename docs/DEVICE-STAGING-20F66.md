# 20F66 设备暂存与临时启动边界

日期：2026-11-04，Asia/Shanghai。

接手结果：`log/device/stage-20F66-20261104-handoff/staging-receipt.json` 已记录 `all-files-staged-and-verified`。原 OS 文件复核通过，SystemOS 与 trust cache 续传完成，三个文件共 7,732,261,164 bytes，设备 SHA-256 全部一致。用户随后明确授权在旧 64 GiB 区域安装并建立持久 Data，后续写入见 [DEVICE-INSTALLATION-20F66.md](DEVICE-INSTALLATION-20F66.md)。下文仅描述暂存阶段，不能用其中“尚未写入”的历史状态覆盖后续安装收据。

用户明确要求设备测试使用临时启动。后续候选只能经 `fastboot boot` 进入；不使用 `flash`、`erase` 或 `set_active`，不覆盖 boot、recovery、xbl 或 abl。iPadOS 材料暂存与内核启动是独立操作，复制成功不代表系统已安装或可运行。

## 本次设备核对

使用 `tools/collect_device.py --adb D:/platform-tools/adb.exe` 和 `tools/backup_gpt.py` 重新采集。设备序列号只以摘要保存于本地收据，未提交。

- 快照：`device/inventory-20261103-235705/`，确认唯一连接设备为 nabu，root 可用，电量 100%。
- GPT：`backup/gpt/20261103-235736/`，六个 LUN 的主备头、分区数组 CRC 与副本一致。
- `nabu_esp`：sda35，4 GiB，FAT32，卷标 NABU_ESP。
- `nabu_system`：sda36，60 GiB，HFS+，卷标 Nabu_iPad8_1。
- 两个分区的 GUID、起止 LBA 与本地已授权回收清单逐项一致，采集时均未挂载。
- Android `/data` 采集时可用 148,967,252 KiB，足以暂存本次 7,732,261,164 bytes 的材料。

ESP 仅以只读方式挂载检查，随后卸载。其三个文件备份于 `backup/esp/20261103-235736/esp-files.tar`。当前只有 `EFI/NabuDiag/NabuProbe.efi` 和两个说明 JSON；部署说明明确记录 `firmware_executed=false`、`kernel_executed=false`。没有发现 rEFInd、UniXNU 或 DarwinBoot，也没有取得可启动入口已经运行的证据。

## 材料暂存

`tools/prepare_ipados_payload.py` 生成 `log/analysis/ipados-device-payload/transfer-files.json` 后，使用：

```powershell
python -X utf8 tools/stage_ipados_payload.py --manifest log/analysis/ipados-device-payload/transfer-files.json --inventory device/inventory-20261103-235705 --output log/device/stage-20F66-20261104 --apply
```

该工具先核对本地 SHA-256、设备身份与容量；文件上传到 `/data/local/tmp/nabu16/20F66/*.part`，设备端 SHA-256 一致后才重命名。它没有分区写入、格式化或重启操作。每个文件的完成情况记录于 `log/device/stage-20F66-20261104/staging-receipt.json`。

原始 OS 与 SystemOS 是供后续 UFS 窗口使用的材料。暂存目录目前不构成 DarwinBoot ramdisk、APFS 挂载或系统安装。旧 64 GiB 区域的边界和内容保持本次采集状态；最终存储布局等待实际 8796 存储驱动与根卷绑定确定。

## 临时启动的实际前提

完整内核构建通过后，仍需匹配的 AArch64 EFI、nabu 板级临时启动镜像、实际 ADT 和可观测日志。当前供体固件、通用编译检查内核与旧项目诊断程序均不能直接代替这些文件。

启动入口及其待验证内容见 [NABU-BOOT-ENTRY.md](NABU-BOOT-ENTRY.md)。系统材料的格式、哈希和用途见 [IPADOS-DEVICE-PAYLOAD.md](IPADOS-DEVICE-PAYLOAD.md)。
