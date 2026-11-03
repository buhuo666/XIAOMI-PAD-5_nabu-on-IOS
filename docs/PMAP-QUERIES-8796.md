# 8796 非 monitor 配置的两个 pmap 查询

日期：2026-11-03。范围：当前 BCM2837 参考构建，以及后续同样未启用 `PMAP_CS` 和 `XNU_MONITOR` 的 nabu 配置。

## 结论与补丁范围

固定 8796 的 ARM 源码缺少 `pmap_has_iofilter_protected_write()` 和 `pmap_cs_configuration()` 的定义。两者存在声明和导出项，同版 x86_64 则明确实现了“不支持”分支。可以为未启用 pmap 代码签名 monitor 的 ARM 配置补齐这两个查询，依据是已有平台行为和 API 约定，而不是单纯让导出检查通过。

补丁：[pmap-nonmonitor-queries.patch](../patches/8796/pmap-nonmonitor-queries.patch)。只在 `#if !PMAP_CS && !XNU_MONITOR` 下提供以下定义：

| 查询 | 返回值 | 返回值实际含义 |
|---|---|---|
| `pmap_has_iofilter_protected_write()` | `false` | 该配置没有 guarded-mode 的寄存器级 MMIO 过滤写入能力；原有写入函数仍会 panic。 |
| `pmap_cs_configuration()` | `0` | 沿用同版 x86_64 对“不支持的旧 pmap 配置查询”的返回约定；没有报告这个旧接口的任何配置位。 |

第二个返回值不能解释为代码签名策略默认、签名强制验证已开启或系统安全。固定版头文件明确禁止这种推断。补丁既不读取／修改 AMFI boot args，也不更改代码签名处理流程。启用 `PMAP_CS` 或 `XNU_MONITOR` 时不会提供这些定义，需要相应实现者提供真实查询；本补丁不声称支持那类构建。

## 固定证据

所有路径相对于项目根目录，行号对应以下未修改的固定源码：

- Apple XNU `8796.121.2`：`c54f35ca767986246321eb901baf8f5ff7923f6a`。
- HakiOS 8796：`96ffbc532e970f3540885755d457e401e04d4707`。

| 证据 | 位置 | 对实现的约束 |
|---|---|---|
| IOfilter 查询与写入契约 | `src/xnu-8796/osfmk/vm/pmap.h:846–873` | 查询的是寄存器级访问控制；不同于 `pmap-io-ranges` 的页粒度保护。不支持时写入函数会 panic。 |
| ARM 的现有不支持路径 | `src/xnu-8796/osfmk/arm/pmap/pmap.c:12346–12373` | `pmap_in_ppl()` 返回 false；`pmap_iofilter_protected_write()` 无条件以 unsupported platform 为由 panic。没有可供查询为 true 的写入实现。 |
| x86_64 的明确先例 | `src/xnu-8796/osfmk/x86_64/pmap.c:3404–3430` | 旧配置查询以 unsupported 为由返回 0；IOfilter 能力返回 false，写入函数 panic。 |
| 旧配置查询契约 | `src/xnu-8796/osfmk/vm/pmap.h:890–902` | 只返回部分非默认配置；0 不能推导默认配置，更不能推导安全。公开头中未给出可复用的旧配置位定义。 |
| 编译配置 | `src/xnu-8796/pexpert/pexpert/arm64/board_config.h:26–98` | T6000／T8101／T8103 启用 `PMAP_CS` 与 `XNU_MONITOR`；BCM2837 未启用。 |
| monitor 宏的派生 | `src/xnu-8796/osfmk/vm/pmap_cs.h:57–80` | `PMAP_CS` 控制代码签名实现，`XNU_MONITOR` 控制 PPL monitor；源码要求 monitor 配置同时启用代码签名实现。 |
| 导出声明 | `src/xnu-8796/config/Private.exports:776–780` | 两个查询都是该版本导出表的一部分。 |

