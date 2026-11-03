# 废弃项目内核的静态参考审计

日期：2026-11-03，Asia/Shanghai。

**这份归档包含普通 arm64 的 XNU 8796.141.3 Mach-O，以及触摸、HID、Framebuffer、Surface 相关定义。包内符号文本与实际符号表一致；固定提交中的 156 个补丁／脚本哈希也与包内清单相符。遵照用户要求，它们仅用于定位旧实现，不直接用于当前工程，也不作为硬件正确性证据。**

当前工程仍使用 **XNU 8796.121.2 + iPadOS 16.5／20F66、普通 arm64**。下文所有旧代码、地址、尺寸、GPIO 与时序均属于隔离参考，不构成当前构建参数。

## 证据范围与版本边界

用户回忆某个 **具体版本未确认的 iOS 16.6** 曾进入桌面，触摸间歇失效。该回忆尚未与本 ZIP 的 SHA-256、实际启动内核、OS build、loader、ADT、固件及根文件系统建立对应关系。

包内 [BUILD-NOTES.txt](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/BUILD-NOTES.txt) 将 **iPadOS 16.6.1／20G81** 写为兼容性调查目标；这不是用户实测 OS 版本。该文件还说明 `kernel.macho` 是 raw kernel，不是 kernelcache、完整 rootfs 或可启动 payload。清单中的 `physical_device_tested=false`、`ready_to_boot=false`、`source_tests_passed=true` 都只是包内记录；`source-tests.txt` 中的 PASS 和旧源码注释也不能替代设备实测。

本轮只读取本地归档、二进制、文本和隔离恢复源码；没有执行包内程序、构建命令或测试，没有重建该内核，也没有操作设备。

## 输入身份与复查记录

| 输入 | 大小（bytes） | SHA-256 |
|---|---:|---|
| `xnu-8796-kernel (3).zip` | 10,217,814 | `63be0e17bdb7e2925efa5f39d038a4632d07b8c26b1c567b9d6bace2004031cc` |
| `kernel.macho` | 17,286,768 | `30bd87d3f8d19590653a9ce3e7f4b94259afaa781ff4051d34a7cef4aa02c5a5` |
| `kernel-symbols.txt` | 3,472,968 | `96cad56015e658d41a3b9f464690bcc7ec1d538aa7ba80370e2f67bfb343448f` |
| `build.log` | 43,513,754 | `a5fc55ab170cb3ab8dd11fc500a709c08807956e4822425a75981b8e0f904a37` |
| 固定提交源码归档 `source-1537c195.zip` | 786,167 | `9087ed51ee8ac8311be50f1842505402c5fab6e644f97a6655be05830ae0d6d9` |

原 ZIP 位于 `C:/Users/buhuo/Downloads/xnu-8796-kernel (3).zip`，14 个原始成员保存在 `D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17`。`REFERENCE-ONLY.json`、源码 ZIP、恢复目录和审计收据均为后加文件，不计入原始 14 个成员。

- [hardware-inventory.json](/D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/abandoned-kernel-8796/hardware-inventory.json)：复查原 ZIP 哈希、14 个成员大小／CRC、清单文件哈希、Mach-O 命令与完整符号表，保留候选符号及构建命令原文。
- [inspect_hardware.py](/D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/abandoned-kernel-8796/inspect_hardware.py)：上述本地读取脚本；不会执行目标内核。
- [llvm-nm.txt](/D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/abandoned-kernel-8796/llvm-nm.txt)：已保存的 LLVM 14.0.0 `llvm-nm --no-demangle` 结果。
- [rea-identity.json](/D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/abandoned-kernel-8796/rea-identity.json)：REA 识别出的 Mach-O 身份与能力边界。当前 Windows Ghidra 路径不支持 Mach-O，未得到深度反编译结论。
- [recovered-source-verification.json](/D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/abandoned-kernel-8796/recovered-source-verification.json)：独立复查源码 ZIP、156 个补丁／脚本原始字节、112 个所选补丁的日志顺序和 85 个恢复文件。

最后一项检查脚本为 [verify_recovered_reference.py](/D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/abandoned-kernel-8796/verify_recovered_reference.py)。在工程根目录运行它只复查保存的字节和收据，不重新取源、应用补丁或编译。两个脚本与详细收据保存在本地 `log`，由工程忽略规则排除。

## 实际 Mach-O 身份

