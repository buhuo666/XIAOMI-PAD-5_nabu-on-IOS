# GPU224 跨电脑、跨平板部署准备包

新设备现在可在部署前选择容量：先按 [动态容量说明](README-动态容量.md) 运行 `00-select-capacity.cmd`，再继续下面流程。ESP 固定 4GiB，系统区域 10GiB，日志 1GiB，其余给 Data；无选择文件时沿用旧 64GiB 布局。

2026-11-12 早期启动反馈更新：若停在绿/蓝/橙三色条，见 [早期启动诊断](README-早期启动诊断.md)。`prepare_chain.py` 现支持 `--checkpoint` 和 `--config`；默认仍为 0，使用原 GPU224 配置。

cp01 后仍无 handoff 的补充反馈：见 [云端核对结果和 ESP 比对方法](回复-cp01与handoff缺失-20261112.md)。不要手填 ADT 的 DRAM 地址。

适用目标：小米平板 5，代号 **nabu**，用户已说明目标机为 12GB 内存、Bootloader 已解锁、Android 已 root。存储容量和分区从目标机扫描，不照抄原测试机的 LBA。

**当前状态：可迁移的运行工具、GPU224 公共文件、系统下载/提取入口和只读扫描已备齐。它还不是“只有 Android 的平板一键安装包”。本项目没有经过验证的离线缩小/重建 Android userdata 工具；首次分区执行步骤必须根据目标扫描结果完成。下面明确标出这个停点。**

本包没有连接或操作原测试平板，也没有在第二台平板验证过启动。新机的屏幕/触控、无线固件和 Android 版本仍需核对。随包工具已改为从新机扫描记录读取 A/B 活动槽并保持不变，不要求切换槽位。

## 1. 复制什么到另一台电脑

复制 **整个 GPU224-Deployment-Kit 文件夹**，建议放到 `C:\Nabu224` 或其他本地 NTFS 目录。不要只复制 boot.img，也不要拆散子目录。

| 目录/文件 | 内容 |
|---|---|
| `host/python` | 随包 Python 运行环境，仅需运行，无需另装 Python 或 pip |
| `host/platform-tools` | ADB、Fastboot 和配套 DLL |
| `host/7zip` | 用于把原版压缩 OS DMG 提取为原始 APFS |
| `host/apfs` | Windows 原生空白 APFS 格式化器、检查器及对应源码 |
| `artifacts/nabu-firmware/boot.img` | GPU224 使用的 BootShim/UEFI 临时入口 |
| `artifacts/nabu-efi` | 与 GPU224 清单对应的 UniXNU 和 DarwinBoot |
| `artifacts/nabu-dynamic-storage` | 支持所选容量且兼容旧布局的新内核和链接报告 |
| `artifacts/nabu-gpu-ready-v223` | 原始 GPU224 内核与报告，保留对照 |
| `artifacts/nabu-bootstrap-gpu-v224-context-timer` | GPU224 bootstrap 与对应报告，含本轮需要的移植运行组件 |
| `firmware` | 原基线 nabu 板级固件；使用前核对目标硬件/固件 |
| `data-selected` | 运行容量选择入口后生成的所选容量空白 APFS Data 元数据 |
| `data-seed` | 未选容量时沿用的旧 49GiB 空白 Data 元数据 |
| `tools` | 本地提取、目标扫描、身份准备、安装/部署和日志工具 |
| `reference/original-tools` | 移植前的工具源码，仅供对照，不作为跨机器入口 |
| `apps/NabuFrameBench.ipa` | GPU224 对应的 FrameBench 测试应用，需另行安装 |
| `system` | 使用者下载并提取后生成的 OS/SystemOS 文件存放处；出包时不含系统镜像 |

不打包旧平板的 ADT、完整 Data、配对记录、Image4 软件密钥、无线 MAC、蓝牙个性化 NVM 或 RMTFS 分区快照。新目标首次安装必须生成自己的这些输入；之后该目标的密钥和身份文件需要保留。

使用的电脑需要能够识别目标的 Android ADB 和 Fastboot 接口。Windows USB 驱动未捆绑；本包提供的 adb.exe/fastboot.exe 不能替代设备驱动。可先运行 `host\platform-tools\adb.exe devices` 确认，平板上批准 USB 调试和 root 请求。

## 2. 先扫描目标，不改分区

在另一台电脑只连接**准备安装的目标平板**，保持 Android 启动完成、USB 调试可用、root 可用。双击：

```text
01-scan-target.cmd
```

或者在包根目录 PowerShell 中执行：

