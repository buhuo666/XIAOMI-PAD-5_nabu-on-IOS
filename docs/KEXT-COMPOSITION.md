# 20F66 原版组件声明依赖与服务归属

更新：2026-11-03。输入是本地 iPad7,11 / j171ap 的 iPadOS 16.5（20F66）内核元数据，共 229 条组件记录。

**三阶段声明依赖闭包分别为 23、36、37 项；未发现缺失的组件标识符。** 这些数字包含每阶段共同的 7 个内核 KPI 记录。它们不是可直接拼装、预链接或启动的 kext 集合，也没有证明 8796.121.2 与原版 8796.122.4 的符号和 ABI 兼容。

## 输入和计算方式

- 配置：`configs/kext-roots-20F66.json`。
- 输入：`OS/ipados/16.5-20F66-iPad7_11/manifests/kernel-report.json`。
- 本地完整输出：同目录 `kext-closure.json`；保留全部边、请求版本、实测版本、最短示例路径、依赖排序、缺项和新增集合。
- 20F66 arm64 内核 SHA-256：`600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2`。
- 实测内核：`xnu-8796.122.4~1/RELEASE_ARM64_T8010`，Darwin 22.5.0；工程源码基线继续是 8796.121.2。
- 根标识符分组参考本地 nabu 固定提交 `54b4f98457f8e9e232cc0a077c20d08d0b2f0ac9` 的 `source-ci/prepare_source.py:48`。这里只参考 bundle identifier；所有依赖和版本重新取自 20F66。21H16 的地址、初始化入口、slide、卷 UUID 和策略包不进入本配置。

在工程根目录执行：

```powershell
python tools/inspect_kext_closure.py OS/ipados/16.5-20F66-iPad7_11/manifests/kernel-report.json
```

算法沿 `OSBundleLibraries` 递归访问标识符，保存每条依赖的原始版本字符串。没有用整数或字符串大小比较来宣称兼容；当前输入没有 `OSBundleCompatibleVersion`，还缺导出符号、重定位、vtable 和硬件匹配证据。输出中的依赖顺序仅是元数据图的拓扑顺序。

## 阶段结果

| 阶段 | 根数 | 闭包总数 | KPI | 非 KPI | 声明边数 | 缺失根/依赖 | 比前阶段新增 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 存储与基本用户态声明依赖 | 4 | 23 | 7 | 16 | 110 | 0/0 | 23 |
| CPU 显示与触摸声明依赖 | 8 | 36 | 7 | 29 | 191 | 0/0 | 13 |
| GPU 声明依赖 | 9 | 37 | 7 | 30 | 201 | 0/0 | 1 |

三个阶段均无声明依赖环。7 个 KPI 是 `bsd`、`dsep`、`iokit`、`libkern`、`mach`、`private`、`unsupported`，前缀均为 `com.apple.kpi.`，实测版本均为 `22.5.0`。它们需要绑定到本工程构建的内核导出，不能将固件中的 KPI 元数据当作本工程已实现相应接口的证明。

`IOHIDEventDriverSafeBoot` 在显示触摸和 GPU 阶段出现，但没有 `_PrelinkExecutableLoadAddr` / `_PrelinkExecutableSize`。后续已提取 20F66 的 7 个 personality 和对应匹配条件，见 [KEXT-INTERFACES-20F66](KEXT-INTERFACES-20F66.md)；是否适用于板级触摸服务仍待运行验证。

### 存储与基本用户态

4 个根为 APFS、AppleFSCompressionTypeZlib、AppleMobileFileIntegrity（AMFI）和 sandbox。下面列出 16 个非 KPI 项：

| 标识符 | 20F66 实测版本 |
|---|---|
| `com.apple.AppleFSCompression.AppleFSCompressionTypeZlib` | `1.0.0` |
| `com.apple.driver.AppleARMPlatform` | `1.0.2` |
| `com.apple.driver.AppleEffaceableStorage` | `1.0` |
| `com.apple.driver.AppleMobileFileIntegrity` | `1.0.5` |
| `com.apple.driver.ApplePMGR` | `1` |
| `com.apple.filesystems.apfs` | `2142.122.2` |
| `com.apple.iokit.CoreAnalyticsFamily` | `1` |
| `com.apple.iokit.IOCryptoAcceleratorFamily` | `1.0.1` |
| `com.apple.iokit.IOReportFamily` | `47` |
| `com.apple.iokit.IOSlowAdaptiveClockingFamily` | `1.0.0` |
| `com.apple.iokit.IOStorageFamily` | `2.1` |
| `com.apple.kec.corecrypto` | `12.0` |
| `com.apple.kext.AppleMatch` | `1.0.0d1` |
| `com.apple.kext.CoreTrust` | `1` |
| `com.apple.security.AppleImage4` | `5.0.0` |
| `com.apple.security.sandbox` | `300.0` |

例如，`AMFI → ApplePMGR → AppleARMPlatform` 是本固件真实的声明路径，所以基础阶段已经涉及 Apple 平台服务，不能等显示阶段才处理。`APFS → IOStorageFamily` 是驱动框架依赖，不会自动提供 SM8150 的 UFS 控制器、分区窗口或 Data 卷实现。

### CPU 显示与触摸

在基础根上加入 IOSurface、IOMobileGraphicsFamily、IOHIDFamily、IOHIDEventDriverSafeBoot。新增 13 项：

