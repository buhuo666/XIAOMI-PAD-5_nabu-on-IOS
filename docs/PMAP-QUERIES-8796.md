# 8796 非 monitor 配置的两个 pmap 查询

日期：2026-11-03。范围：当前 BCM2837 参考构建，以及后续同样未启用 `PMAP_CS` 和 `XNU_MONITOR` 的 nabu 配置。

## 结论与补丁范围

固定 8796 的 ARM 源码缺少 `pmap_has_iofilter_protected_write()` 和 `pmap_cs_configuration()` 的定义。20F66 原版 arm64 的实际指令进一步表明：IOfilter 查询直接返回 false；旧代码签名查询与 `code_signing_configuration()` 读取同一个共享配置，并执行同样的初始化。当前补丁因此让旧查询调用现代查询取得配置，不再采用此前从 x86_64 借用的常量 0。

补丁：[pmap-nonmonitor-queries.patch](../patches/8796/pmap-nonmonitor-queries.patch)。只在 `#if !PMAP_CS && !XNU_MONITOR` 下提供以下定义：

| 查询 | 返回值 | 返回值实际含义 |
|---|---|---|
| `pmap_has_iofilter_protected_write()` | `false` | 该配置没有 guarded-mode 的寄存器级 MMIO 过滤写入能力；原有写入函数仍会 panic。 |
| `pmap_cs_configuration()` | `(int)config` | 调用 `code_signing_configuration(NULL, &config)`，保留共享初始化、缓存状态与 DEVELOPMENT／DEBUG 构建的 boot-arg 配置。 |

旧查询返回 0 时仍不能解释为代码签名策略默认、签名强制验证已开启或系统安全。固定版头文件明确禁止这种推断。补丁复用已有查询，不另设策略或重复解析 boot args。启用 `PMAP_CS` 或 `XNU_MONITOR` 时不会提供这些定义，需要相应实现者提供真实查询；本补丁不声称支持那类构建。

## 固定证据

所有路径相对于项目根目录，行号对应以下未修改的固定源码：

- Apple XNU `8796.121.2`：`c54f35ca767986246321eb901baf8f5ff7923f6a`。
- HakiOS 8796：`96ffbc532e970f3540885755d457e401e04d4707`。

| 证据 | 位置 | 对实现的约束 |
|---|---|---|
| IOfilter 查询与写入契约 | `src/xnu-8796/osfmk/vm/pmap.h:846–873` | 查询的是寄存器级访问控制；不同于 `pmap-io-ranges` 的页粒度保护。不支持时写入函数会 panic。 |
| ARM 的现有不支持路径 | `src/xnu-8796/osfmk/arm/pmap/pmap.c:12346–12373` | `pmap_in_ppl()` 返回 false；`pmap_iofilter_protected_write()` 无条件以 unsupported platform 为由 panic。没有可供查询为 true 的写入实现。 |
| x86_64 的范围 | `src/xnu-8796/osfmk/x86_64/pmap.c:3404–3430` | 旧配置查询以 unsupported 为由返回 0。此先例不能代替已经观察到的 20F66 arm64 共享配置实现。 |
| 旧配置查询契约 | `src/xnu-8796/osfmk/vm/pmap.h:890–902` | 只返回部分非默认配置；0 不能推导默认配置，更不能推导安全。公开头中未给出可复用的旧配置位定义。 |
| 编译配置 | `src/xnu-8796/pexpert/pexpert/arm64/board_config.h:26–98` | T6000／T8101／T8103 启用 `PMAP_CS` 与 `XNU_MONITOR`；BCM2837 未启用。 |
| monitor 宏的派生 | `src/xnu-8796/osfmk/vm/pmap_cs.h:57–80` | `PMAP_CS` 控制代码签名实现，`XNU_MONITOR` 控制 PPL monitor；源码要求 monitor 配置同时启用代码签名实现。 |
| 导出声明 | `src/xnu-8796/config/Private.exports:776–780` | 两个查询都是该版本导出表的一部分。 |

搜索固定 Apple 树与 HakiOS 的 `xnu/files`、`hakios.patch`，仅发现上述查询的声明、导出项和 x86_64 定义，没有 ARM 定义或 HakiOS 替代定义。HakiOS 补丁在 `pmap_cs_lockdown_pages()`／`pmap_cs_unlockdown_pages()` 的非 `XNU_MONITOR` 分支明确采用“无 PPL，无需锁定”的处理，没有加入 guarded-mode IOfilter 实现。

