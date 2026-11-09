# iPadOS 16.5 / 20F66 的 IOAcceleratorES 基础 ABI

2026-11-09。范围为原版 `com.apple.iokit.IOGPUFamily` 中的
`IOAcceleratorES` 基础类，以及当前源码内核的接入边界。

原版 20F66 的基础类实例为 **136 字节**，虚表有 **168 个入口**，
相对同一原版内核的 `IOService` 仅入口 **0、1、7** 不同；没有业务方法覆盖。
它与项目 21H16 参考契约的基础布局一致，但各地址不同。
当前源码内核已经注册同名 `IOAcceleratorES`，因此离线合入原版
`IOGPUFamily` 的成功结果不能作为运行时可加载的依据。

本次没有更改设备、驱动实现或启动镜像。第 163 轮的离屏 2D 结果由主任务记录；
本报告没有把它扩大为 Vulkan、Metal、3D 或应用硬件加速验收。

原版输入为 `OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.arm64.macho`。
其中 `IOGPUFamily` 版本为 **65.40.15**，Mach-O UUID 为
`bd8d9d28-d638-3e9a-8004-b159a8ab93b5`。下列地址均为该文件中的原始虚拟地址，
未加运行时 slide；文件偏移对应整个输入文件。

| 项目 | 原始虚拟地址 | 文件偏移（十进制） | 取证窗口（字节） |
| --- | --- | ---: | ---: |
| 兼容受保护构造函数入口 1 | `0xfffffff005ccd164` | 23351652 | 32 |
| 兼容受保护构造函数入口 2 | `0xfffffff005ccd184` | 23351684 | 32 |
| 非释放析构入口 1 | `0xfffffff005ccd1a4` | 23351716 | 4 |
| 非释放析构的虚表入口 | `0xfffffff005ccd1a8` | 23351720 | 4 |
| 释放析构入口 | `0xfffffff005ccd1ac` | 23351724 | 48 |
| `getMetaClass` | `0xfffffff005ccd1f0` | 23351792 | 12 |
| 元类静态初始化入口 | `0xfffffff005cd0560` | 23364960 | 100 |
| 实例虚表首入口 | `0xfffffff006dd2bf8` | 41200632 | 1344 |

原版 kext 的这些函数符号已剥离。“兼容构造函数”和“析构别名”是根据调用、
参数传递与虚表关系确定的语义名称，不能当成恢复出的原始 C++ 符号名。
100 字节初始化窗口还包含后续类初始化开头，并非完整函数长度。

证据链已保存为可复核的静态解析与有界反汇编结果：

- 两个构造入口保留传入参数，调用 `0xfffffff005cd8414`，再将
  `0xfffffff006dd2bf8` 写入实例首指针。该 stub 经 GOT 槽
  `0xfffffff006dce788` 解析到原版导出
  `__ZN9IOServiceC2EPK11OSMetaClass`（`0xfffffff00778b1a4`）。
- 两个非释放析构入口均直接跳转至 stub `0xfffffff005cd8420`；
  GOT 槽 `0xfffffff006dce790` 指向原版
  `__ZN9IOServiceD2Ev`（`0xfffffff00778b1d4`）。
- `getMetaClass` 返回 `0xfffffff007a973c8`。静态初始化以此为目标，
  传入字符串 `IOAcceleratorES`（`0xfffffff0051a9cc6`）、原版
  `IOService::gMetaClass` 与 `w3=0x88`，调用
  `__ZN11OSMetaClassC2EPKcPKS_j`，随后设置元类虚表。
- 逐项比较全部 168 个虚表入口，差异仅为非释放析构、释放析构和
  `getMetaClass`，即槽 0、1、7。槽 168 至 170 为零，其后为元类虚表。

项目现有 [21H16 契约](../src/nabu/gpu/a640/ioaccelerator-base-abi.json)
中的地址不可用于 20F66。可复用的是已核对的基础布局信息，
不包括 `IOGPU` 子类、原版 `IOGPUUserClient` 协议、Metal 私有接口或整条依赖闭包。

当前源码内核的碰撞点已经明确：

| 当前源码定义 | 位置 | 对原版闭包接入的影响 |
| --- | --- | --- |
| `IOAcceleratorES : IOService` | `src/hakios-8796/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp:1708` | 原版 IOGPUFamily 注册同名元类 |
| `IOSurfaceSendRight` | `src/hakios-8796/xnu/files/iokit/Kernel/MiniIOSurface.cpp:809` | 原版 IOSurface 的同名类冲突 |
| `IOSurfaceRootUserClient` | `src/hakios-8796/xnu/files/iokit/Kernel/MiniIOSurface.cpp:893` | 原版 IOSurface 的同名类冲突 |

当前 `publishAccelerator()` 会发布名为 `sgx` 的源码占位服务。
默认不设置 Metal 插件属性，保留现有软件渲染路径；`metal=1` 会将属性指向
`HakiosMetal`。该开关不能用来替代真实渲染验收。