搜索固定 Apple 树与 HakiOS 的 `xnu/files`、`hakios.patch`，仅发现上述查询的声明、导出项和 x86_64 定义，没有 ARM 定义或 HakiOS 替代定义。HakiOS 补丁在 `pmap_cs_lockdown_pages()`／`pmap_cs_unlockdown_pages()` 的非 `XNU_MONITOR` 分支明确采用“无 PPL，无需锁定”的处理，没有加入 guarded-mode IOfilter 实现。

## 为什么不返回其他代码签名位

8796 另有 `code_signing_configuration()`，定义位于 `bsd/kern/kern_codesigning.c:60–220`，公开接口在 `bsd/sys/code_signing.h:117–124`。它会：

1. 在 DEVELOPMENT／DEBUG 构建解析 `amfi`、`amfi_allow_any_signature`、`amfi_unrestrict_task_for_pid`、`amfi_get_out_of_my_way`、`cs_enforcement_disable`。
2. 计算 `CS_CONFIG_UNRESTRICTED_DEBUGGING`、`CS_CONFIG_ALLOW_ANY_SIGNATURE`、`CS_CONFIG_ENFORCEMENT_DISABLED`、`CS_CONFIG_GET_OUT_OF_MY_WAY`；有 monitor 时再处理其配置与 `CS_CONFIG_CSM_ENABLED`。
3. 缓存配置并返回 monitor 类型和配置位。未启用 monitor 时类型为 `CS_MONITOR_TYPE_NONE`，仍可能报告 boot args 所设置的非默认位。

这与旧 `pmap_cs_configuration()` 的签名和约定不同。固定公开源码没有给出二者位域等价关系，因此不能直接转换返回值。补丁也不能用旧查询的 0 覆盖现代接口报告的状态。

没有 monitor 并不等于没有任何 XNU 代码签名处理。`bsd/kern/code_signing/xnu.c:44` 起仍提供无 monitor 的实现，源码只说明它缺少保护代码签名状态的 monitor 环境。

当前 HakiOS 的实际政策另有具体证据：`xnu/files/libkern/amfi/miniamfi.c:1–12` 说明它是 AMFI stand-in，没有 trust-cache 内容和完整签名策略；`xnu/files/bsd/kern/kern_minimac.c:1–21` 说明 AMFI／Sandbox stand-in 的限制，其 signature callback 将 ad hoc 签名标为平台二进制。该文件的 `AMFI_BOOTARG_STATE_NOT_ENFORCING=0x86` 属于用户态 AMFI syscall `0x60`，且源码承认并不掌握各位的精确含义。它不是旧 pmap 查询的已知 ABI，不能复制进本补丁。

## 验证与剩余范围

验证仅涉及补丁应用和源码配置；完整 macOS 构建、最终链接和设备运行应分别记录，不能由补丁应用成功推导。

- 已在临时目录分别复制固定 Apple 原始 `pmap.c`，以及先应用 HakiOS 中完整 `pmap.c` 补丁段的文件。两种基线上本补丁的 `git apply --check` 和实际应用均成功；HakiOS 基线上有预期的 5 行偏移，无冲突。
- 应用后两个查询各有一处定义，既有写入函数的 unsupported panic 保持不变。原始 checkout 文件 SHA-256 前后一致；没有修改源码 checkout。
- 本补丁 SHA-256：`09fbe98c90fe221e705d6ae438846d9a42211fb3fc245cbf1d8666d871d29b57`。尚未取得包含本补丁的完整 macOS 构建或设备运行结果。
- 集成时在 HakiOS 补丁之后应用本补丁，保留原导出表和现有 `pmap_iofilter_protected_write()`。
- 下一次 macOS 完整构建应确认两个查询的定义来自本补丁，并保留其他导出检查结果。
- 后续 nabu 平台若引入 monitor／MMIO 保护机制，应重新实现并验证能力查询。当前参考配置不是可启动的 nabu 平台实现。
