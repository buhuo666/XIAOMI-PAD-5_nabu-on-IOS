# 20F66 kext 接口：符号表与已记录指针

日期：2026-11-03，Asia/Shanghai。

**原版 kext 中已定位的 5 个旧参考内核缺项，在 IIG 兼容层构建中全部有唯一同名候选。** 旧构建的存储阶段缺 3 个，显示触摸阶段缺 5 个；新构建的存储、显示、GPU 三阶段均为 0 个缺同名目标、0 个地址歧义。以下先保留旧构建的定位证据，再记录新构建复测。完整导入、重定位和 ABI 尚未验证。

## 输入与复现

工程根目录执行：

```powershell
python tools/inspect_kext_symbols.py
```

脚本复用固定 `src/XnuPrelink/native_prelink.py` 的 Mach-O、地址映射、OSUnserialize 和内核导出解析，不调用预链接写入器，也不修改任何原版字节。

| 输入 | SHA-256 |
|---|---|
| `OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.arm64.macho`，原版 8796.122.4~1 | `600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2` |
| `artifacts/ci/41642015502-attempt-2/xnu8796-reference-2/artifacts/8796-reference/mach.development.bcm2837.unstripped`，8796.121.2 HakiOS 参考构建 | `e4d7c08ec80858b142f0ea17cd7d371eb2d6b29260619b2f27d8f53d19723b9b` |

本地输出：

- `OS/ipados/16.5-20F66-iPad7_11/manifests/kext-symbols.json`：模块表字段、分阶段结果、每个内核目标的别名/候选地址，以及全部 64,606 个选定指针的位置和目标。`pointer_records.columns` 定义紧凑行格式；文件偏移以十进制记录，地址为十六进制。
- 同目录 `kext-metadata-20F66.json`：选定 37 项的完整 prelink 元数据，包含 personalities；原始二进制字段以显式 base64 对象保存。

每份报告记录原版内核、参考内核、闭包和解析器的文件哈希。偏移均针对上述普通 arm64 slice，不适用于外层 IM4P、fat Mach-O 或其他版本固件。

## 为什么不能直接比较 kext 的未定义符号

选定集合包含 29 个有代码的 kext、7 个 `OSKernelResource` 和 1 个 codeless bundle。

29 个真实 kext 的 `LC_SYMTAB` 四个字段均为 0，`LC_DYSYMTAB` 十八个字段也均为 0；所有 section 的 `nreloc` 为 0，保留的 `LC_SEGMENT_SPLIT_INFO` 数据长度同样为 0。因此不能把 `nundefsym = 0` 解释成没有外部依赖，也不能用这些表给出完整的导入符号清单。

7 个 KPI 是内核接口元数据，本脚本根据 `OSKernelResource` 跳过普通 kext 解析。它们的紧凑占位内容不能作为独立 Mach-O 或本工程的可装载 kext 使用。

例如 IOStorageFamily 的嵌入头位于文件偏移 `0x9b7280`，IOHIDFamily 位于 `0xa9e940`。报告保留各 `LC_SYMTAB`、`LC_DYSYMTAB` 命令的真实文件偏移，便于逐项核对零字段。

## 显式指针表能够证明什么

原版 `_PrelinkLinkKASLROffsets` 包含 **383,870** 个四字节偏移；加上四字节计数，共 **1,535,484 bytes**。脚本以原版 `__PRELINK_TEXT` 的 VM 地址为基准，读取表中每个选定位置的八字节指针。

组件归属来自原版全部 211 个有代码 kext 的非 `__LINKEDIT` VM 段。当前这些区间互不重叠。指向组件之外的地址，仅在与原版内核外部定义的地址精确相等时命名；随后按这些名称查询参考内核，保留其实际候选地址。

| 阶段 | 有代码 kext | 选定指针 | 指向内核导出 | 内核唯一目标 | 缺同名候选 | 候选地址歧义 |
|---|---:|---:|---:|---:|---:|---:|
| 存储与基本用户态 | 16 | 28,910 | 19,059 | 1,495 | 3 | 0 |
| CPU 显示与触摸 | 28 | 61,640 | 38,683 | 1,767 | 5 | 0 |
| GPU | 29 | 64,606 | 40,455 | 1,778 | 5 | 0 |

其余指针指向组件。当前三个阶段的这些目标都在各自声明闭包内，且选定指针中未遇到无法命名或归属的目标。这只证明表内位置可解释，不证明指令引用、动态调用和完整依赖也都已覆盖。

## 5 个缺项的具体位置

下列 8 个位置都位于相关 kext 的 `__DATA_CONST,__got`。读取该文件偏移的八字节值，等于表列的原版内核地址；原版内核符号表在该地址给出相应名称。参考内核没有同名外部定义。