| 字段 | 直接读取结果 |
|---|---|
| Magic | `0xfeedfacf`，64-bit Mach-O |
| CPU type／subtype | `0x100000c`／`0`，普通 arm64 |
| File type | `2`／`MH_EXECUTE` |
| Load commands | 26 |
| UUID | `87a6dfb0-d847-3962-b1f3-fdbd013ffa55` |
| 内嵌版本字符串 | `Darwin Kernel Version 22.6.0: Mon Aug 14 05:06:07 UTC 2023; runner:xnu-8796.141.3`，出现两次 |
| `LC_BUILD_VERSION` | platform `1`／macOS，minimum OS `15.2.0`，SDK `15.2.0` |
| `__PRELINK*`、`__PLK*` segments | 所有匹配段的文件字节数均为 0 |

字符串中的 **2023-08-14 05:06:07 UTC** 只是二进制内嵌值，并非已验证的编译时间。`LC_BUILD_VERSION` 与编译器平台标记不证明此内核可以运行哪个 macOS／iPadOS 用户态。

存在一个布局例外：`__CTF` 的 `vmsize=0`，但 `filesize=589824`，文件偏移为 `12795904`。现有 `src/XnuPrelink/native_prelink.py` 的 `filesize > size` 防护会拒绝此布局。本审计单独记录该例外、限定符号表读取范围；**不因此放宽当前 prelink 解析器**。成功读取符号表也不等于完整内核布局已获准用于加载。

## 符号文本与二进制的一致性

`LC_SYMTAB` 指定 nlist 起点 `14066320`、数量 **71,050**；字符串表起点 `15203120`、大小 `2083648`。独立读取的全部记录均为 section definition，其中 **24,163 个 external**、46,887 个非 external；`n_type` 分布为 `0x0e=43,253`、`0x1e=3,634`、`0x0f=24,163`。

包内 `kernel-symbols.txt` 的 **71,050 行全部解析成功**，其 `(名称, 地址, external)` 多重集合与实际 nlist 完全相同。已保存的 LLVM 输出又与该文本 **逐字节一致**，SHA-256 见输入表。这证明三种读取结果一致，不证明二进制来源可信、与某份源码逐字节对应或在设备上工作。

按名称筛选的候选如下。每条详细记录包含 nlist／字符串原始偏移、地址、section、可映射的文件偏移和反修饰名，可直接从 JSON 回到二进制字节。

| 名称候选组 | 符号记录 | 位于指令节的记录 |
|---|---:|---:|
| touch transport／parser：`nbu_`、`nvt_`、`geni_spi_`、`nabu_touch_init` | 29 | 24 |
| board HID／keys：`NabuHID`、`gNabuTouch`、`nabu_hid_`、`nabu_keys_init` | 58 | 45 |
| Framebuffer：`NabuFramebuffer`、`IOMobileFramebuffer`、`AppleCLCD`、`nabu_fb` | 87 | 61 |
| Surface：`NabuSurface`、`IOCoreSurface`、`IOSurfaceRoot` | 105 | 81 |

这些数值包含构造／析构、元类、数据和可能的别名，**不是独立函数数量**。名称搜索不覆盖未命名或内联 helper、间接调用，也没有恢复完整子系统调用图。

以下地址均为该二进制符号表内的静态定义值，未应用运行时 slide：

| 定义名／反修饰名 | 地址 |
|---|---|
| `_nabu_touch_init` | `0xfffffe00074fcc44` |
| `_nbu_touch_thread` | `0xfffffe00074fccd4` |
| `_nbu_hid_touch_native` | `0xfffffe00074fef84` |
| `_geni_spi_init` | `0xfffffe00074ff1d8` |
| `_geni_spi_setup` | `0xfffffe00074ff5dc` |
| `_geni_spi_set_clock` | `0xfffffe00074ff6ec` |
| `_geni_spi_transfer` | `0xfffffe00074ff780` |
| `_nvt_validate_point_frame` | `0xfffffe0007500be8` |
| `_nvt_read_point_frame_diag` | `0xfffffe0007500cd0` |
| `_nvt_parse_points` | `0xfffffe0007500f2c` |
| `_nvt_match_nt36523` | `0xfffffe0007501104` |
| `NabuHIDTouch::start(IOService*)` | `0xfffffe0007a7f748` |
| `NabuHIDTouch::touch(int, bool, int, int)` | `0xfffffe0007a7f824` |
| `_nabu_hid_touch` | `0xfffffe0007a7fe44` |
| `AppleCLCD::start(IOService*)` | `0xfffffe0007a7a5ec` |
| `AppleCLCD::publishDisplayModes()` | `0xfffffe0007a7ada4` |
| `AppleCLCD::present(unsigned char const*)` | `0xfffffe0007a7b414` |
| `AppleCLCD::swap(unsigned char const*)` | `0xfffffe0007a7bd9c` |
| `IOMobileFramebufferUserClient::externalMethod(...)` | `0xfffffe0007a7c428` |
| `NabuSurface::kernelAddress()` | `0xfffffe0007a77570` |
| `IOCoreSurfaceRoot::start(IOService*)` | `0xfffffe0007a77fbc` |
| `IOSurfaceRootUserClient::externalMethod(...)` | `0xfffffe0007a79524` |

