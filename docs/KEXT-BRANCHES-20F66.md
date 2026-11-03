# 20F66 kext 的 ARM64 分支与 GOT 接口链

日期：2026-11-03，Asia/Shanghai。

**17 处原版文本中的 BL 指令，通过逐指令匹配的标准 stub 和 GOT，指向此前定位的 5 个 DriverKit 接口。** 它们覆盖此前报告的全部 8 个缺项 GOT 位置。对 131 项历史构建缺项及额外 6 项的直接 B/BL 目标扫描没有精确命中；这不是“没有依赖”的结论，因为这 17 条 stub 链已经证明了间接连接。

此处的“缺项”固定指 Actions `41642015502 / attempt 2` 的旧参考内核，SHA-256 为 `e4d7c08ec80858b142f0ea17cd7d371eb2d6b29260619b2f27d8f53d19723b9b`。新构建 `41649343964 / attempt 1` 已为这 5 个接口提供唯一同名候选，原版指针复测通过；其消息协议和 ABI 尚未验证。构建适配另见 [IIG-COMPATIBILITY](IIG-COMPATIBILITY.md)。

## 输入、范围与复现

原版输入仍为 iPad7,11／20F66 的普通 arm64 slice：

```text
OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.arm64.macho
SHA-256 600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2
```

工程根目录执行：

```powershell
python -X utf8 tools/inspect_kext_branches.py --validate-with-llvm-mc
```

基础解析仅使用 Python 和本地固定 XnuPrelink 源码。可选的 `--validate-with-llvm-mc` 使用已安装的 LLVM；本机实际使用 Ubuntu-22.04 中的 LLVM 14.0.0，没有下载任何工具。输出为 `OS/ipados/16.5-20F66-iPad7_11/manifests/kext-branches.json`，记录全部原始候选、常量区、stub、监测符号清单及输入/解析器哈希。

源位置只取 29 个有代码 kext 中同时满足下列条件的 section：段可执行、`S_ATTR_PURE_INSTRUCTIONS` 置位、类型为 `S_REGULAR` 或 `S_SYMBOL_STUBS`、地址和大小按四字节对齐，并能通过原版顶层段映射到完整文件字节。没有把整个可执行段、字符串、GOT 或任意数据段作为指令扫描。

实测覆盖 29 个 `__text` 和 28 个 `__stubs`，共 **57 个 section、4,165,488 bytes**。原始字的 B/BL 判定为 `(word & 0x7c000000) == 0x14000000`，目标为当前指令地址加上符号扩展的 `imm26 << 2`。指令节标记不能证明每个字都可执行或可达，因此报告称其为编码候选。

## 分阶段计数

| 阶段 | 原始 B/BL 候选 | 完整哈希常量内候选 | 保留候选 | 指向标准 stub | 指向监测缺项的 BL | 涉及缺项 GOT |
|---|---:|---:|---:|---:|---:|---:|
| 存储与基本用户态 | 59,607 | 4 | 59,603 | 22,553 | 3 | 3 |
| CPU 显示与触摸 | 96,176 | 35 | 96,141 | 36,208 | 17 | 8 |
| GPU | 99,926 | 35 | 99,891 | 38,387 | 17 | 8 |

原始 GPU 集合有 66,268 个 BL 编码和 33,658 个 B 编码。排除已知常量后，99,889 个候选目标落回同一 kext 的指令节，2 个 Libm 候选无法映射到已知指令节。没有保留的跨 kext 直接分支或内核导出入口精确命中。

29 个 kext 没有可用于命名这些本地目标的符号表或 `LC_FUNCTION_STARTS`，因此“落在同一 kext 的指令节”不会被记成某个已恢复函数。对于可能的内核非入口目标，工具保留顶层函数起点表区间和相对偏移，明确下一起点不等于已证明的函数结尾；本次没有这样的命中。

## 常量与未决位置

固定 `src/XnuPrelink/emit_prelink.py` 记录了已知内嵌常量的完整 SHA-256。工具只在范围完整且哈希相等时标记常量；前缀相同不足以排除候选，也没有照搬 17.x 地址。

本次匹配 9 个范围，共 6,784 bytes，包含 35 个 B/BL 编码。原始记录仍全部保留，`excluded_literal_id` 指向相应范围及哈希：