现有源码内核的基础虚表同样为 168 个入口，相对其 `IOService` 仅 0、1、7 不同。
以下导出来自
`artifacts/ci/42570303718-attempt-1/xnu8796-reference-168/artifacts/8796-reference/mach.development.bcm2837.unstripped`：

| 导出符号 | 此次产物中的地址 |
| --- | --- |
| `__ZN15IOAcceleratorESC2EPK11OSMetaClass` | `0xfffffff007a1d880` |
| `__ZN15IOAcceleratorESD2Ev` | `0xfffffff007a1d8c0` |
| `__ZN15IOAcceleratorES10gMetaClassE` | `0xfffffff007de1ed8` |

这些是特定构建产物的证据地址。后续若让 `AGXAccelerator` 继承现有源码基础类，
应按导出符号绑定，并移除或改写参考代码中的
`OSKextLoadKextWithIdentifier("com.apple.iokit.IOGPUFamily")`。
该路线避免为基础类单独引入原版闭包，但尚未经过运行时验证。
原版抽象元类与源码中可实例化元类的构造方式不同，布局相同不能表述为全部元数据等同。

离线实验得到两个不同层次的结果：

| 实验 | 结果 | 结论边界 |
| --- | --- | --- |
| `native_prelink.plan()`：APFS、USB、IOGPUFamily | 18 个组件；34,215 个指针绑定 | 依赖解析与绑定计划可生成 |
| `emit_with_fairplay()`：上述组件再加 FairPlay | 19 个组件；41,824 个指针绑定；内存中生成 58,028,032 字节 | 产物可生成；原版可执行代码保留，输入文件未改写，生成镜像未保存 |

相对第 162 轮基础组件，增加 `AppleARMPlatform`、`AppleMobileFileIntegrity`、
`ApplePMGR`、`IOGPUFamily`、`IOReportFamily`、`IOSlowAdaptiveClockingFamily`、
`IOSurface`。报告仍保留 `abi_qualified=false`、`loadable=false`、
`runtime_qualified=false`；`instruction_relocation_complete` 和
`register_dataflow_qualified` 也未被声明通过。
依赖闭包生成没有验证同名元类注册、模块初始化和设备服务，因此不能据此部署原版闭包。

当前阶段可先使用 `NativeAdrenoGpuPublished : IOService` 发布 BO/submit 通道，
由 `native_adreno_publish()` 设置服务名 `NativeAdrenoGpu`。
`NativeAdrenoControl` 只接受管理员硬件启动请求，不是 BO/submit 用户客户端。
正式 GPU 插件通道使用 open type `0x4147`；参考代码另有诊断/交接类型，
原版 IOGPU 的 type 1 不能按此接口处理。

核对时的 `NativeAdrenoPublish.cpp` 仍在 `native-adreno-metal` 运行时开关下调用
`native_adreno_accelerator_publish()`，默认值为 1。
仅将启动参数改为 0 不会移除链接器引用；IOService 阶段应在编译时排除该调用，
并排除 `NativeAdrenoAccelerator.cpp`，从而去除原版基础类依赖。
参考实现还包含 MACF、IOUserClient filter 和特定进程/entitlement grant 逻辑，
迁移时需按当前内核接口适配，不能把那些参考行为当成已验证的当前内核权限机制。

本次已应用 REA 工作流并检查可用性，但 REA 的原生提供程序均不可用：
Ghidra 配置指向不存在的安装路径，Hopper 不支持本机 Windows，IDA 与 Kuna 未配置。
没有安装工具、修改 REA 配置或打开原生分析会话。
实际证据来自项目 `native_prelink.py` 的 Mach-O/导出解析与已安装 Capstone 的反汇编，
不声称具有 REA 原生 Evidence。本范围的基础 ABI 已由这些证据闭合；
以后如需无法在本地完成的反编译，应按项目规则交给 GitHub Actions。

可供主任务使用的文件：

- [20F66 元数据契约](nabu-gpu-ioaccelerator-20f66.json)：不含原版二进制指令字节。
- [契约恢复脚本](../log/host/gpu-ioaccel-20f66/recover_contract.py)与
  [定位脚本](../log/host/gpu-ioaccel-20f66/discover_abi.py)。
- [有界反汇编](../log/host/gpu-ioaccel-20f66/abi-disassembly.json)与
  [168 项虚表比较](../log/host/gpu-ioaccel-20f66/vtable-comparison.json)。
- [源码内核导出与虚表](../log/host/gpu-ioaccel-20f66/source-kernel-base.json)。
- [依赖计划](../log/host/gpu-ioaccel-20f66/prelink-plan.json)与
  [内存产物生成报告](../log/host/gpu-ioaccel-20f66/closure-emission-report.json)。
- [REA 可用性结果](../log/host/gpu-ioaccel-20f66/rea-availability.json)。

日志目录中的反汇编与大型绑定明细保留在本地；交付的分析文档和元数据契约不包含 Apple 二进制文件。
