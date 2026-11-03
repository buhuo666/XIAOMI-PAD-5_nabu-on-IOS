# 20F66 原生分析与最新参考构建

日期：2026-11-03，Asia/Shanghai。

Actions **`41659076371 / attempt 1`** 已完成：源码编译、内核链接及原生 LLDB 静态分析产生可核对结果，完整 `make all` 仍因 **24 个缺失导出**失败。新内核的 11 个受限查询入口与供体逐字节相同，三个 IIG 空 reply 错误分支已恢复，pmap 旧查询读取共享代码签名配置。当前没有 nabu 启动镜像或设备启动结果。

## 构建身份与结果

| 项目 | 结果 |
|---|---|
| 仓库／分支 | `buhuo666/XIAOMI-PAD-5_nabu-on-IOS`／`nabu16-bootstrap` |
| 实际构建提交 | `1e53b512c839d8e334391147457069598ddd1d0c` |
| Actions | `41659076371 / attempt 1`，结论 `failure` |
| 原生分析步骤 | `success` |
| 原始 make 退出码 | `2` |
| 编译日志 | 无 C/C++ `error:` 或内核链接 undefined-symbol 诊断；导出检查报告 24 项 |
| 开源基线／参考板型 | XNU `8796.121.2`／`DEVELOPMENT_ARM64_BCM2837` |
| 原版供体 | iPad7,11／j171ap，iPadOS 16.5／20F66，实际 XNU `8796.122.4~1` |
| host | macOS Actions，Xcode 16.4；普通 arm64 目标 |

两份下载产物的大小、SHA-256 与 CI 的 `build-report.json` 一致，Mach-O header 均为 CPU `0x100000c`、subtype `0`、file type `2`：

| 产物 | bytes | SHA-256 |
|---|---:|---|
| `mach.development.bcm2837.unstripped` | 22,837,864 | `ec2df9cb80756852b82a1e0dd86e25203ab401994fd31bf6e86183cecab51f78` |
| `mach.development.bcm2837` | 17,040,560 | `41050f0f8bc012f90a017caed0a9887fc7faeba8329d1ede5a90674a4f1c1cb5` |

本地产物目录：`artifacts/ci/41659076371-attempt-1/xnu8796-reference-9/`。下面简写为“run9 产物目录”；它不是构建编号或可安装镜像名。

| 检查 | 首轮 shim | 原生 IIG 兼容层 | 两个 pmap 查询 | 最新受限汇编 |
|---|---:|---:|---:|---:|
| 缺失导出 | 131 | 37 | 35 | 24 |
| 与原版 5,868 个外部定义同名 | 5,731 | 5,825 | 5,827 | 5,838 |
| 原版独有定义 | 137 | 43 | 41 | 30 |

最新候选有 23,303 个外部定义。剩余构建缺项精确为 **17 个 IOUnifiedAddressTranslator 类符号 + 7 个 pmap_iommu 操作**；再加上此前记录的 6 个原版额外接口，构成 30 项差集。没有删除导出列表或隐藏 make 的失败退出码。

## 云端分析如何取得

Windows 当前 REA 原生 provider 不支持这个 ARM64 Mach-O。项目因此使用已有 macOS Actions 工具链执行 [analyze_20f66_ci.sh](../tools/analyze_20f66_ci.sh)：

1. 按固定来源下载 Apple 固件小成员，检查 KernelCache 的预期 SHA-256，使用固定 LZFSE 源码解码。
2. 根据 [native-analysis-20f66.json](../configs/native-analysis-20f66.json) 的 51 项调查入口，读取导出、section 与 `LC_FUNCTION_STARTS`，形成有长度上限的计划。
3. 使用 Xcode LLDB 创建静态 target，记录指令地址、原始字节、助记符及操作数。没有 launch、attach 或内核执行。
4. [inspect_iig_20f66.py](../tools/inspect_iig_20f66.py) 回读两个 Mach-O，核对所有被解码范围，再检查选定 IIG 常量和分支。已启用 `--require-legacy-reply-checks`。

固定原版 slice 为 48,087,040 bytes，SHA-256 `600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2`，UUID `45734ead-3ab7-330d-bacf-9c48ef9a9358`。它与开源基线的小版本不同，不以版本号接近推导兼容。

