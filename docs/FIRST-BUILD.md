# 首轮 macOS 参考构建

日期：2026-11-03，Asia/Shanghai。

GitHub Actions 已实际编译并链接出 HakiOS 8796 的普通 arm64 内核。完整 `make all` 在后续导出表生成阶段失败，退出码为 2；这次构建不标记为通过，也不作为 nabu 启动镜像。

## 可复现身份

| 项目 | 值 |
|---|---|
| 仓库 | `buhuo666/XIAOMI-PAD-5_nabu-on-IOS` |
| 分支 | `nabu16-bootstrap` |
| 工程提交 | `4a1406e27e82679e21970d2e4e12ca9c53f652d5` |
| Actions run / attempt | `41642015502` / `2` |
| XNU | `c54f35ca767986246321eb901baf8f5ff7923f6a`，8796.121.2 |
| HakiOS | `96ffbc532e970f3540885755d457e401e04d4707` |
| 实际主机 | macOS 15.8.2（24H232），arm64 |
| 工具链 | Xcode 16.4（16F6），Apple clang 17.0.0 |
| 配置 | HakiOS open defconfig，`DEVELOPMENT_ARM64_BCM2837` |

首个 run `41641380279` 的源码选择名写错，未开始编译。修正后的 run `41642015502` 第一次执行因代理范围澄清而取消；第二次执行是本报告的完整结果。

## 产物

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `mach.development.bcm2837` | 16,937,392 | `a6a37823c5075c960e53b06dcd1449c926e562e4b0319650f0e65f054a9b992f` |
| `mach.development.bcm2837.unstripped` | 22,700,144 | `e4d7c08ec80858b142f0ea17cd7d371eb2d6b29260619b2f27d8f53d19723b9b` |

两者从 Actions 下载回本机后重新计算的大小和哈希均与构建报告一致。Mach-O header 为 `0xfeedfacf`、CPU type `0x100000c`、subtype `0`、file type `2`。版本字符串含 `xnu-8796.121.2-dirty`；dirty 来自按设计应用的 HakiOS 补丁。

本地产物位于 `artifacts/ci/41642015502-attempt-2/xnu8796-reference-2/artifacts/8796-reference/`。完整日志、状态、缺失符号表与本地校验结果位于 `log/ci/github/41642015502/attempt-2/`。

## 失败定位

失败目标为 `check_all_exports` 与 IOKit、Libkern、Private 的 symbolset 生成，共报告 **131 个不同的缺失导出符号**。日志没有 C/C++ 编译错误或内核链接的 undefined-symbol 错误。

HakiOS 的 `xnu-deps/host/bin/iig` 使用预生成 SDK 头文件；缺少对应 `iig-impl` 时生成空实现文件。缺失导出中包含 DriverKit RPC 方法。其他缺项包括 `IOUnifiedAddressTranslator` 与 Apple 平台的 pmap/DART/PPL 接口。后续逐项归因确认为 94 个生成层缺项和另外 37 个平台接口缺项，不能全部归因于一个 shim。

Apple `makedefs/MakeInc.top` 区分 `build` 和 `all/config` 阶段：本次内核链接已完成，失败发生在后处理。现阶段保留完整 `all` 的真实失败状态，没有删导出列表、添加空函数或忽略错误来换取绿色 CI。

另用 `tools/compare_kernel_symbols.py` 比较两个内核本体 LC_SYMTAB 中的外部定义：原版 20F66 有 5,868 个，参考内核有 23,086 个；同名 5,731 个，原版独有 137 个。结果保存在本地 `symbol-comparison.json`。此比较不包含各嵌入 kext 自身的符号表，也不检查函数语义或类布局；137 项与上述导出检查的 131 项属于不同口径，不能混用或据此宣称二进制兼容。

## 下一步适配范围

参考构建证明主机工具链、固定源码和链接过程能够工作。接下来以 nabu 启动需求拆分平台补丁，处理原版 20F66 组件实际调用的接口；不把通用 HakiOS 的 Mini 显示/APFS 与原版对应组件直接混合。

此产物没有本机 ADT、DarwinBoot 装载布局或 nabu 启动验证。设备本轮未重启或刷写。

后续已完成 [131 项逐项归因](EXPORTS-8796.md) 和 [原版组件实际指针引用](KEXT-INTERFACES-20F66.md)。[原生 IIG 实验](IIG-COMPATIBILITY.md) 另行记录；本报告保留首次产物和失败口径。
