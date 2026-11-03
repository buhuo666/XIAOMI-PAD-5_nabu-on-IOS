# 20F66 剩余平台接口的实际消费者

日期：2026-11-03，Asia/Shanghai。

**使用 Actions `41659076371 / attempt 1` 候选复测全部 211 个有代码 kext，30 个剩余原版独有符号中有 7 个出现明确指针与标准 stub 消费者：4 个由 IONVMeFamily 使用，3 个由 IOSkywalkFamily 使用。两者都不在当前 37 项组件闭包内。** 这些连接包含 7 个 GOT 位置和 17 条文本分支；另外 23 个符号在本次覆盖形式中没有精确引用，不能据此认定无用途。

## 固定输入与执行

| 输入 | SHA-256 |
|---|---|
| 原版 iPad7,11／20F66 普通 arm64 slice，8796.122.4~1 | `600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2` |
| 当前 Actions `41659076371 / attempt 1` 的 unstripped 内核，含 IIG 修复、共享 pmap 配置及 11 个查询入口 | `ec2df9cb80756852b82a1e0dd86e25203ab401994fd31bf6e86183cecab51f78` |
| 历史 Actions `41649343964 / attempt 1` 的 unstripped 内核，8796.121.2 + IIG 兼容层 | `c385da03d5a258d6bbf189c05fd357f0b69d6219484c2bb5299a25bacb623444` |

脚本从原版与当前候选重新计算外部定义名差集，得到 **30** 项；与历史 131 项构建失败名称交叉后为 **24** 项，其余为此前已登记的 **6** 项，没有无法归因的新缺项。24 项与本次 CI 保存的 `export-failure.json` 名单逐项相同；没有使用过期的 131 项直接作为当前缺项清单。

缺项演变为原版独有 **43 → 41 → 30**、构建导出 **37 → 35 → 24**：先补齐两个 pmap 查询，再补齐 11 个仅限参考配置的查询入口。相对 `41655737937`，剩余 30 项的逐符号消费者记录保持相同；`nvme_ppl_get_desc` 从缺项集合消失，因此当前报告少 1 个 GOT／stub 和 2 条 BL。该接口在供体中的消费者并未消失，它现在已有候选定义。实现语义见 [PMAP-QUERIES-8796](PMAP-QUERIES-8796.md) 和 [PLATFORM-SEMANTICS-20F66](PLATFORM-SEMANTICS-20F66.md)。

在工程根目录执行：

```powershell
python -X utf8 tools/inspect_platform_consumers.py --candidate artifacts/ci/41659076371-attempt-1/xnu8796-reference-9/artifacts/8796-reference/mach.development.bcm2837.unstripped --output log/ci/github/41659076371/attempt-1/platform-consumers.json --validate-with-llvm-mc
```

当前输出：`log/ci/github/41659076371/attempt-1/platform-consumers.json`。报告逐项保留 30 个符号的原版地址、当前缺失状态、指针、stub、分支位置、使用模块和是否属于当前闭包。无命中项保留空列表及明确的有限搜索结论。

历史报告 `OS/ipados/16.5-20F66-iPad7_11/manifests/platform-consumers-20F66.json` 保持原样，SHA-256 仍为 `44c0f81a290c23a9d2963b0b42d88badda914e266397ad8e880cb373e1ed24a6`。脚本现在要求显式传入 `--candidate` 和 `--output`，避免误用历史候选或覆盖旧报告。

## 覆盖边界

| 项目 | 实测 |
|---|---:|
| 供体组件记录总数 | 229 |
| 可执行 kext | 211 |
| 当前选定组件总数 | 37 |
| 当前选定的可执行 kext | 29 |
| 显式 KASLR 指针 | 383,870 |
| 无法归属 kext 的表内指针 | 0 |
| 指令节 | 421 |
| 指令节总 bytes | 21,851,348 |
| 原始 B/BL 编码候选 | 469,297 |
| 完整哈希已知常量内编码 | 38 |
| 匹配标准 x16 stub | 16,771 |
| 未支持的 stub 记录 | 0 |
| 因不满足指令节规则而单列的可执行／混合节 | 0 |
| 30 项的精确 GOT 指针 | 7 |
| 30 项的直接 B/BL 符号起始地址命中 | 0 |
| 30 项的 B/BL → stub → GOT 链 | 17 |

