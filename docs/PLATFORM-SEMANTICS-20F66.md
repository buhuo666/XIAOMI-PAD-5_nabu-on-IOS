# 20F66 pmap 与平台接口的实际指令语义

日期：2026-11-03。结论按原版普通 arm64 slice、固定公开源码和当前非 monitor 配置区分。

- `pmap_cs_configuration` 应读取共享代码签名配置。原版有初始化分支和缓存读取，不是常量返回；[pmap 补丁](../patches/8796/pmap-nonmonitor-queries.patch) 已据此更新。
- `pmap_has_iofilter_protected_write` 以及下列 11 个平台接口，已逐条确认是设返回寄存器为 0 后返回。11 个接口已形成仅限 BCM2837 普通 arm64 参考配置的独立汇编补丁，并通过字节级交叉汇编检查；其私有 C 类型与“0 是何种状态”仍不能仅由机器指令确定。
- 7 个 `pmap_iommu_*` 接口包含实际状态、重试、分派或分配行为。特别是仅 4 字节的 `pmap_iommu_ioctl` 是跳转到真实实现，不能以短函数为由补零返回。

## 证据身份与检查

云端记录目录：`artifacts/ci/41655737937-attempt-1/xnu8796-reference-6/log/ci/native-20f66`。分析过程只创建静态 LLDB target，没有运行所分析内核。

| 输入 | SHA-256／身份 |
|---|---|
| 原版 `kernelcache.arm64.macho`，48,087,040 bytes | `600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2` |
| 原版 UUID／版本 | `45734EAD-3AB7-330D-BACF-9C48EF9A9358`；`8796.122.4~1/RELEASE_ARM64_T8010` |
| 本次候选 unstripped 内核 | `216993adb1adc704fb9c8ddc8c94db9e53c3604c42432ffd94ec23d8664c8b9d` |
| `plan.json` | `b727ab021ad0cc78ac46047b4eef5fe3a6758ceb13b50b21199b5951fa454507` |
| `instructions.json` | `8ddc9cec9fecdccb045294a230871a8ceadac62fbe7cecda223c33ed95650960` |
| `tool.json` | `56e92bb548173defbc9e04e19c5920764ce2c12f79406a4de433823f2b0ae5e0` |
| Xcode LLDB | `lldb-1700.0.9.502`；工具 SHA-256 `89c7d02af88f43932a4481027df291ebb38f53e2cd058e0bc876f53553e68ece` |

逐项重新读取本地原版与候选：本报告涉及的 20 个原版代码范围和 2 个候选范围，其导出入口、完整文件映射、原始字节、LLDB 字节串和范围 SHA-256 全部一致。范围来自 `LC_FUNCTION_STARTS` 与 section 边界；这不会自动证明被调用函数闭包或完整 ABI。

原版现代代码签名查询和 ioctl 跳转目标是本轮额外检查，使用本机已安装的 WSL Ubuntu LLVM 14.0.0 静态解码。这里没有将 LLVM 输出当作 REA 反编译或云端 LLDB 输出。附属记录保存原始字节、地址计算、完整解码输出和两种工具身份：

[platform-semantics-20F66.json](../log/analysis/platform-semantics-20F66.json)，SHA-256 `75a43fbf539b20381ecd07b456030523ae0b70ee8ba97c104f5765ef69861d1e`。

## 11 个两条指令的平台接口

以下所有入口均存在对应导出，起点在 `LC_FUNCTION_STARTS` 内；8 字节范围没有截断。表中类型标签只描述实际指令，不代表推断出的 C 类型。

| 标签 | 完整原始字节（文件顺序） | 实际指令 | 范围 SHA-256 |
|---|---|---|---|
| X | `000080d2c0035fd6` | `mov x0,#0; ret` | `d3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3` |
| W | `00008052c0035fd6` | `mov w0,#0; ret` | `2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a` |