| 组件 | 常量文件偏移 | bytes | 内含 B/BL 编码 |
|---|---|---:|---:|
| corecrypto | `0x11b51e0` | 256 | 1 |
| corecrypto | `0x11b95d0` | 256 | 1 |
| Libm | `0x12d6410` | 2,160 | 9 |
| Libm | `0x12d7964` | 2,188 | 11 |
| Libm | `0x12d82c8` | 1,088 | 9 |
| Libm | `0x12d88ec` | 212 | 1 |
| Libm | `0x12d90f0` | 56 | 1 |
| AppleFSCompressionTypeZlib | `0x2134100` | 528 | 1 |
| AppleFSCompressionTypeZlib | `0x213cfe0` | 40 | 1 |

例如 SHA-256 常量中的 `0x14292967` 恰好符合 B 编码。按指令解释会虚构 corecrypto 到其他 kext 的边；这些字必须和真实分支分开。

下列 2 个 Libm 位置没有匹配已知完整哈希，仍保留为未决编码，没有将其认定为真实控制流或新增常量范围：

| 文件偏移 | 字值 | 按 B/BL 公式得到的目标 |
|---|---|---|
| `0x12d74d4` | `0x96540c13` | `0xffffffeffee62520` |
| `0x12d74ec` | `0x9499342c` | `0xfffffff007fac59c` |

## 17 条 BL → stub → GOT 链

28 个 `__stubs` 中共有 3,056 个条目，`reserved2` 均为 12，全部逐指令匹配以下模式：

```asm
adrp x16, <GOT 所在页>
ldr  x16, [x16, #偏移]
br   x16
```

解码同时要求寄存器均为 x16、LDR 为 unsigned-offset 64-bit 形式、BR 字值精确匹配。计算出的槽必须位于同一 kext 的 `__DATA_CONST,__got`，按八字节对齐，并出现在原版 `_PrelinkLinkKASLROffsets`。最终目标取自原始镜像的槽值，并通过原版内核导出地址精确命名。这不等于观察了运行时 GOT 或方法执行。

| 原版使用组件 | 目标接口简写 | BL 数 | 首个 BL 文件偏移 | stub 文件偏移 | GOT 文件偏移 |
|---|---|---:|---|---|---|
| IOStorageFamily | `IOService::Stop_Invoke` | 1 | `0x1104f68` | `0x1107460` | `0x2606e70` |
| IOStorageFamily | `IOService::Start_Invoke` | 1 | `0x1104fe8` | `0x110746c` | `0x2606e78` |
| IOStorageFamily | `IOService::_Dispatch` | 1 | `0x1105058` | `0x11074a8` | `0x2606ea0` |
| IOHIDFamily | `OSAction::_Dispatch` | 8 | `0x13f2df4` | `0x13f65d4` | `0x26a1d08` |
| IOHIDFamily | `IOService::_Dispatch` | 3 | `0x13f0864` | `0x13f66a0` | `0x26a1dc8` |
| IOHIDFamily | `IOService::Stop_Invoke` | 1 | `0x13f31a4` | `0x13f664c` | `0x26a1d90` |
| IOHIDFamily | `IOService::Start_Invoke` | 1 | `0x13f347c` | `0x13f6658` | `0x26a1d98` |
| IOHIDFamily | `IOService::SetProperties_Invoke` | 1 | `0x13f3454` | `0x13f6670` | `0x26a1da8` |

完整 17 个 BL 位置、指令字、stub 的三条指令、GOT 指针及原始 mangled name 位于报告的 `interesting_retained_records`。这补充了 [KEXT-INTERFACES-20F66](KEXT-INTERFACES-20F66.md) 的静态指针证据。

监测清单中的其余 126 个历史缺项、额外 6 个原版独有符号，在本次直接 B/BL 和已支持 stub 链中未出现；每个名称的原版地址及命中列表均保存在 `watchlist`。这不覆盖虚调用、其他 BR/BLR、条件分支、ADRP 后续消费者或运行时构造的目标，不能据此删接口或宣称无依赖。

## 验证与边界

已用独立 LLVM 14.0.0 解码器核对全部 **99,926** 个原始 B/BL 编码的助记符与有符号位移，并核对上述 **8** 个关键 stub 的全部指令和 GOT 地址计算，结果一致。验证的是编码和操作数算术；LLVM 同样能把常量字解码成指令，不能用解码成功证明它是可达代码。

报告没有生成重定位补丁、没有写入新内核或设备。还需要核对修复后导出实现的消息结构和 ABI、其余寻址指令及数据流，以及本机实际启动与调用行为。