## 原版共享状态的指令证据

Actions `41655737937 / attempt 1` 保存了静态 LLDB 结果，原版 slice SHA-256 为 `600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2`，UUID 为 `45734EAD-3AB7-330D-BACF-9C48EF9A9358`。这是 `8796.122.4~1/RELEASE_ARM64_T8010`，不能把它当成固定开源 `8796.121.2` 的原始源码。

| 原版函数 | 入口 VA／文件偏移 | 字节数 | 范围 SHA-256 |
|---|---|---:|---|
| `pmap_cs_configuration` | `0xfffffff007312d58`／`0x30ed58` | 52 | `dd38c44aaef771e649865294ba9ec12a8f09d78a6f69f5524a5d3d8c7d1fd159` |
| `pmap_has_iofilter_protected_write` | `0xfffffff007312d94`／`0x30ed94` | 8 | `2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a` |
| `code_signing_configuration` | `0xfffffff007627148`／`0x623148` | 72 | `b209eb79f2b5df240a7b957fb4235539f6d9818ca49e59d2860ae4551d58803e` |

前两项来自云端 `log/ci/native-20f66/instructions.json`。现代查询是本地从同一原版 slice 追加提取，并用已安装的 LLVM 14.0.0 解码；没有把本地 LLVM 结果标成云端 LLDB 或 REA 反编译结果。完整字节、工具身份与校验在 [平台语义文档](PLATFORM-SEMANTICS-20F66.md) 及其附属记录中。

两个代码签名查询的 ADRP 分别解出同一个 `0xfffffff007149000` 页基址；随后的访问精确对应：

| 地址 | 访问与关系 |
|---|---|
| `0xfffffff007149108` | 两者均 `ldarb` 读取标记位 0；未设置时均以 `stlrb` 写入 1，再 `dmb ish`。 |
| `0xfffffff00714910c` | 两者初始化为 0；现代查询向第一个非空输出参数返回该 32-bit 字段，对应 monitor 类型。 |
| `0xfffffff007149110` | 两者初始化为 0；现代查询向第二个非空输出参数返回该 32-bit 字段，旧查询直接 `ldr w0` 返回这个字段。 |

因此共享的是同一个实际状态地址，而不仅是相似的指令形状。初始化标记已置位时，旧查询跳过写入并返回缓存；未置位时才初始化。原版是 RELEASE 非 monitor 路径，初始化值为零，不能据此把 DEVELOPMENT 构建的查询也改成常量零。IOfilter 查询的完整原始字节则为 `00008052c0035fd6`，即 `mov w0,#0; ret`。

## 固定 8796 的可见性、构建与策略边界

8796 另有 `code_signing_configuration()`，定义位于 `bsd/kern/kern_codesigning.c:60–220`，公开接口在 `bsd/sys/code_signing.h:117–124`。它会：

1. 在 DEVELOPMENT／DEBUG 构建解析 `amfi`、`amfi_allow_any_signature`、`amfi_unrestrict_task_for_pid`、`amfi_get_out_of_my_way`、`cs_enforcement_disable`。
2. 计算 `CS_CONFIG_UNRESTRICTED_DEBUGGING`、`CS_CONFIG_ALLOW_ANY_SIGNATURE`、`CS_CONFIG_ENFORCEMENT_DISABLED`、`CS_CONFIG_GET_OUT_OF_MY_WAY`；有 monitor 时再处理其配置与 `CS_CONFIG_CSM_ENABLED`。
3. 缓存配置并返回 monitor 类型和配置位。未启用 monitor 时类型为 `CS_MONITOR_TYPE_NONE`，仍可能报告 boot args 所设置的非默认位。

固定公开源码没有给出旧查询的实现和位定义，单看头文件不足以建立二者关系；上面的原版地址和读取路径补上了这项证据。当前补丁在非 monitor 范围内直接返回现代接口的配置，不复制 MiniMAC 的位域。此配置下不会设置最高位的 `CS_CONFIG_CSM_ENABLED`，其公开配置位可由 `int` 表示。

