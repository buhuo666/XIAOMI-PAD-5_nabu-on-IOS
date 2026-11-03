# 项目进展

更新：2026-11-03，Asia/Shanghai。

目标：小米平板 5（nabu），XNU 开源基线 8796.121.2，iPadOS 16.5／20F66，普通 arm64。

## 已完成

- 建立独立工作目录和 Git 工程，下载 23 个固定提交的源码仓库；清单在 `configs/sources.lock.json`。另记录 21 条 UniXNU gitlink 与 19 个图形补丁的哈希，见 `docs/SOURCE-BASELINE.md`。
- 经已授权 root ADB 读取设备信息。设备报告 nabu／SM8150，当前 Android 15，活动槽位 A，bootloader unlocked。
- 保存六个 UFS LUN 的主备 GPT，校验头部和分区数组 CRC，并确认主备一致。原始备份保存在本地 `backup/gpt`。
- 确认旧项目区域为 `nabu_esp` 4 GiB + `nabu_system` 60 GiB，共 64 GiB；用户已授权回收，当前登记了准确边界，尚未格式化。
- 从 Apple CDN 的 20F66 IPSW 提取 KernelCache、DeviceTree、StaticTrustCache，记录 ZIP CRC 和文件 SHA-256。
- 编译 Apple LZFSE 解码器，取得原版 arm64 内核与 229 条 prelink 组件记录。
- HakiOS 8796 补丁在固定 Apple 8796.121.2 源码上通过 `git apply --check`。
- 完成 FDT 与 Linux 内存资源交叉核对：扣除固定 no-map 预留后，两者逐字节一致。高地址连续 11 GiB 尚未选作 XNU 管理窗口，见 `docs/DEVICE-MEMORY.md`。
- 保存本机七个 Adreno 固件文件，设备端与主机 SHA-256 一致，四个必需文件匹配 nabu 参考记录。
- 首轮 macOS／Xcode 16.4 的 GitHub Actions 参考内核构建取得两个 arm64 Mach-O，完整构建因 131 个缺失导出符号失败；见 `docs/FIRST-BUILD.md`。
- 计算原版 20F66 的三阶段声明依赖闭包：23／36／37 项，记录与 HakiOS Mini 服务的归属冲突，见 `docs/KEXT-COMPOSITION.md`。
- 完成 5,602,053,020 bytes IPSW 的完整 ZIP CRC 和 SHA-256 校验，提取 OS、Cryptex SystemOS 与对应 trust cache。
- 还原 3 个 ZBM 压缩文件，保存 50 个用户态分析文件。44 个缓存文件齐全，2,619 个镜像头为普通 arm64；47 个代码文件的原始 CodeDirectory 分块哈希和 trust-cache 成员关系通过检查。见 `docs/USERLAND-20F66.md`。
- 完成 131 个缺失导出的逐项归因：94 个 DriverKit 生成层、17 个 UAT、18 个 Apple 平台接口、2 个缺 ARM 实现的 pmap 查询。见 `docs/EXPORTS-8796.md`。
- 从原版 kext 显式 KASLR 指针表定位到 8 个 GOT 引用位置、5 个参考内核缺项：基础存储涉及 3 个，显示触摸再增加 2 个。此检查不覆盖完整指令重定位及 ABI；见 `docs/KEXT-INTERFACES-20F66.md`。
- 新 Actions `41646722684` 实测找到了 Xcode 16.4 的真实 IIG（DriverKit-427.100.5），17 份实现文件均已生成。默认生成代码引用旧版 IORPC 没有的 `kernelContent`，导致编译失败，未产生新内核。
- Actions `41648024252` 完成 8 组 IIG deployment-target 测量，生成文件全部相同。随后 `41649343964` 的消息布局兼容层编译通过全部 17 份实现，生成两个新内核，94 个生成层缺项全部消失；剩余 37 项仍使完整构建失败。下载后的产物哈希、34 份生成记录和变换输出已复核；见 `docs/IIG-COMPATIBILITY.md`。
- 新内核与原版同名外部定义从 5,731 增至 5,825；原版独有从 137 降至 43。选定原版 kext 的显式指针复测中，三阶段均为 0 个缺同名候选、0 个地址歧义；尚不代表重定位和 ABI 兼容。
- 完成 29 个原版 kext 的有限 B/BL 与标准 stub 检查：17 处 BL 经 8 个 GOT 连接上述 5 个接口；独立 LLVM 核对全部 99,926 个编码候选及关键 stub 的地址计算。35 个常量编码单列、2 个 Libm 位置仍未决，见 `docs/KEXT-BRANCHES-20F66.md`。

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

1. 核对原生 IIG 实现与 20F66 的消息 ID、回调和类布局；判断剩余 37 个导出及 6 个额外原版接口的实际消费者。
2. 扩展原版组件的指令重定位、初始化入口和已有同名接口的实际行为证据。
3. 按服务归属拆分 8796 平台补丁，建立 nabu 的最小配置。
4. 补齐选定配置所需的工具链与源码依赖，形成实际 nabu 构建。

当前 Actions 产物只用于验证 8796 的源码编译；尚未形成 nabu 专用可启动内核、ADT 或安装镜像。设备端本轮执行的是读取和主机保存，未重启、刷写或调整分区。