| 符号 | 原版入口 VA | thin 文件偏移 | 指令标签 |
|---|---|---|---|
| `_sart_get_desc` | `0xfffffff00732aae8` | `0x326ae8` | X |
| `_t6000dart_get_desc` | `0xfffffff00732aaf0` | `0x326af0` | X |
| `_t6000dart_vo_tte` | `0xfffffff00732aaf8` | `0x326af8` | X |
| `_t8020dart_get_desc` | `0xfffffff00732ab00` | `0x326b00` | X |
| `_t8020dart_vo_tte` | `0xfffffff00732ab08` | `0x326b08` | X |
| `_t8110dart_get_desc` | `0xfffffff00732ab10` | `0x326b10` | X |
| `_t8110dart_vo_tte` | `0xfffffff00732ab18` | `0x326b18` | X |
| `_t8110dart_vo_tt_index` | `0xfffffff00732ab20` | `0x326b20` | W |
| `_t8110dart_max_translation_levels` | `0xfffffff00732ab28` | `0x326b28` | W |
| `_nvme_ppl_get_desc` | `0xfffffff00732ab30` | `0x326b30` | X |
| `_uat_get_desc` | `0xfffffff00732ab38` | `0x326b38` | X |

九个 X、两个 W。两类指令最终都使 `x0` 为 0；W 写入同时清除高 32 位。入口路径没有读取输入参数、没有内存读写、没有调用或条件分支，第二条直接 `ret`。这是对实际路径的观察，不是从名字或 8 字节长度猜测实现。

补丁：[bcm2837-apple-iommu-query-returns.patch](../patches/8796/bcm2837-apple-iommu-query-returns.patch)。它保留原版“零值返回且不写输出内存”的行为，每个入口使用表中对应的两条 arm64 指令；没有编造 `kern_return_t` 原型、写出参或将结果称为 `KERN_SUCCESS`。补丁没有改变导出列表，也没有实现 IOMMU 初始化、映射或释放操作。

固定公开 XNU `8796.121.2` 的 `config/Private.arm64.exports:85–96` 列出这些名字；在该固定树、HakiOS 的 `xnu/files` 与补丁中未找到对应类型声明或实现。因此，`get_desc` 的名字与 x0=0 可支持“无描述符”的解释，但指针类型本身仍是推断；`vo_tte`、`vo_tt_index` 或 `max_translation_levels` 的 0 更不能被改写为已完成地址转换、有效页表项、成功 IOMMU 操作等语义。

`_uat_get_desc` 的两条指令不说明 `IOUnifiedAddressTranslator` C++ 类也可使用同样替代。原版类方法另有真实调用、状态和控制流，当前证据没有恢复完整对象布局、虚表契约或各 ioctl 数据结构。

原版 `_nvme_ppl_get_desc` 有 IONVMeFamily 的明确消费者，见 [平台消费者报告](PLATFORM-CONSUMERS-20F66.md)。该组件不在当前最小闭包里，这不等于接口无用，也不等于这组 Apple 接口可直接实现 Qualcomm UFS／SMMU。未来引入相关 provider 时必须重新审查所需行为。

### 配置与构建入口

补丁新增 `osfmk/arm64/bcm2837_apple_iommu_queries.s`，在固定 `osfmk/conf/files.arm64` 的 `iofilter_asm.s` 后按相同的 `optional nos_arm_asm` 规则登记。HakiOS 的 `MASTER.arm64` 已在参考 `KERNEL_BASE` 中选择 `nos_arm_asm`；现有 Actions 日志也实际编译了这一组的 `iofilter_asm.o` 和 `machine_routines_asm.o`。新文件复用 `<machine/asm.h>` 的符号前缀宏，并包含真实 `<pexpert/arm64/board_config.h>`；不依赖生成的 `assym.s`。

汇编定义严格受以下条件限定：

```c
#if defined(ARM64_BOARD_CONFIG_BCM2837) && !defined(__arm64e__) && !PMAP_CS && !XNU_MONITOR
```

`ARM64_BOARD_CONFIG_BCM2837` 由固定构建的 `MACHINE_FLAGS_ARM64_BCM2837` 提供；`BCM2837.h` 明确设置 `NO_MONITOR`，该板型没有启用 `PMAP_CS`／`XNU_MONITOR`。额外检查这两个宏可避免未来 BCM 配置变化后继续提供此分支。这里只选择当前参考板型，没有扩展至所有非 monitor ARM 平台，也没有登记或声称 nabu 支持。

### 实际应用与交叉汇编验证

补丁 SHA-256：`7fea4ea21697c3041d48df1833d57c0384cf78e142d531d010845c95cb1b1571`。