最新原版 **47 个代码范围／3,390 条指令**，候选 **21 个代码范围／1,904 条指令**。其余调查项包含数据定义或无定义项，不能将 51 当作已解码函数数。比如原版没有独立 `OSAction::Aborted_Impl` 导出，该逻辑在分派内可见。

| run9 产物目录内的记录 | SHA-256 |
|---|---|
| `log/ci/native-20f66/plan.json` | `1961e5bec92e48dc7ed7eb5f77838c7b35c3f2f5aef9ea1e4f2eb084629ab135` |
| `log/ci/native-20f66/instructions.json` | `2be5f5c6cba609c0b3dfdd20f29e3ed76a5aa747cb33a97b466bad23506c62b9` |
| `log/ci/native-20f66/iig-review.json` | `7f0565d0ffb763d7c9de80d7b2f2308dabc8f01ceb7a294e857fbde6ef8471b4` |
| `log/ci/native-20f66/tool.json` | `56e92bb548173defbc9e04e19c5920764ce2c12f79406a4de433823f2b0ae5e0` |

工具记录为 `lldb-1700.0.9.502`，LLDB SHA-256 `89c7d02af88f43932a4481027df291ebb38f53e2cd058e0bc876f53553e68ece`。产物归档保留静态分析记录和源码生成内核，没有归档原版系统镜像。

## IIG 修复及辅助调用

`Start_Invoke`、`Stop_Invoke`、`SetProperties_Invoke` 原本被新生成器的 `__builtin_assume(reply != NULL)` 优化掉 NULL 分支。兼容层只移除这三个有供体指令依据的假设，恢复生成代码已有的条件检查。云端与下载后检查均通过；34 份原生实现的本地重放也与归档适配结果相同。

| 消息 | 生成头与原版对应数值 |
|---|---|
| IOService Start | `0xab6f76dde6d693f2` |
| IOService Stop | `0x98e715041c459fa5` |
| IOService SetProperties | `0xd8a753ea156f9162` |
| OSAction Aborted | `0xbfb95094c657d68f` |

三个 Invoke 的 request 下限为 `0x6c`、reply 为 `0x3c`，descriptor count 与 objectRefs 均为 2，对象参数偏移为 `0x64`。三个回复的 method ID、flags=8、version `0x4da2b68d`、descriptor count=0 已核对。对应分派入口也保留 NULL 跳过 replySize 检查的分支。IOService 的 **53 个比较数值**（包括树阈值）和 OSAction 的 1 个比较数值相同；这不是所有消息处理行为相同的证明。

候选 `OSObject::_Dispatch` 在 `0xfffffff00799820c`，先调用消息转换函数，再通过 GOT 调用基类分派。本地回读 GOT `0xfffffff007206138` 得到 `0xfffffff007a47044`，唯一外部定义名为 `OSMetaClassBase::Dispatch(IORPC)`。目标 12 字节为 `e05880520000bc72c0035fd6`，返回 `0xe00002c7`／Unsupported。原版 `0xfffffff00775a800` 同样在消息转换调用之后返回这个常量。此检查确认静态 GOT 目标与返回值，没有证明两个消息转换函数完全等价。

候选 `OSAction::Aborted_Impl` 位于 `0xfffffff007a451e0`，56 bytes。可见对象 `+0x10` 的扩展状态、`+0x40` 原子标记及 `+0x20` handler 路径，与原版分派中的对应内联逻辑相符；尚未建立完整类布局或生命周期证明。

主机提取函数回归在既有 WSL Clang 14／x86_64／`-O2` 上各运行 39 例：6 组预期变化，其余 33 组一致。旧 NULL 输入违反 builtin assumption，其结果只描述该编译器；没有执行 NULL reply 加成功 handler 路径。详见 [IIG-COMPATIBILITY](IIG-COMPATIBILITY.md)。

## pmap 与 11 个查询入口

构建报告中的两个项目补丁哈希已与工作区文件回读比较：

| 补丁 | SHA-256 |
|---|---|
| `pmap-nonmonitor-queries.patch` | `3d5f5fb5976b55fba9461ae5d05efa5c1e0d1d2592a5661a0c1043ba3d3dbbb8` |
| `bcm2837-apple-iommu-query-returns.patch` | `7fea4ea21697c3041d48df1833d57c0384cf78e142d531d010845c95cb1b1571` |

