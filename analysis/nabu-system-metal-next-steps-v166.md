# 第166轮后的系统 Metal 最小接入边界

2026-11-09，只读方案。第166轮 owned NC BO 上的 Vulkan 填充、计算和三角形通过，
桌面触摸正常、APFS136。独立 Metal 前端 CI42590211952 正在构建，尚未实机验收。

**独立 Metal 通过后，先让 GPU ready 后启动的全新进程，经
MTLCreateSystemDefaultDevice() 完成同样的离屏测试，再推进 IOSurface 和桌面。**

| 部分 | 已有基础 | 最小新增工作 |
| --- | --- | --- |
| 内核发现 | 源码 IOAcceleratorES，136字节/168槽；C2、D2、gMetaClass 已导出 | 薄派生 shim、两个 Metal 插件属性、转交现有 newUserClient |
| GPU连接 | NativeAdrenoGpuPublished、open 0x4147、BO/map/submit/fence 实测通过 | 工厂绑定真实服务及 registry ID，在实际进程权限下验证 |
| Metal工厂 | bridge 可直接构造设备，20F66 _MTLDevice 大小为528 | bundle 的 initWithAcceleratorPort:、MTLDevice/MTLDeviceSPI 注册及实际被调方法 |
| Surface | MiniIOSurfaceCopy/Drop/CreateSimple/MakeSendRight 等已有导出 | 新 GPU 的缓存共享、资源持有和完成关系 |
| 呈现 | 当前16.5 framebuffer协议、CPU复制、软件节拍 | 新 fence 与 surface/swap 的连接；真正DPU scanout/vblank另需驱动 |

**内核 shim 可以只依赖现有导出。** 参照 NativeAdrenoAccelerator.cpp 的结构，
按符号绑定本树 IOAcceleratorES 的受保护构造、析构和元类，转发到已验证的
NativeAdreno用户客户端。删除参考的原版 IOGPUFamily 加载依赖，避免与源码
IOAcceleratorES、IOSurface同名类冲突。用本树声明匹配其可实例化基础类，
不能仅凭 sizeof 采用原版抽象元类声明或21H16绝对地址。
原版 IOGPU type 1 不是自有0x4147协议，不能用改名或返回成功替代其实现。

**工厂 bundle 提取最小入口。** initWithAcceleratorPort: 读取真实 registry ID，
返回独立测试通过的 bridge device；最初只允许一个测试进程获得设备。
参考插件的默认路径会启动自测后返回nil，发布路径还带缓存、遥测、名单和显示线程，
不宜整体开启。当前 metal=1 指向 HakiosMetal占位，并不会选择本次bridge。
528字节检查只能证明必要布局，系统注册时的私有方法和库加载仍需实际验证。

**90秒延迟与进程缓存是明确边界。** 第166轮 framebuffer在24.36秒发布，
backboardd在51秒左右使用它，GPU到115.83秒才ready。已有同20F66的
iPhone10,3_6共享缓存分析记录了“枚举IOAcceleratorES→属性→bundle/类→初始化”的
发现链，以及 MTLCreateSystemDefaultDevice 的 dispatch_once结果缓存。
这些地址属于另一设备缓存，不能直接搬入本机。接入方案应按一次发现处理：
ready后启动新测试进程；后续桌面切换需让GPU先ready，或在呈现完整后受控重启消费者。
保留早期无Metal属性的sgx占位，不依赖晚补属性使既有backboardd自动重新选择设备。

**普通 IOSurface 不等于 owned NC BO。** MiniIOSurface的普通分配使用
kIOMemoryKernelUserShared和PAGE_SIZE，未选择NC；锁/解锁主要更新共享seed，
不会等待NativeAdreno fence。bridge的surfaceBuffer()直接导入像素地址，并持有
IOSurface直到资源释放。因此需先验证CPU写→GPU读、GPU写→CPU读、重复修改、
16KiB VM页/4KiB GPU页、行距、只读导入、跨进程持有和fence后释放。

