# GPU224 新设备部署：选择 iPadOS 容量

2026-11-12。把本更新合并到一份尚未绑定平板的 GPU224 部署包，再为新设备选择容量。

同一个动态容量内核读取每次安装的布局。总容量包括 4GiB ESP；系统区域固定 10GiB，日志固定 1GiB，其余作为空白 APFS Data。

| 选择的 iPadOS 总空间 | ESP | nabu_system 分区 | 系统区域 | Data | 日志 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 32GiB | 4 | 28 | 10 | 17 | 1 |
| 64GiB | 4 | 60 | 10 | 49 | 1 |
| 128GiB | 4 | 124 | 10 | 113 | 1 |
| 256GiB | 4 | 252 | 10 | 241 | 1 |

这里选择的是划给 iPadOS 的空间。平板标称 256GB 不表示能划出 256GiB：还要给其他分区和 Android userdata 留空间，扫描器会按实际扇区判断。支持整数 GiB，最小 32GiB。

## 1. 在新设备工作目录中选择容量

在 Windows 本地 NTFS 目录解压完整原部署包，再合并本更新。建议使用 `C:\Nabu224` 这样的英文路径。

双击 `00-select-capacity.cmd`，输入总容量。也可以明确指定，例如 128GiB：

```powershell
& .\host\python\python.exe -X utf8 .\tools\select_nabu_capacity.py --total-gib 128
& .\host\python\python.exe -X utf8 .\tools\prepare_selected_data.py
```

生成 `configs/selected-layout.json` 和 `data-selected/data-image.json`。后者附带小型 APFS 元数据块；`data-work/selected-data.apfs` 是主机上的稀疏文件，逻辑容量等于 Data，实际只占元数据空间。完整逻辑摘要计算可能需要几分钟。

格式化器和检查器随更新提供，不需安装 WSL 或另外编译。GPL 对应源码及构建脚本在 `host/apfs/source`。这两条命令只写电脑上的新文件。

每台平板使用一份独立工作目录。在绑定前确定容量；工具保留已有选择和生成结果。更换选择可使用另一份干净工作目录。

## 2. 扫描并准备所选分区

按原部署说明运行 `01-scan-target.cmd`。扫描、绑定、安装和日志工具自动选择 `configs/selected-layout.json`。

分区要求变为：`sda35/nabu_esp` 固定 4GiB，`sda36/nabu_system` 为总容量减 4GiB。扫描器生成对应建议边界；首次分区仍按目标机的离线方案完成，然后重新扫描并绑定。

本次容量选择没有增加自动缩小 Android userdata 的执行器。它生成规划；实际改变已有 Android 分区仍需原部署说明中的独立步骤。

## 3. 安装使用本次生成的 Data

下载、提取、暂存系统和目标身份的流程沿用原说明。安装预检和首次安装时，将 `--data-bundle data-seed` 改为：

```text
--data-bundle data-selected
```

例如预检：

```powershell
& .\host\python\python.exe -X utf8 .\tools\install_ipados_windows.py --inventory device/target --gpt-backup 'backup/gpt/<本次扫描目录>' --data-bundle data-selected --staging-receipt log/device/stage-target/staging-receipt.json --output log/device/install-target
```

预检通过后，按原说明对同一命令加 `--apply`。新安装初始化所选 Data 和最后 1GiB 日志区；首次完整写入与读回的耗时会随容量增加。

## 4. 日志准备及启动使用新内核

日志准备命令中的 `--kernel` 使用：

```text
artifacts/nabu-dynamic-storage/kernel.native-apfs.macho
```

`prepare_chain.py` 默认使用这个内核，也可用 `--kernel` 明确指定。其余部署、临时启动和回收命令沿用原说明。

所选布局的日志清单版本为 3；日志仍占最后 1GiB，有 16 个 64MiB 分配单元。收据记录本次容量，回收按对应位置读取。

## 5. 已有安装的处理范围

新内核也支持旧 64GiB 布局及旧日志格式。已有平板可继续使用它原本的布局和 Data，无需重新格式化。

容量选择用于新安装。它不会给已有 APFS Data 在线扩容或缩容；安装器遇到不同的已安装布局会停止。已使用的设备应继续保留自己的工作目录、布局、身份文件和安装收据。

构建和主机验证记录见 `dynamic-storage-update.json` 及 `reference/dynamic-storage`。新容量在第二台平板的启动、Data 挂载及跨重启持久化仍需实测；主机检查通过不代替设备验收。
