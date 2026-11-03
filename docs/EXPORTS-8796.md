# 8796 参考构建导出缺项归因

日期：2026-11-03，Asia/Shanghai。对象是 Actions `41642015502 / attempt 2`，工程提交 `4a1406e27e82679e21970d2e4e12ca9c53f652d5`。

本报告记录首轮 131 个缺失导出的归因，并与该次两个内核的 `LC_SYMTAB` 交叉核对。**94 项来自不完整的 DriverKit 生成层，35 项对应公开源码缺少实现的 UAT／Apple 平台接口，2 项在公开树中只有 x86_64 实现。** 后续 IIG 兼容层已消除其中 94 项，剩余 37 项；完整复编译结果见 [IIG-COMPATIBILITY](IIG-COMPATIBILITY.md)，选定组件的实际引用见 [kext 接口报告](KEXT-INTERFACES-20F66.md)。

## 输入和复现

- Apple XNU：`c54f35ca767986246321eb901baf8f5ff7923f6a`，`8796.121.2`。
- HakiOS：`96ffbc532e970f3540885755d457e401e04d4707`。
- 原版：20F66，`8796.122.4~1/RELEASE_ARM64_T8010`，thin arm64 SHA-256 `600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2`。
- 参考：`mach.development.bcm2837.unstripped`，SHA-256 `e4d7c08ec80858b142f0ea17cd7d371eb2d6b29260619b2f27d8f53d19723b9b`。

```powershell
python -X utf8 tools/analyze_missing_exports.py
```

脚本使用 `llvm-cxxfilt --strip-underscore`；本机未找到时使用 Ubuntu-22.04 内现有工具，不下载依赖。报告保存在 `log/ci/github/41642015502/attempt-2/export-attribution.json`，包括全部 131 项的原始名称、反解名称、导出文件与行号、IIG 声明或源码检索位置、原版／参考符号状态和后续动作。它复用 `compare_kernel_symbols.py` 的薄 Mach-O 符号读取逻辑。

检索边界为这份固定 Apple 树的 **4,983 个受 Git 管理的文本文件**。下文的“缺少实现”指这个边界内的结果，不是对 Apple 私有源码或其他 XNU 版本的结论。

## 分类结果

| 类别 | 项数 | 本次观察 | 后续处理 |
|---|---:|---|---|
| DriverKit／IIG 生成不完整 | 94 | `.iig` 定义存在；shim 只提供一份不完整聚合实现，其余生成实现为空 | 先探测真实 IIG，再以固定 `.iig` 同时生成头文件和 RPC 实现 |
| `IOUnifiedAddressTranslator` | 17 | 类名仅出现在 `Private.arm64.exports`，没有类声明或实现 | 从保留 kext 的真实引用确认需求，设计 nabu 的映射接口 |
| `pmap_iommu_*` | 7 | 精确函数名仅出现于 `Private.arm64.exports` | 核对 DMA／SMMU 所需语义，不把 Apple IOMMU API 等同于 Qualcomm 实现 |
| DART／SART／NVMe／UAT 描述符等 | 11 | 精确函数名仅出现于 `Private.arm64.exports` | 先确定哪些 Apple 平台消费者会被移除或替换 |
| pmap 查询接口 | 2 | `pmap.h` 有声明，`osfmk/x86_64/pmap.c` 有实现，未找到 ARM 实现 | 根据 nabu 实际能力和策略实现，并核对调用方含义 |

20 个 C 接口的逐项归属：

| 归属 | 符号（省略 Mach-O 前导下划线） |
|---|---|
| IOMMU，7 项 | `pmap_iommu_alloc_contiguous_pages`、`pmap_iommu_init`、`pmap_iommu_ioctl`、`pmap_iommu_iovmalloc`、`pmap_iommu_iovmfree`、`pmap_iommu_map`、`pmap_iommu_unmap` |
| 平台描述符与转换，11 项 | `nvme_ppl_get_desc`、`sart_get_desc`、`t6000dart_get_desc`、`t6000dart_vo_tte`、`t8020dart_get_desc`、`t8020dart_vo_tte`、`t8110dart_get_desc`、`t8110dart_max_translation_levels`、`t8110dart_vo_tt_index`、`t8110dart_vo_tte`、`uat_get_desc` |
| 查询，2 项 | `pmap_cs_configuration`、`pmap_has_iofilter_protected_write` |

`pmap_has_iofilter_protected_write` 的公开声明说明它查询设备是否支持寄存器级 MMIO 访问控制；x86_64 实现返回 false。`pmap_cs_configuration` 返回部分代码签名策略配置位，声明特别指出 0 不保证处于默认或安全配置。nabu 的实现需要忠实表达实际状态，不能只为消除导出错误加入常量返回值。

## DriverKit 的具体断点

构建路径可以从源码直接串起来：