USERLAND目前只验证了CPU/GPU别名同为NC的owned BO，cached-import开关仍关闭。
NativeAdrenoParamsHostImport只是入口存在，NativeAdrenoSubmitHardwareCoherent
也不能替代独立的NativeAdrenoSubmitCachedCoherentImports资格。
直接定义NABU_GPU_METAL会顺带启用cached imports；原机/mainline的coherent标识
不足以证明当前SMMU和别名协议已合格。需真实一致性测试或实现维护/所有权协议，
不能仅改能力位，也不能单独将共享WB页的一份别名改成NC。
首个显示实验可在GPU完成后显式CPU复制NC结果到现有surface；记录此复制成本。
若做透明Metal surface后端，必须补提交前后同步，创建时复制一次不够。

**先复用当前16.5 presenter。** MiniIOSurfaceDrawn已导出，但其实现读取旧hakios GPU
的surface->drawn、gGPULock和旧fence，尚未连接新NativeAdreno队列。
需关联surface写入、GPU完成、显示读者和swap持有期，或在交给presenter前明确等待完成。
现有presenter等待500ms失败后仍显示surface；新异步路径必须定义失败帧处理。
第一阶段可以继续CPU复制到固件framebuffer，分别验收GPU完成、像素、swap和实际屏幕。
MiniIOMobileFramebufferShow是诊断复制出口，不是完整显示协议。

**以下参考功能不能直接开启：**

- 17.7/21H461的536字节基类检查、QuartzCore对象/全局偏移及深色/压缩状态写入。
  当前独立构建改为528，并删除无条件quartzCoreCallers地址诊断；后续工厂也需保留这些适配。
- NATIVE_ADRENO_SCANOUT_COPY、A740 replay、sheng-fb-gpu及NGP handoff。
  NGP的mode/wait/complete、0x7000+method和0x5343映射不是当前0x46c framebuffer swap协议。
  当前integration callbacks为空；NabuGpuScanout未纳入36对象构建，也未在166验证。
- cached-coherent imports、硬件scanout/vblank、压缩/深色/多平面能力。它们分别需要内存、
  20F66呈现协议或SM8150显示硬件工作，不能由现有导出或owned NC结果推出。

**执行出口依次为：**

1. 独立Metal：布局、buffer、compute、render、完成回调和读回通过。
2. 系统工厂：新进程经最小shim/bundle得到设备并完成同一离屏测试，记录真实权限与注册错误。
3. 单一平面BGRA8 IOSurface：缓存、持有期及重复使用通过，再完成小窗口实际呈现。
4. 桌面：补实际调用的20F66 SPI、系统metallib加载路径和发现时机，再测桌面、触摸、
   锁屏及进程重启。旧16.5 QEMU曾在MetalContext找不到metallib URL处失败，
   这是具体待观察入口，不能称为本机已经复现。

当前不需新反编译。若本机工厂行为与已有记录不符，最小CI目标是本机Metal UUID
88922408-fd68-3396-8465-3775ce66ff60中的MTLCreateSystemDefaultDevice、
MTLRegisterDevices、getMetalPluginClassForService及_MTLAddDevice直接调用范围，
确认缓存、bundle入口和注册selectors；只有实际遇到库路径失败，再限定到QuartzCore
MetalContext的metallib选择。无需先反编译整库。

证据：[166结果](nabu-gpu-v166.md)、[基础ABI](nabu-gpu-ioaccelerator-20f66.md)、
[20F66类元数据](nabu-metal-base-20f66.md)、[独立前端](nabu-metal-standalone-build.md)、
[既有20F66发现分析](../src/hakios-8796/docs/ru/metal.md)、
[MiniIOSurface](../src/hakios-8796/xnu/files/iokit/Kernel/MiniIOSurface.h)、
[当前presenter](../src/hakios-8796/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp)。
