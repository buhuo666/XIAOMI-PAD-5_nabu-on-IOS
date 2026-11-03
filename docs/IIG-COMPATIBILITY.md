# 原生 IIG 与 8796 的兼容性实验

日期：2026-11-03，Asia/Shanghai。

IIG 兼容层已在 macOS 实际编译通过全部 17 份实现，并重新链接出两个普通 arm64 内核。94 个 DriverKit 生成层导出缺项全部消失，完整构建仍因另外 37 个平台接口缺项失败。此结果恢复了参考构建的生成层，不代表 nabu 内核或原版 kext 已可启动。

## 原生默认输出实验

| 项目 | 结果 |
|---|---|
| Actions | `41646722684 / attempt 1` |
| 工程提交 | `74b03d5faea63ac11b0048f05bfe5064dac39060` |
| 工具 | Xcode 16.4，`DriverKit-427.100.5` |
| 工具 SHA-256 | `ae3554f474b279a219adf59ab6780601aeb6873854cdf43d65fbd3b01e952e0d` |
| 实际路径 | `/Applications/Xcode_16.4.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/iig` |
| 原始 make 退出码 | 2 |
| 新内核产物 | 0 |

本地日志位于 `log/ci/github/41646722684/attempt-1/`，下载产物位于 `artifacts/ci/41646722684-attempt-1/xnu8796-reference-3/`。后者的 `log/ci/iig-probe.json` 保留系统 xcrun 的命令、退出码、完整帮助、版本和工具哈希；`iig-generated.json` 记录 17 个不同输入在两个生成目录中的 34 份非空实现及各自哈希。

`probe_iig.py` 显式调用 `/usr/bin/xcrun` 并使用 `/usr/bin:/bin` 的查找路径，避开 HakiOS 的同名 shim。找到真实工具后，将绝对路径通过 `IIG` 传给 XNU。选择发生在 `setup.sh` 导出头文件之前，确保头文件和实现来自同一个生成器。

这次失败与先前的导出表检查失败不同：它发生在 DriverKit 生成代码的 C++ 编译阶段。日志有 132 条编译诊断，只有两种错误文本，均指向 `IORPC` 缺少 `kernelContent`。此前两个已链接参考内核仍保存在首轮产物目录，没有被此次实验覆盖。

## 不同版本的内部消息结构

固定 8796 的 `iokit/DriverKit/IORPC.h` 中，`IORPC` 只有 `message`、`reply`、`sendSize`、`replySize` 四个字段。官方 XNU 10063.121.3 的对应头文件还带有 `kernelContent`。对照文件及来源哈希位于本地 `iig-compat-research/` 子目录。

原版 20F66 的 kext 使用按值传递的 `IORPC`，所以直接给旧结构体增加字段可能改变调用约定和对象布局。当前没有采用这种改法。需要让生成代码符合旧消息契约，并以 [已定位的 GOT 引用](KEXT-INTERFACES-20F66.md) 及后续 ABI 检查验证结果。

IIG 的帮助声明有 `--deployment-target` 参数，但没有说明它是否控制这个内部字段。Apple 的 `IIG_TARGET` 文档描述的是 RPC 参数目标注解；8796 `OSObject.iig` 也将其定义为 `annotate("target")`，它不是生成器版本开关。

## deployment-target 测量

提交 `db646866eae3c6c86b0c460356a935cc4a2c66d6` 增加了独立的 `OSObject.iig` 生成矩阵，依次记录默认值及 `13.3`、`16.5`、`19.0`、`20.0`、`21.0`、`22.4`、`23.0` 的退出码、生成文件、哈希和 `kernelContent` 出现次数。

Actions `41648024252 / attempt 1` 已完成测量：8 组输入全部被生成器接受，但所有头文件逐字节相同，所有实现也逐字节相同。每份实现仍有 8 处 `kernelContent`，随后的构建仍未产生内核。

| 输出 | bytes | SHA-256（8 组均相同） |
|---|---:|---|
| `OSObject.h` | 9,369 | `bf360daf1a3dc08d9a5a49817a833fd60ca2d6aad19aa2d4c987054b4b2857fb` |
| `OSObject.iig.cpp` | 17,557 | `39d669f6a505167c6cc268baca4e29a99cea0c66c154358c4865837ab040c10a` |

这些值是实测 CLI 输入，不预设它们与 iPadOS 或 DriverKit 版本的映射。该有限矩阵不能证明所有生成器版本或参数都无效，但已排除这些输入能解决当前布局差异的假设。完整命令、结果及原始输出保存在 `artifacts/ci/41648024252-attempt-1/xnu8796-reference-4/log/ci/iig-targets/`。

