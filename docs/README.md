# 文档与研究资料

当前实施目标：nabu + XNU 8796.121.2 + iPadOS 16.5（20F66）。

## 现有资料

| 文档 | 用途 |
|---|---|
| [项目进展](STATUS.md) | 当前完成项、实际构建结果与下一步 |
| [开工与构建命令](BOOTSTRAP.md) | 固定源码、固件提取、Actions 操作 |
| [源码基线](SOURCE-BASELINE.md) | 23 个仓库、gitlink 和图形依赖记录 |
| [本机内存](DEVICE-MEMORY.md) | 扩容内存和固定保留区的实测核对 |
| [首轮参考构建](FIRST-BUILD.md) | 两个参考内核产物与导出检查失败 |
| [20F66 用户态](USERLAND-20F66.md) | ZBM 解压、完整缓存组、原始代码哈希 |
| [131 个导出缺项](EXPORTS-8796.md) | DriverKit、UAT 和平台接口逐项归因 |
| [原生 IIG 实验](IIG-COMPATIBILITY.md) | 17 份实现编译通过，三个空 reply 分支已云端复核 |
| [原生分析与最新构建](NATIVE-ANALYSIS-20F66.md) | Actions 41659076371、缺失导出 131→24、静态分析范围 |
| [pmap 查询](PMAP-QUERIES-8796.md) | 共享代码签名配置与非 monitor 能力查询 |
| [平台接口语义](PLATFORM-SEMANTICS-20F66.md) | 11 个受限查询返回与 7 个未实现的 IOMMU 操作 |
| [平台接口消费者](PLATFORM-CONSUMERS-20F66.md) | 全部 211 个 kext 的有限引用检查 |
| [弃用内核硬件参考](ABANDONED-KERNEL-REFERENCE.md) | 85 个恢复文件、版本线索与触摸待验证问题 |
| [原版组件组成](KEXT-COMPOSITION.md) | 声明依赖与服务归属拆分 |
| [原版组件实际接口](KEXT-INTERFACES-20F66.md) | KASLR 指针取证与 5 个接口候选恢复 |
| [原版组件分支链](KEXT-BRANCHES-20F66.md) | 17 处 BL→stub→GOT，常量与未决编码 |
| [当前工作路线](D:/github-IOS/nabu-XNU8796-iPadOS16.5工作路线.md) | M0～M8 的任务、产物、验收与近期任务 |
| [基线清单草案](D:/github-IOS/nabu-ipados16.5-基线清单.json) | 已选版本和待验证输入；目前不是可构建配置 |
| [工作路线来源索引](D:/github-IOS/nabu-ipados16.5-工作路线来源索引.json) | 固定源码与原始证据的路径、版本和哈希 |
| [nabu 选型研究](D:/github-IOS/nabu双系统移植路线建议.md) | 供体、内核、扩容与后续双启动研究 |
| [四项目路线对比](D:/github-IOS/四项目技术路线对比与启动链整合.md) | 各参考项目的启动与图形技术路线 |

实施记录存于本目录；选型和最初工作路线仍在上一级研究目录，原始基线草案保留为规划记录。当前状态以 STATUS 和对应实测报告为准。

## 后续文档命名

- `启动交接契约.md`：loader、ADT、boot_args 和内核入口约定。
- `20F66-ABI适配记录.md`：原版组件和 8796 的接口适配。
- `M2-最小启动验收.md`：阶段结论，引用实际 run ID 和 build ID。
- `问题记录.md`：问题、证据、修复版本和复测结果。

设备参数放 `device`，一次测试的原始记录放 `log`，可长期复用的分析与结论放在这里。