```powershell
& .\host\python\python.exe -X utf8 .\tools\scan_target.py
```

扫描会读取：机型、内存、Android 版本、活动槽、UFS 容量/扇区、分区表、主备 GPT、RTC/SoC 身份和触控相关日志。不会执行分区写入、格式化、重启或临时引导。

输出：

- `device/target/partition-plan.json`：实际容量、userdata 几何、所选容量的布局建议、是否具备已有布局。
- `device/target/inventory.json`、`hardware-summary.txt`：设备条件与硬件信息。
- `backup/gpt/<时间>/`：目标机自己的主备 GPT 备份。

已有扫描不会被覆盖。再次扫描可使用 `--output device/scan-after-partition` 等新的目录。

**现在只有 Android 的目标，先完成这一节，然后回传 partition-plan.json、inventory.json 和 hardware-summary.txt，以确定首次分区执行方案。不要把旧测试机的 GPT 备份或 reclaimed-region.json 写入新机。**

## 3. 首次分区：必须先处理的独立阶段

后续已存在的安装器要求：

| 分区 | 名称 | 容量 | 格式/用途 |
|---|---|---:|---|
| sda35 | nabu_esp | 4GiB | FAT32，保存 EFI、内核、ADT、bootstrap |
| sda36 | nabu_system | 所选总容量 − 4GiB | 项目布局，包含 10GiB 系统区域、总容量 − 15GiB Data、1GiB 日志 |

扫描器在识别到标准 userdata 尾部布局时，会按目标机实际扇区和尾部位置计算建议边界。**这只是规划，不是已经执行或验证过的缩容。Android 文件系统里显示的空闲空间，不等于可以直接改 GPT 的空闲扇区。**

执行首次分区前必须确定：

1. 目标机用户数据已经独立备份；GPT 备份不包含 Android 用户数据。
2. 使用适用于目标机、可使 `/data` 完全离线的环境，确定 userdata 文件系统/加密情况和可用工具。
3. 选择并验证保留数据的缩容方法，或者在用户明确接受清空 Android 数据后采用重建 userdata 的方法。**本包不承诺无损缩容，也不默认授权清空数据。**
4. 从目标扫描生成分区变更，保留其余分区和引导槽；准备对应的 Android 恢复方案。
5. 创建上述两分区并格式化仅 nabu_esp，然后回到目标 Android，重新扫描主备 GPT、挂载状态和分区实际范围。

本包没有向正在运行的 Android userdata 尾部直接写分区表的命令，也没有提供猜测出来的 `sgdisk`/`resize.f2fs` 命令。**首次分区没有完成前，停止在此，不执行第 5 节及之后的设备写入。第 4 节的主机下载和提取可以独立进行。**

## 4. 使用者自行下载原始系统并提取

固定输入是 **iPadOS 16.5 / 20F66，iPad7,11 / j171ap**：

```text
iPad_10.2_16.5_20F66_Restore.ipsw
```

项目记录的 Apple CDN 地址：

```text
https://updates.cdn-apple.com/2023SpringFCS/fullrestores/032-85073/CCE27BB2-DF15-4DA8-80E0-C9B885DBA725/iPad_10.2_16.5_20F66_Restore.ipsw
```

本次整理没有重新下载该归档；下载入口使用项目固定 URL，提取时以固定 BuildManifest 和 APFS 内容校验确认输入。不要替换成其他版本或其他 iPad 型号。

文件预期大小 `5,602,053,020` bytes；原完整文件 SHA-256：

```text
468840ab760dcb27158b68e4ebc057dfac3a2b9d943451143a89df4e628e1504
```

可用浏览器自行下载，也可使用随包下载脚本。需要代理时显式指定目标电脑自己的代理地址，例如：

```powershell
& .\host\python\python.exe -X utf8 .\tools\fetch_full_ipsw.py --proxy http://127.0.0.1:19999
```

这个示例端口只有在目标电脑确实运行该代理时才适用；也可省略 `--proxy` 使用目标电脑环境的网络设置。下载脚本保存位置由 `configs/firmware.json` 决定。

下载完成后，将 IPSW 拖到 `02-import-system.cmd`，或执行：

```powershell
& .\host\python\python.exe -X utf8 .\tools\import_system.py --ipsw 'C:\Downloads\iPad_10.2_16.5_20F66_Restore.ipsw'
```

提取器选择 j171ap Erase identity，读取 OS 和 Cryptex1,SystemOS。OS 经 7-Zip 提取 `3.apfs`，不会把 Apple DMG 外层 GPT 当作 nabu 分区内容；SystemOS 本身就是 raw APFS。对新提取文件检查大小、NXSB 几何和固定 SHA-256，然后生成：