1. HakiOS `xnu-env.sh:16` 把 `xnu-deps/host/bin` 放到 PATH 前面；`hakios.patch:1987`、`:1993` 把 XNU 的绝对 `/usr/bin/xcrun` 改成 PATH 中的 `xcrun`。
2. HakiOS `host/bin/xcrun` 查询目标工具时优先返回其同目录的 `iig`。
3. `host/bin/iig:15` 把 macOS 13.3 SDK 的既有头文件复制给构建；`:16–17` 对存在的 `<name>.iig.cpp` 使用本地替代文件，否则生成空翻译单元。
4. 固定 HakiOS 树仅提供 `iig-impl/OSObject.iig.cpp`；17 个 `.iig` 输入中，另外 16 个没有对应实现文件。
5. XNU `iokit/DriverKit/Makefile:61` 要求生成头文件和实现，`iokit/conf/files:13` 起将这些 `.iig.cpp` 编入内核。CI 日志中的 17 个 IIG 步骤并不能说明真实 RPC 代码已生成。

94 项包括 RPC 方法包装、`*_Invoke`、`_Dispatch`，以及由 `IOUserClient::KernelCompletion` 声明导出的 action 子类元数据。源码中不少 `*_Impl` 已存在；报告中 74 条缺失导出可关联到同名基础方法的 `_Impl` 出现位置。它们与 RPC 包装不是同一个符号，单纯存在 `_Impl` 不能填补消息校验、分发、对象引用和回调 ABI。

| 类／生成类 | 缺项数 |
|---|---:|
| IOService | 34 |
| IODataQueueDispatchSource | 14 |
| IODispatchSource | 7 |
| IOUserClient | 6 |
| IOInterruptDispatchSource、IOMemoryDescriptor、OSObject | 各 4 |
| IOBufferMemoryDescriptor、IODMACommand、IODispatchQueue、IOUserServer | 各 3 |
| OSAction_IOUserClient_KernelCompletion（含 vtable） | 3 |
| IOMemoryMap、IOServiceNotificationDispatchSource、OSAction | 各 2 |

还有一项必须纳入后续审计的既有行为：HakiOS 的 `OSObject.iig.cpp` 已带有 **44 个返回 `kIOReturnUnsupported` 的替代函数，以及 21 个直接跳转到 `_Impl` 的桥接入口**。这 44 个替代函数与 21 个入口都能在参考内核符号表中找到；44 个中又有 27 个与原版导出同名。它们是上游参考代码的原有内容，本次没有新增或替换。符号计数相同仍可能掩盖缺失的 DriverKit 行为。

## 131 项与 137 项的关系

原先两份报告的口径不同：131 是 `make all` 的导出检查失败集合，137 是原版内核拥有而参考内核没有的外部定义集合。本次通过原始 mangled name 精确映射，确认 **131 项全部是 137 项的子集**，对这两个固定文件成立。

余下 6 项为：

- `kern_packet_set_fpd_command`
- `kern_packet_set_fpd_context_id`
- `kern_packet_set_fpd_sequence_number`
- `ml_amcc_error_inject_register`
- `ml_dcs_error_inject_register`
- `ml_mem_fault_report_enable_register`

这 6 个精确名称在本次公开源码搜索中没有结果，包括公开导出表。仍需从原版组件调用关系判断是否属于选定路线的必要接口。当前证据不能把某个缺项直接归因于 `8796.121.2` 与 `8796.122.4` 的版本变化。

## 最小下一步

1. 原生工具已实测存在：Xcode 16.4 提供 `DriverKit-427.100.5`，全部 17 个输入均能生成实现。默认输出与 8796 的 `IORPC` 不匹配；已测 8 组 deployment-target 输入均不改变该输出。详情见 [IIG-COMPATIBILITY](IIG-COMPATIBILITY.md)。
2. Actions `41649343964` 已通过限定消息布局分支的兼容层编译全部 17 个实现并链接出新内核。94 个生成层缺项全部消失；剩余 37 个导出仍使 `make all` 以 2 退出。原版独有定义从 137 降至 43，恰为剩余 37 项加上述 6 项。
3. 原生生成层替换了旧 shim 输入，先前 44 个 Unsupported 替代入口与 21 个直接桥接入口的名称在新内核中均存在。后续仍需核对其消息处理、回调与原版调用方；同名计数不代替行为证据。
4. 对最小存储、显示触摸、GPU 三阶段保留的原版组件，定位另外 37 项及额外 6 项的实际引用；此后再实现所需接口、替换平台消费者或明确不支持的功能。
5. `BCM2837` 宏没有启用 Apple `PMAP_CS`／`XNU_MONITOR`，但本次搜索表明许多实现根本不在公开树中。启用这些宏不是已有证据支持的修复办法。

本报告保留该次构建的失败结论；未删改导出表、未添加桩函数。后续原生 IIG 构建结果记录在 [IIG-COMPATIBILITY](IIG-COMPATIBILITY.md)。