| 标识符 | 20F66 实测版本 |
|---|---|
| `com.apple.driver.AppleAudioClockLibs` | `240.1` |
| `com.apple.driver.AppleIISController` | `240.1` |
| `com.apple.driver.AppleM2ScalerCSCDriver` | `265.0.0` |
| `com.apple.driver.IODARTFamily` | `1` |
| `com.apple.iokit.IOAVFamily` | `1.0.0` |
| `com.apple.iokit.IOAudio2Family` | `1.0` |
| `com.apple.iokit.IOCECFamily` | `1` |
| `com.apple.iokit.IOHDCPFamily` | `1.0.0` |
| `com.apple.iokit.IOHIDEventDriverSafeBoot` | `2.0.0` |
| `com.apple.iokit.IOHIDFamily` | `2.0.0` |
| `com.apple.iokit.IOMobileGraphicsFamily` | `343.0.0` |
| `com.apple.iokit.IOSurface` | `336.50.1` |
| `com.apple.kec.Libm` | `1` |

这些新增项包含两条需要移植决策的支线：

- `IOMobileGraphicsFamily → AppleM2ScalerCSCDriver → IODARTFamily`。
- `IOMobileGraphicsFamily → IOAVFamily → AppleIISController / AppleAudioClockLibs / IOAudio2Family / IOCECFamily / IOHDCPFamily / Libm`。

这是声明可达关系，不表示本机存在 Apple scaler、DART 或音频硬件。应根据 20F66 实际符号调用拆出所需类与方法，再决定原版保留、由板级服务提供，或不参与硬件匹配；不能靠删除元数据依赖边解决二进制引用。

### GPU

在显示触摸根上只加入 `com.apple.iokit.IOGPUFamily`（`65.40.15`）。它其余 10 条声明依赖已经在前阶段闭包内，因此总数只增长 1。

这个结果没有包含 Adreno 640 的寄存器初始化、SMMU、固件、提交队列或用户态 Metal/Turnip 实现；这些来自另行构建的板级源码，不会被 Apple 的 `OSBundleLibraries` 自动纳入。`AppleMultitouchDriver` 与 `AppleKeyStore` 也不在这 37 项中，这不代表用户态不需要输入或 keybag 服务。

## HakiOS 参考构建与拟定原版组件的服务归属

以下是对本地 HakiOS 固定提交 `96ffbc532e970f3540885755d457e401e04d4707` 的源码观察及拟定拆分，尚未修改该源码。路径均相对于 `src/hakios-8796/`。

| 服务 | HakiOS 已有实现与依据 | 选用原版组件时需要拆分的部分 |
|---|---|---|
| IOSurface | `xnu/files/iokit/Kernel/MiniIOSurface.cpp:836` 定义 `IOCoreSurfaceRoot`，设置 `IOSurfaceRootUserClient` 并注册；其像素对象是自有 `MiniIOSurface`。 | 原版 IOSurface 应独占对应服务和对象协议；关闭 Mini 发布及其对象使用者，显示后端改接原版 IOSurface 接口。不能把两种对象布局当作同一类。 |
| 显示 | `MiniIOMobileFramebuffer.cpp:290` 定义 `IOMobileFramebuffer`，`:1337` 定义用户客户端；它直接依赖 `MiniIOSurface`，向 boot framebuffer 做软件呈现。 | 原版 IOMobileGraphicsFamily 路径需要独立的 nabu/GOP 呈现后端。Mini framebuffer 与原版 family 的类、用户客户端和 surface 协议应成套选择。 |
| GPU 基类与发布 | 同文件 `:1708` 定义 `IOAcceleratorES`，`:1716` 的 `publishAccelerator` 发布 `sgx`；`metal=1` 会声明 `HakiosMetal` 插件。 | 原版 IOGPUFamily + NabuAdreno 路线需要移除这套占位基类与发布入口，并由板级加速器指定实际插件。该冲突不只是 framebuffer 名称重复。 |
| APFS | `xnu/hakios.patch:181` 起将自有 APFS 源码加入构建；`:1346` 通过 `apfs_vfsops` 注册文件系统名 `apfs`。 | 原版 APFS 接管 VFS 注册和根卷语义时，退出这组内建 VFS/挂载入口，保留的块设备提供者通过明确接口接入 IOStorageFamily。 |
| 平台与 CPU | `GenericARMPE.cpp:181` 定义平台专家，`:213` 的 `start` 注册 `GenericARMCPU`；补丁 `:1844` 为其设置 platform-expert 匹配。 | nabu 的平台/CPU owner 必须单一。闭包里的 AppleARMPlatform/PMGR 仍可能提供被调用的类与方法，保留哪些接口、哪些硬件匹配应禁用，需要符号和方法证据；不能把两个平台专家同时当主入口。 |
| AMFI 与 Sandbox | `kern_minimac.c:118`、`:356` 定义名为 `AMFI`/`Sandbox` 的替代策略，`:365` 注册；`libkern/amfi/miniamfi.c:260` 注册 AMFI 接口。 | 原版 AMFI/Sandbox 路线应替换对应接口和策略注册，并重新安排 20F66 初始化顺序与信任缓存交接。早期初始化地址尚未定位。 |

`GenericARMPE.cpp:302` 连续调用 MiniIOSurface、MiniIOMobileFramebuffer、MiniAppleKeyStore、MiniIONetworkStack 的启动入口；`xnu/hakios.patch:1910` 起把这些 Mini 对象加入 IOKit 构建。因此后续 nabu 配置要同时拆分**编译入口、启动调用、类/符号归属和运行时服务发布**，不能只添加几条原版 prelink roots。

## 当前边界与下一步

本次完成的是以 20F66 为输入的声明依赖取证，及源码可见的服务归属整理。后续已取得原版 personality 元数据和显式指针接口候选。仍需完成完整指令引用与重定位、初始化入口和顺序、所需 vtable/类布局，以及板级替代服务边界。HakiOS 参考内核构建继续用于验证编译链，nabu 原版组件组合尚未成为可启动产物。