```text
system/20F66-OS.apfs             5,068,816,384 bytes
system/20F66-SystemOS.apfs       2,663,383,040 bytes
system/transfer-files.json
system/import-receipt.json
```

下载和提取同时保留原件及中间件，建议主机预留至少 25GB 空间。提取失败会保留 `system/import-work` 以便检查；不要把 `.part`/中间件当成成功结果。

本包不需要原版 trustcache 可选 sidecar，GPU224 的部署清单未使用它。若提取后移动了包目录，运行 `tools/prepare_transfer_manifest.py` 更新清单中的本机路径。

## 5. 绑定已准备好的新机布局

**仅限第 3 节已完成，且重新扫描报告为 existing-layout-candidate。**

```powershell
& .\host\python\python.exe -X utf8 .\tools\scan_target.py --output device/scan-after-partition
& .\host\python\python.exe -X utf8 .\tools\bind_existing_layout.py --scan device/scan-after-partition --accept-existing-layout
```

绑定工具只在电脑上保存新目标的 inventory、原始 system 首部和分区范围；不写设备。它使用扫描得到的目标分区 GUID/LBA，绝不会复用旧机授权清单。每台平板使用一份独立工作目录。

以下命令中的 `backup/gpt/<本次扫描目录>` 必须替换为该目标重新扫描生成的真实路径；它不是可原样运行的占位符。

## 6. 安装系统到新机 nabu_system

目标回到 Android、root 可用。先把使用者下载的系统暂存到 Android 普通文件目录：

```powershell
& .\host\python\python.exe -X utf8 .\tools\prepare_transfer_manifest.py
& .\host\python\python.exe -X utf8 .\tools\stage_ipados_payload.py --manifest system/transfer-files.json --inventory device/target --output log/device/stage-target --apply
```

该步仅上传到 `/data/local/tmp/nabu16/20F66`，不代表完成系统分区安装。Android `/data` 需有约 8.2GiB 以上暂存可用空间（两个镜像加工具要求的 1GiB 余量）。

先运行安装预检（不带 `--apply`）：

```powershell
& .\host\python\python.exe -X utf8 .\tools\install_ipados_windows.py --inventory device/target --gpt-backup 'backup/gpt/<本次扫描目录>' --data-bundle data-selected --staging-receipt log/device/stage-target/staging-receipt.json --output log/device/install-target
```

预检确认目标、范围和源文件后，首次写入命令为：

```powershell
& .\host\python\python.exe -X utf8 .\tools\install_ipados_windows.py --inventory device/target --gpt-backup 'backup/gpt/<本次扫描目录>' --data-bundle data-selected --staging-receipt log/device/stage-target/staging-receipt.json --output log/device/install-target --apply
```

已选择容量时使用 `data-selected`；没有选择文件的旧布局仍使用 `--data-bundle data-seed`。该命令会向已绑定的 nabu_system 写系统，并按所选容量初始化 Data；不会替你创建分区。首次安装成功收据为 `installed-and-readback-verified`；已有完整相同安装的复核收据为 `existing-installation-verified-data-preserved`，日志工具接受这两种完成状态。复核分支保留 Data；后续不要以重装方式清空已使用的 Data。

## 7. 准备新机身份和固件输入

先根据扫描得到的触控/面板日志核对 `firmware/nabu-touch/firmware.json` 的 NT36523/CSOT 基线；蓝牙 ROM 基线在 `reference/bluetooth-rom-reference.json`。不一致需要适配，不能仅因同名 nabu 就确认。

确认目标实际蓝牙地址（系统设置中查看；蓝牙应处于已开启且已初始化状态）。保持 Android Wi-Fi 使用设备永久地址，执行以下命令，并把示例地址替换为目标机真实值：

```powershell
& .\host\python\python.exe -X utf8 .\tools\prepare_target_identity.py --bluetooth-address 'AA:BB:CC:DD:EE:FF' --confirm-matching-board-firmware
```

工具只从目标读取永久 Wi-Fi MAC、SoC/RTC、GPU/无线固件和 RMTFS 快照，在主机生成新的软件 nonce key、蓝牙 NVM 和目标输入。固件和原基线不匹配时停止；不尝试套用旧机校准数据。若目标 ROM 中的文件路径不同，应先定位对应原文件再调整读取路径，不删除检查。