在两个临时目录分别使用固定 Apple `files.arm64`，以及先应用 HakiOS 完整 `files.arm64` 补丁段的版本。本补丁在两者上均通过 `git apply --check` 和实际应用，新编译清单项各出现一次。固定源码 checkout 的文件 SHA-256 前后一致。

使用本机已安装的 Clang 14 及 `-target arm64-apple-macosx13.0 -x assembler-with-cpp`，直接编译临时目录内的完整新汇编文件；包含路径指向固定 XNU 的实际 `osfmk`／`pexpert` 头文件，没有替换头文件或安装依赖。两种补丁基线上均执行下表全部配置：

| 配置 | 外部定义数 | `__text` bytes |
|---|---:|---:|
| BCM2837，普通 arm64，无 PMAP_CS／XNU_MONITOR | 11 | 88 |
| BCM2837 + `PMAP_CS=1` | 0 | 0 |
| BCM2837 + `XNU_MONITOR=1` | 0 | 0 |
| BCM2837 + 人工定义 `__arm64e__=1` | 0 | 0 |
| 未指定板型 | 0 | 0 |
| VMAPPLE | 0 | 0 |

对正向配置，解析 Mach-O object 的真实符号表和 section 字节，11 个入口逐个与原版字节比较：九个 X、两个 W 全部相等，文本重定位数为 0。arm64e 一行验证的是 guard 的宏排除行为，不是完整 arm64e 工具链资格测试。

完整命令、编译器身份、对象哈希和逐符号字节在 [bcm2837-query-assembly-validation.json](../log/analysis/bcm2837-query-assembly-validation.json)，SHA-256 `2169132f5b651f789b44edd7179451db739f17d287a6c240cd29f758dff467cb`。这证明受限汇编实现及宏选择通过本地检查；完整 Xcode 内核编译、链接和导出检查由下一次 CI 验证。

## pmap 代码签名查询不是常量实现

原版旧查询：入口 `0xfffffff007312d58`，文件偏移 `0x30ed58`，52 bytes，SHA-256 `dd38c44aaef771e649865294ba9ec12a8f09d78a6f69f5524a5d3d8c7d1fd159`。完整原始字节：

```text
a8f1fff0082104910afddf08a9f1fff0ea000037aaf1fff05f0d01b93f1101b92a0080520afd9f08bf3b03d5201141b9c0035fd6
```

原版现代查询：入口 `0xfffffff007627148`，文件偏移 `0x623148`，72 bytes，SHA-256 `b209eb79f2b5df240a7b957fb4235539f6d9818ca49e59d2860ae4551d58803e`。完整原始字节：

```text
0ad9ffd04a2104914bfddf0809d9ffd008d9ffd0cb0000373f0d01b91f1101b92b0080524bfd9f08bf3b03d5600000b4290d41b9090000b9610000b4081141b9280000b9c0035fd6
```

两者的六个 ADRP 指令均解出 `0xfffffff007149000`，随后访问同一组全局地址：标记 `+0x108`、现代第一个输出字段 `+0x10c`、现代第二个输出字段 `+0x110`。旧查询与现代查询都 acquire 读取标记，检查位 0；未初始化时清两个字段、release 写标记，再执行 `dmb ish`。旧查询返回的 `ldr w0,[x9,#0x110]` 与现代第二个输出指向同一个 32-bit 字段。

这支持在当前非 monitor 配置中使用：

```c
code_signing_config_t config;
code_signing_configuration(NULL, &config);
return (int)config;
```

固定 `kern_codesigning.c:60–220` 提供现成的初始化、缓存和 DEVELOPMENT／DEBUG boot-arg 处理；`pmap.c:68` 已包含其头文件。调用不递归，也不需要编译 monitor 路径。详见 [PMAP-QUERIES-8796](PMAP-QUERIES-8796.md)。原版 RELEASE 初始化为零并不能证明 DEVELOPMENT 的 boot-arg 状态应被丢弃；本次候选常量实现与原版的初始化／共享状态行为有实际区别。

IOfilter 查询则没有这一问题：原版 `0xfffffff007312d94` 的完整字节是 `00008052c0035fd6`，与固定 ARM 的 unsupported 写入路径一致，保留 false 有直接证据。

## 7 个 IOMMU 接口的明确边界