指令节选择和 stub 解码规则与 [KEXT-BRANCHES-20F66](KEXT-BRANCHES-20F66.md) 一致：仅扫描可执行、按四字节对齐、完整文件映射且标记 `PURE_INSTRUCTIONS` 的 `S_REGULAR`／`S_SYMBOL_STUBS` section。标准 stub 必须精确匹配 `ADRP x16 → LDR x16,[x16,#imm] → BR x16`，槽位还必须位于同一模块的 `__DATA_CONST,__got`，并出现在显式 KASLR 表中。

全量扫描匹配了 12 个已知常量范围，共 7,880 bytes。范围、完整哈希及模块内计数都保存在报告中，不能凭常量前缀排除数据。没有运行所分析的 kext。

### 三阶段闭包与实际扫描量

以下是全量扫描中属于各阶段的子集；阶段累积包含前一阶段，不能把三行相加。声明边数从本次供体元数据重新计算，并与原闭包报告逐项核对。

| 阶段 | 组件记录 | 有代码 kext | 声明依赖边 | 显式指针 | 指令节 | 指令节 bytes |
|---|---:|---:|---:|---:|---:|---:|
| 存储与基本用户态 | 23 | 16 | 110 | 28,910 | 32 | 2,419,492 |
| CPU 显示与触摸 | 36 | 28 | 191 | 61,640 | 55 | 4,011,944 |
| GPU | 37 | 29 | 201 | 64,606 | 57 | 4,165,488 |

每阶段均含 7 个 KPI 元数据记录；后两阶段另含无独立可执行体的 `IOHIDEventDriverSafeBoot`。因此最大闭包是 **37 = 29 个有代码 kext + 7 个 KPI + 1 个无代码匹配组件**。三阶段在当前 30 项覆盖形式中均未观察到消费者；这不是 29 个 kext 没有其他内核依赖的判断。

## 7 个有消费者的符号

下列偏移均针对原版 thin arm64 文件，不能用于外层 IPSW、IM4P 或其他固件。GOT 中的每个八字节值精确等于原版对应内核导出地址。

| 符号（省略单个 Mach-O 前导下划线） | 使用组件 | GOT 文件偏移 | stub 文件偏移 | 文本分支数 | 首个文本分支文件偏移 |
|---|---|---|---|---:|---|
| `pmap_iommu_alloc_contiguous_pages` | IONVMeFamily | `0x28c73f0` | `0x208e600` | 3 BL | `0x205c720` |
| `pmap_iommu_init` | IONVMeFamily | `0x28c73f8` | `0x208e60c` | 2 BL | `0x205c6fc` |
| `pmap_iommu_ioctl` | IONVMeFamily | `0x28c7400` | `0x208e618` | 8 BL | `0x205c7ac` |
| `pmap_iommu_map` | IONVMeFamily | `0x28c7408` | `0x208e624` | 1 BL | `0x205ca58` |
| `kern_packet_set_fpd_command` | IOSkywalkFamily | `0x25fb8c0` | `0x10ef4fc` | 1 B | `0x10cc3b4` |
| `kern_packet_set_fpd_context_id` | IOSkywalkFamily | `0x25fb8c8` | `0x10ef508` | 1 B | `0x10cc3ac` |
| `kern_packet_set_fpd_sequence_number` | IOSkywalkFamily | `0x25fb8d0` | `0x10ef514` | 1 B | `0x10cc3a4` |

前 4 项属于剩余 24 项构建导出失败集合；后 3 项属于额外的 6 个原版独有符号。完整 **14 BL + 3 B** 的指令字和偏移都在每个符号的 `branch_sites` 内。B 是静态无条件分支，这里不把它计作 BL 或声称已观察到运行时调用。

### IONVMeFamily 的平台归属

原版 `com.apple.iokit.IONVMeFamily` 的 personality 元数据显示：

- 多个 AppleANS2／AppleANS3 controller 以 `RTBuddyService` 为 provider。
- `NVMeSEPNotifier` 以 `AppleSEPManager` 为 provider。
- `AppleEmbeddedNVMeController` 以 `IOPCIDevice` 为 provider，包含 Apple PCI 匹配值 `0x2002106b`。
- 同一 family 还带 `GenericNVMeSSD`／`IONVMeController` 的通用 PCI NVMe 匹配项，因此不能把整个 bundle 简化成只有一个 Apple 专用驱动。