| 接口简写 | 原版内核地址 | 使用组件 | 指针文件偏移 |
|---|---|---|---|
| `IOService::_Dispatch` | `0xfffffff00775b92c` | IOStorageFamily | `0x2606ea0` |
| `IOService::Start_Invoke` | `0xfffffff00775d618` | IOStorageFamily | `0x2606e78` |
| `IOService::Stop_Invoke` | `0xfffffff00775d70c` | IOStorageFamily | `0x2606e70` |
| `OSAction::_Dispatch` | `0xfffffff00775b650` | IOHIDFamily | `0x26a1d08` |
| `IOService::_Dispatch` | `0xfffffff00775b92c` | IOHIDFamily | `0x26a1dc8` |
| `IOService::Start_Invoke` | `0xfffffff00775d618` | IOHIDFamily | `0x26a1d98` |
| `IOService::Stop_Invoke` | `0xfffffff00775d70c` | IOHIDFamily | `0x26a1d90` |
| `IOService::SetProperties_Invoke` | `0xfffffff00775dcbc` | IOHIDFamily | `0x26a1da8` |

完整 Mach-O 符号名如下，签名不能只按上表的简写实现：

```text
__ZN8OSAction9_DispatchEPS_5IORPC
__ZN9IOService9_DispatchEPS_5IORPC
__ZN9IOService12Start_InvokeE5IORPCP15OSMetaClassBasePFiS2_PS_E
__ZN9IOService11Stop_InvokeE5IORPCP15OSMetaClassBasePFiS2_PS_E
__ZN9IOService20SetProperties_InvokeE5IORPCP15OSMetaClassBasePFiS2_P12OSDictionaryE
```

这 5 个缺项与参考构建的 131 项导出检查失败是不同口径：这里从选定原版 kext 的具体指针位置出发，证明哪些缺项已被实际二进制引用。它们可用于安排修复优先级，不能据此删除其他导出或直接生成“已兼容”的预链接镜像。

## codeless HID 元数据

`com.apple.iokit.IOHIDEventDriverSafeBoot` 实测没有 executable 字段，有 7 个 personality，均由 `com.apple.iokit.IOHIDFamily` 提供实现，provider 均为 `IOHIDInterface`。其中 `HID Pointing/Consumer/System Control Driver` 的 `DeviceUsagePairs` 包含 `DeviceUsagePage = 13`，完整匹配条件已保存在元数据报告中。

这能说明供体已有对应 HID 匹配声明；不能证明 nabu 板级触摸服务已经发布匹配的 IOHIDInterface、报告描述符或事件数据。实际触摸链仍须按板级实现验证。

## IIG 兼容层构建复测

Actions `41649343964 / attempt 1` 的新候选为 `artifacts/ci/41649343964-attempt-1/xnu8796-reference-5/artifacts/8796-reference/mach.development.bcm2837.unstripped`，SHA-256 为 `c385da03d5a258d6bbf189c05fd357f0b69d6219484c2bb5299a25bacb623444`。

```powershell
python tools/inspect_kext_symbols.py --candidate artifacts/ci/41649343964-attempt-1/xnu8796-reference-5/artifacts/8796-reference/mach.development.bcm2837.unstripped --output log/ci/github/41649343964/attempt-1/kext-symbols.json
```

复测仍读取相同原版固件和闭包，全部 64,606 个选定指针的位置、目标与归属保持一致。三个阶段的 1,495／1,767／1,778 个内核唯一目标均找到唯一同名候选。此前缺失的 5 个目标如下：

| 接口简写 | 新候选内核地址 |
|---|---|
| `OSAction::_Dispatch` | `0xfffffff007997adc` |
| `IOService::_Dispatch` | `0xfffffff0079983cc` |
| `IOService::Start_Invoke` | `0xfffffff007999b64` |
| `IOService::Stop_Invoke` | `0xfffffff007999c34` |
| `IOService::SetProperties_Invoke` | `0xfffffff00799a21c` |

这些地址只属于上述候选文件，没有写回原版指针或生成预链接镜像。完整构建仍有 37 个导出缺项；本次选定指针没有直接命中它们，不能据此证明它们不会被其他指令、动态调用、初始化或后续组件使用。

旧报告仍在原始 OS manifests 目录；新报告和独立元数据副本保存在该 Actions 的本地日志目录。构建、导出计数和产物验证见 [IIG-COMPATIBILITY](IIG-COMPATIBILITY.md)。

后续 [B/BL 与 stub 检查](KEXT-BRANCHES-20F66.md) 又在原版文本中定位到 17 处 BL，经标准 stub 连到全部 8 个 GOT 位置。它为这 5 个接口补充了静态调用链证据，仍没有执行原版 kext。

## 下一步

1. 已恢复 IOService/OSAction 生成实现并复测 8 个 GOT 位置；继续分别核对请求结构、调用路径和 20F66 签名。
2. 检查新生成实现及此前同名入口的实际行为，追踪剩余平台接口的其他引用方式。
3. 继续分析 ARM64 直接分支、指令编码地址、vtable/类布局、初始化入口及跨组件重定位。当前报告没有提供完整重定位覆盖率，也没有运行或启动这些 kext。

验证已完成：脚本对实际固件完整运行；单独回读上述 8 个文件偏移验证原始指针值；核对 29 个符号表、动态符号表、section relocation 与 split-info 的零字段；Python 语法编译通过。