编译与调用路径已经核对：`osfmk/arm/pmap/pmap.c:68` 已包含 `<sys/code_signing.h>`；其 `code_signing_config_t` 和 `code_signing_configuration()` 原型在当前内核编译中可见，无需新头文件。`bsd/conf/files:417` 将 `kern_codesigning.c` 列为 `standard`。HakiOS 的补丁与 overlay 没有替换这个函数、头文件或标准构建项；最新 `41659076371` 候选中 `_code_signing_configuration` 定义在 `0xfffffff007838b28`。

`code_signing_configuration()` 的整个函数体没有调用 `pmap_cs_configuration()`，不会形成递归。其 `csm_enabled()` 及 pmap 专属 boot-arg 调整分别受 `CODE_SIGNING_MONITOR`／`PMAP_CS_PPL_MONITOR` 控制；本补丁的 `!PMAP_CS && !XNU_MONITOR` 配置使这些分支不参与编译。原有无 monitor 初始化、原子缓存和输出写入路径均可用。

没有 monitor 并不等于没有任何 XNU 代码签名处理。`bsd/kern/code_signing/xnu.c:44` 起仍提供无 monitor 的实现，源码只说明它缺少保护代码签名状态的 monitor 环境。

当前 HakiOS 的实际政策另有具体证据：`xnu/files/libkern/amfi/miniamfi.c:1–12` 说明它是 AMFI stand-in，没有 trust-cache 内容和完整签名策略；`xnu/files/bsd/kern/kern_minimac.c:1–21` 说明 AMFI／Sandbox stand-in 的限制，其 signature callback 将 ad hoc 签名标为平台二进制。该文件的 `AMFI_BOOTARG_STATE_NOT_ENFORCING=0x86` 属于用户态 AMFI syscall `0x60`，且源码承认并不掌握各位的精确含义。它不是旧 pmap 查询的已知 ABI，不能复制进本补丁。

## 验证与剩余范围

当前共享配置版本已完成补丁应用、macOS 编译链接和实际指令核对。完整 `make all` 仍因其他导出缺项失败，未做设备运行；这些结果分别记录。

- 已在临时目录分别复制固定 Apple 原始 `pmap.c`，以及先应用 HakiOS 中完整 `pmap.c` 补丁段的文件。两种基线上本补丁的 `git apply --check` 和实际应用均成功；HakiOS 基线上有预期的 5 行偏移，无冲突。
- 应用后两个查询各有一处定义，既有写入函数的 unsupported panic 保持不变。原始 checkout 文件 SHA-256 前后一致；没有修改源码 checkout。
- 当前共享配置版本的补丁 SHA-256：`3d5f5fb5976b55fba9461ae5d05efa5c1e0d1d2592a5661a0c1043ba3d3dbbb8`。Actions `41657999493` 和 `41659076371` 的构建报告均记录该哈希，编译链接产生了两个普通 arm64 内核，未做设备运行。
- Actions `41655737937` 编译的是此前常量版本（补丁 SHA-256 `09fbe98c90fe221e705d6ae438846d9a42211fb3fc245cbf1d8666d871d29b57`）。其两个 candidate 查询都是 `mov w0,#0; ret`，不能作为当前共享配置版本的编译证据。
- 集成时在 HakiOS 补丁之后应用本补丁，保留原导出表和现有 `pmap_iofilter_protected_write()`。
- 两轮候选的旧查询入口均为 `0xfffffff007427ff4`，44 bytes，SHA-256 `b881456c20f776163bb6699432b02cb62dc451a37e96ff44cfbe43da47bbac37`。实际指令以 x0=NULL、x1=&32-bit 栈配置调用 `0xfffffff007838b28` 的 `_code_signing_configuration`，随后返回写入的配置；IOfilter 查询仍逐字节等于原版 false 返回。记录在各 run 的 `platform-native-review.json`。
- 最新 Actions `41659076371` 原生分析成功，完整构建剩余 24 个其他导出缺项；没有改删导出检查。最新产物身份与复核范围见 [NATIVE-ANALYSIS-20F66](NATIVE-ANALYSIS-20F66.md)。
- 后续 nabu 平台若引入 monitor／MMIO 保护机制，应重新实现并验证能力查询。当前参考配置不是可启动的 nabu 平台实现。