JSON 另保留 **61 条 `__cstring` 候选**，包括 `nabutouch`、`nabutouchdelay`、`nabutouchmove`、`nabu-touch-firmware`、NT36523／GENI SPI 和 firmware readiness／reset-state 文本。其中有 `NABU TOUCH: threaded GPIO39 sampling active, native=%ux%u fallback=80ms`。这些是**内嵌字符串，不是捕获到的运行日志**；它们既不证明该分支执行过，也不确认 GPIO、坐标或时序适用于当前设备状态。

## 构建日志中的源码与对象

保存的 `build.log` 共 **275,683 行**。以下七条均为真实 `-c` 编译命令，源码路径前缀为历史 runner 的 `.../dxb/xnu/`：

| 源码相对路径 | 命令行号 | 对象名 |
|---|---:|---|
| `bsd/dev/nabu_keys.c` | 24123 | `nabu_keys.o` |
| `bsd/dev/nabu_touch.c` | 24463 | `nabu_touch.o` |
| `bsd/dev/nabu_geni_spi.c` | 25156 | `nabu_geni_spi.o` |
| `bsd/dev/nabu_nt36523.c` | 26134 | `nabu_nt36523.o` |
| `iokit/Kernel/arm/NabuSurface.cpp` | 36327 | `NabuSurface.cpo` |
| `iokit/Kernel/arm/NabuFramebuffer.cpp` | 40001 | `NabuFramebuffer.cpo` |
| `iokit/Kernel/arm/hid/NabuHID.cpp` | 43215 | `NabuHID.cpo` |

四条 C 命令没有显式 `-o`，对象名由紧邻的 CC banner 与后面的对象列表共同确认；三条 C++ 命令显式指定 `-o`。第 **112633 行**的对象列表将上述三个 C++ 对象写入 `iokit.filelist`，路径模板为 `.../dxb/build/xnu.obj/DEVELOPMENT_ARM64_NABU/iokit/DEVELOPMENT/${obj}`；第 **274068 行**对应四个 C 对象，写入 `bsd.filelist`，目录为 `.../DEVELOPMENT_ARM64_NABU/bsd/DEVELOPMENT/${obj}`。

七条命令共同包含：

- Xcode 16.2 的 clang／clang++ 路径、`-arch arm64`、`-march=armv8.2-a+crypto`、`-O2`。
- `-DARM64_BOARD_CONFIG_NABU`、`-DPAGE_SIZE_FIXED`、`-DARM_LARGE_MEMORY=1`、`-DVM_KERNEL_LINK_ADDRESS=0xfffffe0007004000`。
- `-DXNU_TARGET_OS_OSX`、`-DXNU_PLATFORM_MacOSX`、`-DDEVELOPMENT`，以及 MacOSX15.2.sdk 内核头文件路径。
- C++ 另有 `-std=gnu++1z`、`-fapple-kext`。

包内工具链文本记录 Apple clang 16.0.0／Xcode 16.2；日志开头称构建 XNU for macOS 13.5。这些是历史构建记录。`PAGE_SIZE_FIXED` 等宏名本身不能确定数值页大小、monitor 是否启用或最终运行语义。编译与对象列表也不能单独证明源码与本 Mach-O 完全对应；需结合重建或函数级二进制比对继续验证。

## 隔离恢复的旧源码

主线程取得包内记录的固定项目提交 **`1537c1956fae9e2f14d5db5bbbdf1f981a233647`**，将其中的 `xnu-8796` 参考资料保存在 `source-reference`。来源与字节身份见 [source-reference-receipt.json](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/source-reference-receipt.json)。

从归档日志的补丁顺序中选择 **112 个涉及目标文件的补丁**，按历史流程移除 CR 后，在独立 `recovered-hardware` 目录恢复出 **85 个文件**；选定文件没有缺失基础文件。细节见 [hardware-reconstruction.json](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/hardware-reconstruction.json)。这只是所选硬件文件的恢复，未声称完成整个历史源码树的重建。