其 `OSBundleLibraries` 有 **17 个直接声明依赖：6 个 KPI、11 个非 KPI**，包括 AppleNANDConfigAccess、AppleSMC、AppleA7IOP、AppleEmbeddedPCIE、RTBuddy 及 IOStorageFamily；17 不是递归依赖闭包大小。当前 nabu 闭包选择的是 IOStorageFamily 及板级 UFS 路线，没有选择 IONVMeFamily。这解释了为什么全量供体中能找到这些接口消费者，而当前 29 个选定可执行 kext 中没有这些表内引用。

上述结论来自模块元数据及具体引用位置；它没有证明是哪一个 controller 类执行上述 BL，也没有把 Apple NVMe／PPL 的语义等同于 Qualcomm UFS／SMMU。

### IOSkywalkFamily 的范围

`com.apple.iokit.IOSkywalkFamily` 是供体网络框架模块。其 metadata 有 IOSkywalkEthernetInterface、IOSkywalkNetworkInterface、IOSkywalkInterface 的匹配项，后两项要求 `IOBSD` 资源。其 `OSBundleLibraries` 有 **8 个直接声明依赖：6 个 KPI，以及 IONetworkingFamily、mDNSOffloadUserClient-Embedded**；8 不是递归依赖闭包大小。它不在当前存储／显示触摸／GPU 的 37 项闭包中；今后扩展网络功能时仍需重新考虑这些引用。

## 23 个未观测到覆盖形式引用的符号

下表的结果统一为：**在全部 211 个 kext 的显式 KASLR 指针、精确 B/BL 入口和已支持的标准 stub 链中，未发现该符号的精确引用。** 不是源码、系统运行或所有可能寻址方式中的“无引用”判断。

| 集合 | 符号 |
|---|---|
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::gMetaClass` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::superClass` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::commitUnmaps` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::prepareFWUnmap` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::getPageTableEntry` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::setClientContextID` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::isPageFaultExpected` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::removeClientContextID` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::registerTaskForService` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::createMappingInAperture` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::getTotalPageTableMemory` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::map` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::doMap` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::unmap` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::doUnmap` |
| UAT，剩余导出失败 | `IOUnifiedAddressTranslator::taskDied` |
| UAT，剩余导出失败 | `vtable for IOUnifiedAddressTranslator` |
| IOMMU，剩余导出失败 | `pmap_iommu_iovmalloc` |
| IOMMU，剩余导出失败 | `pmap_iommu_iovmfree` |
| IOMMU，剩余导出失败 | `pmap_iommu_unmap` |
| 额外原版独有 | `ml_amcc_error_inject_register` |
| 额外原版独有 | `ml_dcs_error_inject_register` |
| 额外原版独有 | `ml_mem_fault_report_enable_register` |

C++ 名称在表中简写，报告保留完整 mangled name、反解签名和原版地址，不可据简写猜测 ABI。

## 可以据此推进的工作

当前闭包的消费者定位已经从“没有看到符号名”推进到对全部供体 kext 的指针与限定指令形式检查。7 个符号的已观测消费者位于当前闭包之外，为先做 nabu 最小启动和板级 UFS 提供了范围依据；这份报告不修改组件选择，不删除导出表，也不替代未实现的接口语义。

当前候选的剩余 24 项仍使完整 `make all` 失败。如何形成明确的平台导出契约，需要结合选定构建范围、未来功能和 ABI 约束单独决定。通用 BR／BLR、虚调用、条件分支、ADRP 的后续消费者、函数内部偏移引用和运行时构造目标均未完整分析；主内核自身的代码也不在本次消费者扫描范围内。

验证已完成：新候选实际全量运行；旧报告哈希保持不变；24 项与新 CI 缺项名单一致；7 个 GOT、7 个 stub 和 17 个文本分支的原始字节回读；独立 LLVM 14.0.0 核对这 17 条 B/BL 的有符号位移及 7 个 stub 的 GOT 地址算术；Python 语法检查通过。

工具自审补充了重复组件标识、闭包组件缺失、显式指针跨组件边界及声明边数不一致的检查；报告 schema 2 记录脚本本身的哈希、阶段扫描量及未归因差项。已知覆盖形式与解码规则没有扩大。本次复测不需要额外 macOS 原生工具，没有上传系统材料、预链接或操作设备。
