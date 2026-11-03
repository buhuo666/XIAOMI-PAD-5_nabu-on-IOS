# 20F66 用户态提取与静态校验

日期：2026-11-03，Asia/Shanghai。

已完成 iPad7,11／j171ap 的 16.5／20F66 用户态材料提取：50 个选定文件，包括 launchd、dyld、SpringBoard 入口、版本/应用 plist，以及全部 44 个 dyld 缓存文件。47 个代码文件的原始 CodeDirectory 分块哈希和原版 trust cache 成员关系均通过检查；缓存中的 2,619 个镜像头均为普通 arm64。

这是后续适配使用的原版材料，尚未形成可启动根文件系统。没有在 nabu 上运行这些用户态程序。

## 输入与文件位置

完整 IPSW 为 `iPad_10.2_16.5_20F66_Restore.ipsw`，5,602,053,020 bytes，SHA-256：

```text
468840ab760dcb27158b68e4ebc057dfac3a2b9d943451143a89df4e628e1504
```

该归档已完成完整 ZIP CRC 与所选 BuildManifest 哈希校验。工作目录内的原版材料都在 `OS/ipados/16.5-20F66-iPad7_11/` 下：

| 路径 | 内容 |
|---|---|
| `original/` | 完整 Apple IPSW |
| `extracted/096-04157-076.dmg` | BuildManifest 的 OS，保存为原始 APFS 镜像 |
| `extracted/096-03702-078.dmg` | Cryptex1,SystemOS，包含共享缓存 |
| `extracted/Firmware/` | 原版 StaticTrustCache、SystemTrustCache 及解出的 payload |
| `userland/os/` | 选定的系统入口与 plist |
| `userland/systemos/` | 共享缓存及 Cryptex 版本 plist |
| `manifests/userland-extraction.json` | 50 项的 APFS 声明大小、实际大小、SHA-256、压缩输入记录 |
| `manifests/userland-report.json` | 签名分块校验、trust 条目、缓存 UUID/映射、完整镜像目录 |

OS 与 SystemOS 的 `SystemVersion.plist` 都报告 16.5／20F66；两者 SystemImageID 不同，分别保存在报告中。主机提取目录不是保持 APFS 元数据、seal、权限及扩展属性的 rootfs 副本。

## 恢复 ZBM 压缩文件

7-Zip 24.09 对以下三个文件返回 `Unsupported Method`。它已经提取压缩数据，但将其放入 NTFS 的 `com.apple.decmpfs` 与 `com.apple.ResourceFork` 备用数据流，普通数据流长度仍为 0：

| 文件名后缀 | 还原后的 bytes |
|---|---:|
| `.28.dyldlinkedit` | 19,218,432 |
| `.42.dyldlinkedit` | 326,057,984 |
| `.symbols` | 585,220,096 |

`tools/extract_userland.py` 使用锁定 HakiOS 源码中的 `libzbitmap.c`，在 WSL 编译共享库，按 decmpfs type 14 的块表解压。它保存压缩头/资源流的大小与哈希，核对输出大小；后续再由原版 CodeDirectory 的每块哈希核对解压内容。没有根据文件名或“工具退出了”判定成功。

脚本仅接续明确属于这些 ZBM 成员的 7-Zip 错误，其他提取错误保留失败。日志在 `log/host/userland/`；解码中间材料在 `build/userland-zbm/`，原始归档和 APFS 镜像始终可用于重做提取。

## 缓存与入口结果

| 项目 | 实测结果 |
|---|---|
| 缓存文件总数 | 44：主缓存 + 42 个子缓存 + 1 个本地符号缓存 |
| 运行时缓存大小 | 2,657,402,880 bytes，43 个文件 |
| 含本地符号文件的总大小 | 3,242,622,976 bytes |
| 主缓存 UUID | `ab05dde5-28af-3a21-a7f0-b47fe15bebda` |
| 镜像目录 | 2,619 条，每条都有唯一文件映射与普通 arm64 Mach-O 头 |
| 缓存 OS version | 16.5.0 |
| 未滑动 shared region 起点 | `0x180000000` |
| shared region 声明大小 | 2,786,017,280 bytes |
| 子缓存核对 | 42 个文件名、UUID、VM offset 全部匹配 |
| 本地符号缓存 | UUID 与主缓存的 symbolFileUUID 匹配 |
| 原版 trust cache | Static：2,509 条；SystemOS：61 条，均为 version 2 |

三个磁盘入口的 `LC_BUILD_VERSION` 都是 platform 2、minimum OS 16.5.0、SDK 16.5.0：

| 入口 | bytes | UUID |
|---|---:|---|
| `/sbin/launchd` | 525,088 | `babc0c9d-bf6e-3513-8ba8-c8e876f3119a` |
| `/usr/lib/dyld` | 922,912 | `57d51d04-7ac8-335b-95aa-734c226e2e9e` |
| SpringBoard.app/SpringBoard | 112,048 | `40ec75f0-76c1-3deb-85f1-39369b09e9d5` |

这三个入口记录的直接依赖路径都能在缓存目录中找到。SpringBoard 入口进一步加载缓存中的 `SpringBoard.framework/SpringBoard`，不能只取应用目录里的小入口文件就认为用户界面材料完整。

共核对 197,853 个 CodeDirectory 代码块。三个磁盘入口使用 4 KiB 签名块，44 个缓存文件使用 16 KiB 签名块；所有缓存映射也满足 4 KiB 对齐。签名块大小、VM 页大小和设备 DMA 粒度是不同约束，这些结果不证明整个 4 KiB 内核运行契约已兼容。

检查使用原版 trust cache 中的 cdhash，不包含 Apple 证书链、特殊签名槽、APFS seal 或启动时的 AMFI 策略验证。当前 Windows REA 的 Mach-O 检查工具要求 macOS，原生分析 provider 也不支持此 ARM64 Mach-O，因此本报告使用本地格式解析和哈希证据，没有反编译或运行时证据。

## 复现

以下命令在工程根目录执行，使用已下载固件和固定源码，不下载新材料：

```powershell
python tools/extract_os_image.py
python tools/extract_os_image.py --component Cryptex1,SystemOS
python tools/extract_os_image.py --component Cryptex1,SystemTrustCache
python tools/extract_userland.py
python tools/inspect_userland.py
```

如果 7-Zip 提取已经完成而解压阶段被中断，可以先运行 `extract_userland.py --repair-only`。它继续处理现有数据并重新核对每个选定文件。

报告仅在命令成功时更新；失败重跑会保留上一次成功报告。判断本轮结果应结合命令退出码、日志、报告生成时间和输入收据哈希。

格式偏移在 `configs/dyld-format.json`，由固定 Apple dyld 头文件的结构体经过 C `offsetof/sizeof` 取得；配置记录头文件哈希和 nabu 来源提交。签名检查复用固定 nabu 快照的 `audit_apple_inputs.py` 中的通用 CodeDirectory 解析器，16.5 的镜像、trust 条目、地址、UUID 均来自本次实际输入。

下一步是处理 [kext 的实际接口引用](KEXT-INTERFACES-20F66.md)，随后完成 nabu 平台、原版服务归属和初始化顺序。上述原版材料不会自动提供 SM8150 驱动或一套可直接启动的卷布局。