独立复查结果：156 个原始补丁／脚本的本地字节与固定源码 ZIP 成员相同，其 SHA-256 又全部匹配原内核归档清单；112 个所选补丁顺序与旧构建日志一致；85 个恢复文件的大小和 SHA-256 全部匹配恢复收据。**独立复查没有重复补丁片段构造／应用，也没有编译或证明恢复源码等价于最终二进制**，`source_rebuilt_or_binary_matched` 仍为 `false`。

核心阅读入口：

| 内容 | 隔离恢复文件 |
|---|---|
| 初始化、GPIO 采样、读帧与发布 | [nabu_touch.c](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_touch.c) |
| GENI SPI 传输 | [nabu_geni_spi.c](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_geni_spi.c)、[头文件](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_geni_spi.h) |
| NT36523 帧校验与解析 | [nabu_nt36523.c](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_nt36523.c)、[头文件](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_nt36523.h) |
| HID 服务与触点发布 | [NabuHID.cpp](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/iokit/Kernel/arm/hid/NabuHID.cpp) |
| 显示模式、Framebuffer 与 user client | [NabuFramebuffer.cpp](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/iokit/Kernel/arm/NabuFramebuffer.cpp) |
| Surface 与映射 | [NabuSurface.cpp](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/iokit/Kernel/arm/NabuSurface.cpp)、[头文件](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/iokit/Kernel/arm/NabuSurface.h) |

## 触摸间歇失效的调查线索

下面仅描述**恢复源码中的行为**。旧注释关于若干次运行、恢复效果或控制器含义的陈述没有独立日志支撑；本表不把这些陈述作为实验结果，也不判定用户历史问题的原因。

| 已看到的旧代码 | 对应位置 | 后续需验证的问题 |
|---|---|---|
| SPI 设置 `poll_only=1`；GENI 设置在该分支向 `SE_IRQ_EN` 写 0 | [调用配置](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_touch.c:252)、[SPI 实现](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_geni_spi.c:119) | 区分 GENI 传输完成机制与触控器 GPIO 提示；核对 SPI 打包、时钟、CS、读响应和超时 |
| 使用旧常量 GPIO39，低电平清除 `line_consumed`，高电平且未消费时提示一次读帧；其余情况等待 80 ms fallback，无读帧条件则 sleep 1 ms | [循环](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_touch.c:486) | 核对实际 IRQ 极性、有效沿与保持方式；用同一时间轴记录 GPIO、读帧与触点事件，判断是否漏帧 |
| 读帧、解析或发布任一失败时，只要存在活动槽位就调用 `nbu_touch_release` | [失败分支](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_touch.c:544) | 单次坏帧是否导致人为抬起／重按；需要同时记录原始帧、校验结果和最终 HID 事件 |
| 前六字节全部为 `0x77`，或每字节为 `0xfd/0xfe` 时，在 checksum 拒绝之前返回 `-2` | [诊断读帧](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_nt36523.c:123) | 验证这些模式在实际控制器上的含义，区分总线错误、固件状态与有效恢复请求 |
| `frame_status==-2` 分支递增 backoff，前七次 sleep 20 ms，之后 200 ms；重设 fallback deadline 后继续循环，该分支没有 reset 或 firmware reload | [backoff](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/bsd/dev/nabu_touch.c:557) | 是否需要复位、挥发固件恢复和状态重建；现有等待是否能够恢复，必须由实测确认 |
| HID 逻辑尺寸固定为 1600×2560；Framebuffer 默认值同样如此，但 `nabufb_native` 可改用 boot framebuffer 宽高 | [HID](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/iokit/Kernel/arm/hid/NabuHID.cpp:435)、[显示选项](/D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/iokit/Kernel/arm/NabuFramebuffer.cpp:184) | 核对物理触控坐标、方向、缩放、显示模式和 HID 生命周期的契约；相同默认常量不等于事件路径一致 |

建立当前 8796.121.2／20F66 的硬件实现时，需独立确认选定 IOSurface、Framebuffer、IOHID 组件的服务归属、类布局、user-client 方法和消息语义。旧类只能提供调查方向；符号同名、可见桌面和源码静态模型测试均不能完成这一项验证。

今后的设备实验需保存同一轮的 OS build、内核哈希／UUID、loader／ADT／固件哈希及时间对齐日志，才能把上述线索与具体现象连接起来。当前文档提供静态定位入口，尚未形成经验证的触摸修复方案。