## 保留 8796 消息布局的兼容层

提交 `e14c3405a80220c4ec5f2fa7440ba1ccd0aae500` 增加 `tools/iig_8796.py`。原生生成器仍生成全部头文件和实现；兼容层只选择实现中已有的完整 Mach 消息分支，使之使用 8796 的四字段 `IORPC`。`IORPC.h` 和生成头文件保持原样。

变换识别三种内容：引用 `kernelContent` 的 `#ifdef KERNEL` 块、`MESSAGE_CONTENT` 的独立内容指针块，以及 Invocation 在 `_Msg` 与 `_Msg_With_Content` 间切换的指针声明。对这些块选取既有 `#else`；没有 `#else` 的新增字段块被去除。内核 include、MetaClass 分发及其他内核条件保留。若适配后仍有 `kernelContent`，脚本立即报错。

本地实际 OSObject 样本识别出 11 个消息布局块和 2 个 Invocation。脚本为每份实现加入编译期检查：`sizeof(IORPC) == 24`、四字段偏移分别为 0／8／16／20，以及每个 Invocation 与 `IORPC` 等大。原生输出、适配输出、哈希及块范围保存在 CI 的 `log/ci/iig-8796/`。

## 兼容层的实际构建结果

Actions `41649343964 / attempt 1`，提交 `e14c3405a80220c4ec5f2fa7440ba1ccd0aae500`，已经完成。两个生成目录各有 17 份实现，共 34 份适配记录、864 个消息分支变换和 188 个 Invocation 布局断言。全部实现编译通过；日志没有 C/C++ `error:` 或内核链接 undefined-symbol 错误。生成记录中没有空实现 shim 标记。

| 新产物 | bytes | SHA-256 |
|---|---:|---|
| `mach.development.bcm2837` | 17,023,672 | `014ae5e1bd3c303d55dea630d17f9924e23650950a00cfaa8bde9cfa69ee2eba` |
| `mach.development.bcm2837.unstripped` | 22,820,792 | `c385da03d5a258d6bbf189c05fd357f0b69d6219484c2bb5299a25bacb623444` |

下载后重新核对了两个文件的大小、SHA-256 和 Mach-O header：CPU type `0x100000c`、subtype `0`、file type `2`。34 份原生输出重新经过本地 `adapt()` 后，与下载的适配输出逐字节相同，变换记录和哈希也相符。

| 检查 | 首轮 shim 构建 | 兼容层构建 |
|---|---:|---:|
| `make all` 缺失导出 | 131 | 37 |
| 其中 DriverKit 生成层缺项 | 94 | 0 |
| 参考内核外部定义 | 23,086 | 23,290 |
| 与原版 5,868 个定义同名 | 5,731 | 5,825 |
| 原版独有定义 | 137 | 43 |
| 选定 kext 指针的缺同名目标（存储／显示／GPU） | 3／5／5 | 0／0／0 |

剩余 37 个导出精确对应先前归因的 17 个 UAT、18 个 Apple 平台接口和 2 个 pmap 查询；另有原版独有的 6 个未公开接口，合计 43。`make all` 的真实退出码仍是 2，Actions 仍为 failure。没有删导出列表或新增空函数来改变状态。

旧 shim 的 44 个 Unsupported 替代入口和 21 个直接桥接入口，在新内核中均仍有同名定义；本轮构建输入已改用原生生成实现。这不单独证明这些入口的消息处理和回调行为与供体一致。此前 8 个 GOT 位置涉及的 5 个接口全部有唯一同名候选，详见 [复测记录](KEXT-INTERFACES-20F66.md)。

本地产物位于 `artifacts/ci/41649343964-attempt-1/xnu8796-reference-5/`。本地 `log/ci/github/41649343964/attempt-1/` 保留 `local-kernel-verification.json`、`iig-compat-verification.json`、`export-failure.json`、`export-resolution.json`、`symbol-comparison.json` 和 `kext-symbols.json`。首轮报告与产物保持原有目录。

本轮 CI 归档了原生 CPP、适配 CPP 及变换记录。随后已将日志留存改为在适配前保存原件，并同时保存生成头文件；实际 OSObject 样本与未识别分支失败路径均通过本地检查，记录在 `log/host/iig-wrapper-check.json`。该留存改动不改变 `adapt()` 输出；本轮 CI 没有归档的生成头文件仍不能算作已取得证据。

后续需要验证原版 kext 的方法 ID、类布局、对象生命周期、初始化顺序和运行行为，并解决 nabu 平台服务归属。此构建没有原版组件预链接、板级 ADT、启动内存布局或设备启动验证。