成功产生 `target-inputs/personalized/receipt.json`，状态为 `local-inputs-prepared`。这里仍不代表新机硬件启动已验证。整个 personalized 目录属于这一台设备，不随公共包分享；软件密钥首次生成后保持不变。

## 8. 准备新日志槽、生成 ADT 并部署 ESP

随包安装器在首次新安装分支中初始化 nabu_system 内的 1GiB 日志保留区；已有安装的复核分支不清理它。日志工具只接受全零的新槽，若已有日志必须先回收，不能直接覆盖。

```powershell
& .\host\python\python.exe -X utf8 .\tools\nabu_runtime_logs.py --prepare --slot 1 --kernel artifacts/nabu-dynamic-storage/kernel.native-apfs.macho --inventory device/target --gpt-backup 'backup/gpt/<本次扫描目录>' --installation-receipt log/device/install-target/installation-receipt.json --output log/device/prepare-001
```

先仅在电脑构建：

```powershell
& .\host\python\python.exe -X utf8 .\tools\prepare_chain.py --gpt-backup 'backup/gpt/<本次扫描目录>' --log-preparation log/device/prepare-001/preparation.json --output artifacts/target-chain-001
```

这个步骤用新机自己的身份/密钥/无线快照生成 ADT，配合 GPU224 公共文件，输出 `artifacts/target-chain-001/EFI` 和 `chain-manifest.json`。然后部署到新机已经存在的 FAT32 ESP：

```powershell
& .\host\python\python.exe -X utf8 .\tools\prepare_chain.py --gpt-backup 'backup/gpt/<本次扫描目录>' --log-preparation log/device/prepare-001/preparation.json --output artifacts/target-chain-001 --apply
```

保留命令输出的 `log/device/nabu-chain-<时间>/deployment.json` 路径。成功状态应为 `deployed-and-readback-verified`。部署工具备份将被替换的 ESP 文件，再逐项写入/回读，不格式化 ESP、不改变 GPT。

## 9. 临时启动

只有前面各步完成，才能从 Android 使用本轮新部署收据启动：

```powershell
& .\host\python\python.exe -X utf8 .\tools\run_nabu_temporary_boot.py --boot --gpt-backup 'backup/gpt/<本次扫描目录>' --deployment 'log/device/nabu-chain-<时间>/deployment.json' --output log/device/boot-001
```

工具会执行 `adb reboot bootloader`，核对 nabu、解锁和目标身份，然后执行 `fastboot boot`。不执行 `fastboot flash`、erase 或 set_active，也不额外先重启一次 Android。

Fastboot 的 `OKAY` 只说明发送/引导命令成功。实际验收包括显示、触控、USB、Data 挂载、GPU 工作和后续日志。GPU224 的 120Hz/675MHz 配置不等于已经证明全链 120fps。

新 Data 不含旧机已经安装的应用。`apps/NabuFrameBench.ipa` 需要在原生 USB/配对和应用安装通道可用后另装；本包没有捆绑 Apple 设备驱动或代替应用安装通道。先验收系统启动，不能以缺少 FrameBench 判定 GPU 启动失败。

## 10. 恢复 Android 与回收日志

手动恢复 Android 后，先回收本轮记录，再准备下次新槽。保持本轮主机目录和收据：

```powershell
& .\host\python\python.exe -X utf8 .\tools\run_nabu_temporary_boot.py --collect --gpt-backup 'backup/gpt/<本次扫描目录>' --output log/device/boot-001
```

回收工具保存 ESP handoff 信息与日志，校验后按原工具流程清理对应日志槽。若回收中断，保留所有文件和报错，不重复启动覆盖证据。下一次用新的 prepare/chain/boot 输出目录。

## 验证范围与当前待完成项

- 公共 GPU224 文件取自本地已部署轮次；只做文件存在/复制长度检查，没有重新进行已有文件的哈希审计。
- 本包携带的运行环境、CLI 帮助、依赖导入和容量规划的离线样例经过主机检查，详见 `package-check.json`。
- 动态容量内核的完整构建、链接和加载器检查已通过；Windows 上 32、64、128、256、512GiB 布局的空白 Data 格式化、APFS 检查及安装元数据合同已验证，详见 `reference/dynamic-storage`。主机验证不代替新设备启动与持久化验收。
- 新增工具尚未在目标平板执行；跨设备首次分区、驱动匹配、安装、启动和回收仍需目标实测。
- 最先需要的现场结果是目标 `partition-plan.json`、`inventory.json`、`hardware-summary.txt`。它们用于补齐原生 Android → 所需分区布局的执行步骤，而不是让用户猜存储容量。