这些范围的完整指令和原始字节在附属 JSON 的原版 `symbols` 中。不能把下面的导出入口范围当成其调用闭包的全部代码。

| 符号 | 原版入口 VA | thin 文件偏移 | bytes | 范围 SHA-256 |
|---|---|---|---:|---|
| `_pmap_iommu_init` | `0xfffffff007312130` | `0x30e130` | 112 | `2910b5d4ebf415b1b67fdfa20baa0502bb63bc95017917fe2d0185ff923dd7d0` |
| `_pmap_iommu_iovmalloc` | `0xfffffff0073123b8` | `0x30e3b8` | 112 | `166840482cfa1eaa933cfeeba4a12bd1307db96bc2c0936738ea3c0cefea4dd1` |
| `_pmap_iommu_map` | `0xfffffff007312580` | `0x30e580` | 132 | `7bd5379d92b618f0ba15009c8f0c672b66fc74dee6cc55c4a950c5de8f5479bb` |
| `_pmap_iommu_unmap` | `0xfffffff007312748` | `0x30e748` | 112 | `c8530a7ceadb1a04f087559e500e8e8cb2725416ab8ee80ac848eb6b939b616f` |
| `_pmap_iommu_iovmfree` | `0xfffffff0073127b8` | `0x30e7b8` | 208 | `c7a159b0e639ad711b98c1c789f8a18a792b843853b5b37a7a2fc39b4502ae09` |
| `_pmap_iommu_ioctl` | `0xfffffff0073129c4` | `0x30e9c4` | 4 | `96e3b891eec9f91b85a061194621cbf73c17fe3efe2d32d69d2f1a708862dd6b` |
| `_pmap_iommu_alloc_contiguous_pages` | `0xfffffff007312b14` | `0x30eb14` | 408 | `6422a01c1de26af46741933063396f0aa41e62580d385887d19f267896665091` |

- `init` 和 `iovmalloc` 保存参数后调用内部函数，检查返回值的高 32 位以及低 32 位是否为 6，并存在调用后重试。固定 `osfmk/mach/kern_return.h:98` 中 6 是 `KERN_RESOURCE_SHORTAGE`，但内部打包返回类型仍未恢复，不能只凭该数字声明完整原型。
- `map` 具有返回值 14／6 的重试分支，`unmap` 具有 14 的重试分支；固定 `kern_return.h:138` 中 14 是 `KERN_ABORTED`。这些入口在调用前建立临时状态并传递额外指针，直接返回 0 会跳过真实工作。
- `iovmfree` 验证状态对象及表项，再通过描述结构 `+0x38` 的函数指针尾调用；错误路径可到 panic。既有分派和对象约束不能由 no-op 表示。
- `alloc_contiguous_pages` 有溢出检查、分配／等待调用和逐页操作。原版对长度加 `0x3fff` 后以 `~0x3fff` 对齐，并使用 14 位页移；这是该原版 16 KiB 路径的具体证据，不能原样搬到项目拟定的 4 KiB 内核。
- `ioctl` 导出范围虽只有 4 bytes，原始字节 `b1ffff17` 解为 `b 0xfffffff007312888`。本轮继续检查目标 316 bytes（文件偏移 `0x30e888`，SHA-256 `5909067e3d03eb100fb2d347b61be5a6b2013c7fc9b6068f99325eabba154469`）：它检查参数区间溢出和状态对象，在 `0xfffffff007312904` 读取描述结构 `+0x40` 的函数指针，再于 `0xfffffff007312934` 执行 `br x6`。导出入口是转发，不是返回值实现。

固定 Apple 树对这 7 个接口也只保留 `Private.arm64.exports:78–84` 的名称，没有完整公开声明与实现。当前证据足以否决零值成功桩，但不足以重建 IOMMU 状态结构、操作表、同步、所有权或完整函数签名。本轮不为这 7 项添加行为补丁。

## 范围结论

当前 pmap 补丁只调整两个有明确契约的查询，仍由 `!PMAP_CS && !XNU_MONITOR` 限定。11 个实际零返回入口使用独立、范围更窄的 BCM2837 汇编补丁；7 个 IOMMU 操作和 UAT 类方法仍需单独恢复真实契约。本报告没有声称完整 ABI 兼容、可启动 nabu 内核或设备运行通过。
