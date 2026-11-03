# 项目进展

更新：2026-11-03，Asia/Shanghai。

目标：小米平板 5（nabu），XNU 开源基线 8796.121.2，iPadOS 16.5／20F66，普通 arm64。

## 已完成

- 建立独立工作目录和 Git 工程，下载 19 个固定提交的源码仓库；清单在 `configs/sources.lock.json`。
- 经已授权 root ADB 读取设备信息。设备报告 nabu／SM8150，当前 Android 15，活动槽位 A，bootloader unlocked。
- 保存六个 UFS LUN 的主备 GPT，校验头部和分区数组 CRC，并确认主备一致。原始备份保存在本地 `backup/gpt`。
- 确认旧项目区域为 `nabu_esp` 4 GiB + `nabu_system` 60 GiB，共 64 GiB；用户已授权回收，当前登记了准确边界，尚未格式化。
- 从 Apple CDN 的 20F66 IPSW 提取 KernelCache、DeviceTree、StaticTrustCache，记录 ZIP CRC 和文件 SHA-256。
- 编译 Apple LZFSE 解码器，取得原版 arm64 内核与 229 条 prelink 组件记录。
- HakiOS 8796 补丁在固定 Apple 8796.121.2 源码上通过 `git apply --check`。
- 准备 macOS 15／Xcode 16.4 的 GitHub Actions 参考内核构建。

## 固件实测结果

| 项目 | 结果 |
|---|---|
| 产品／build | iPad7,11／j171ap，16.5／20F66 |
| Mach-O 架构 | CPU type `0x100000c`，subtype `0`，普通 arm64 |
| 原版内核版本 | Darwin 22.5.0，`xnu-8796.122.4~1/RELEASE_ARM64_T8010` |
| 原版内核 UUID | `45734ead-3ab7-330d-bacf-9c48ef9a9358` |
| arm64 slice SHA-256 | `600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2` |
| APFS | 2142.122.2 |
| IOSurface | 336.50.1 |
| IOGPUFamily | 65.40.15 |
| IOHIDFamily | 2.0.0 |

开源内核继续使用选定的 `8796.121.2`。原版固件实际为 `8796.122.4~1`，这项差异需要通过接口分析处理，不能按同系列版本直接判定兼容。

格式与版本结论来自本地解包和 Mach-O／OSUnserialize 解析。REA 确认了 thin Mach-O 格式，但当前 Windows 原生分析 provider 不支持这个 ARM64 Mach-O，尚未取得反编译证据。

## 正在推进

1. 在 GitHub Actions 上运行 HakiOS 8796 参考构建，形成可复用工具链和失败定位记录。
2. 展开 UniXNU／SoC 剩余组件与工具链依赖。
3. 提取 20F66 系统卷，核对 dyld、用户态和卷布局。
4. 按服务归属拆分 8796 平台补丁，建立 nabu 的最小配置。

当前 Actions 产物只用于验证 8796 的源码编译；尚未形成 nabu 专用可启动内核、ADT 或安装镜像。设备端本轮执行的是读取和主机保存，未重启、刷写或调整分区。