两轮修复后构建 `41657999493` 与 `41659076371` 中，`pmap_cs_configuration` 都以 x0=NULL、x1=&栈配置调用 `0xfffffff007838b28` 的共享查询，随后返回所写配置。其入口 `0xfffffff007427ff4` 的完整 44 bytes SHA-256 为 `b881456c20f776163bb6699432b02cb62dc451a37e96ff44cfbe43da47bbac37`。这保留 DEVELOPMENT 的配置路径；原版 RELEASE 初始化为 0 不意味着候选应恒定返回 0。

11 个新增入口均仅限 BCM2837 普通 arm64、无 PMAP_CS／XNU_MONITOR。新内核中九个为 `mov x0,#0; ret`，两个为 `mov w0,#0; ret`，逐项匹配原版 8-byte 范围。这里没有推断私有 C 类型，没有写输出参数，也没有把返回 0 解释成 IOMMU 成功。详见 [PLATFORM-SEMANTICS-20F66](PLATFORM-SEMANTICS-20F66.md)。

7 个 IOMMU 操作仍未实现。尤其 `pmap_iommu_ioctl` 的 4-byte 导出入口跳到真实实现，分配路径还明确使用 16 KiB 对齐；均不能直接替换为零返回或照搬到拟定 4 KiB 内核。

## 消费者复测与记录

最新候选的存储／显示触摸／GPU 三阶段显式指针检查均为 **0 个缺同名目标、0 个地址歧义**。这只核对名字和地址映射，未完成原版 kext 重定位及 ABI 验证。

全部 211 个原版可执行 kext 的有限扫描覆盖 383,870 个显式 KASLR 指针和 421 个指令节。当前 30 项差集中，7 个符号有 7 个 GOT／stub 和 17 条文本分支：IONVMeFamily 4 个接口、14 条 BL；IOSkywalkFamily 3 个接口、3 条 B。两模块均在当前 37 项闭包之外。其余 23 项只是在显式指针、精确 B/BL 入口和标准 x16 stub 形式中未命中，不能声称无依赖。

`nvme_ppl_get_desc` 已有候选定义，因此其原有 1 个 GOT 和 2 条 BL 从“剩余缺项消费者”计数中移出；供体引用本身仍然存在。其余 30 项的逐符号记录与前轮一致。完整范围及 LLVM 独立解码核对见 [PLATFORM-CONSUMERS-20F66](PLATFORM-CONSUMERS-20F66.md)。

本地复查目录为 `log/ci/github/41659076371/attempt-1/`：

| 文件 | 用途 |
|---|---|
| `status.json`、`artifacts.json` | GitHub 返回的 run、step、产物身份 |
| `local-kernel-verification.json` | 两个 Mach-O 的大小、哈希及 header |
| `export-failure.json` | 实际导出失败名单、make 退出码、编译诊断检查 |
| `iig-compat-verification.json` | 34 份生成实现重放与六处假设变换 |
| `iig-native-review.json` | 下载后复跑的范围、常量与分支检查；内容与云端报告一致 |
| `platform-native-review.json` | 11 个入口、pmap 调用、OSObject GOT／helper 的原始证据 |
| `symbol-comparison.json`、`kext-symbols.json` | 定义差集与三阶段显式指针结果 |
| `platform-consumers.json` | 全供体有限引用扫描；SHA-256 `22eb607369990f0d4cbd822ffb5ed0f1337c2c67d7cff8e7cfd73dcd88040c3b` |

这些日志和原始镜像保留在本地忽略目录；文档保存关键数值，工具保存在仓库。复测命令见 [BOOTSTRAP](BOOTSTRAP.md)。

## 后续边界

本轮确认的是参考内核的编译结果、有限机器码语义和供体引用形式。完整 IIG ABI、类布局、初始化、重定位、UAT／IOMMU 状态、nabu loader／ADT／CPU／UFS 仍需独立处理。旧项目的 85 个硬件恢复文件仅作为 [历史调查参考](ABANDONED-KERNEL-REFERENCE.md)，没有加入这些构建输入或用作硬件正确性证据。
