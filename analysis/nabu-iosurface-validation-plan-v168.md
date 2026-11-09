# 第168轮之后：独立IOSurface纹理验证计划

2026-11-09。只读源码和既有证据梳理；本轮没有修改运行时代码、内核配置或设备。
第167轮已验证owned NC上的Metal填充、计算、绘图和真实像素；第168轮系统工厂内核
已经链接并通过离线检查，本文不把系统工厂实机结果视作已经取得。

建议先用**既有NativeAdreno owned NC BO包装成IOSurface**，调用公开
`newTextureWithDescriptor:iosurface:plane:`，验证真实导入、双向像素和持有期。
这个实验可继续使用v168内核，cached imports保持关闭。随后单独验证普通缓存
IOSurface；两者必须分别记录。仅把`IOSurfaceCacheMode`设成WC不能实现前一步。

## 已确认的内存、映射和所有权路径

以下路径均相对项目根目录；行号对应本次读取的源码。

| 路径 / 函数 | 已确认行为 | 对下一步的意义 |
| --- | --- | --- |
| `src/hakios-8796/xnu/files/iokit/Kernel/MiniIOSurface.cpp:188` `surfaceMemory` | `inTaskWithOptions(kernel_task, kIODirectionInOut\|kIOMemoryKernelUserShared, bytes, PAGE_SIZE)`；没有指定WC/NC | 普通surface不是已验证的NC BO；需保留其真实缓存模式 |
| 同文件`:446` `surfaceCreate`，`:623`到分配段 | 普通像素区向`PAGE_SIZE`取整；分配一页共享状态加像素；像素基址在状态页之后 | 当前16KiB VM页与GPU4KiB页是两层粒度，不能把共享状态页当纹理数据导入 |
| 同文件`:651` 客户内存包装 | `IOSurfaceAddress`使像素使用调用者范围，`withAddressRange`+`prepare`固定页面，内核建立只读映射；单独分配状态页 | 可以把测试拥有的NC映射包装成surface，现有接口无需新增内核selector |
| 同文件`:685` `info->cacheMode` | 仅复制`IOSurfaceCacheMode`数值到返回结构；分配和映射均不使用该值 | 给普通`IOSurfaceCreate`增加这个key不会改变实际PTE/VM对象属性 |
| 同文件`:1018` `addRef` / `:1083` `returnSurface` | 映射状态/普通像素内存到客户端；wrapped surface在另一任务另建`pixelMap`，原任务使用`clientAddress`；映射未显式覆盖cache mode | 包装后的第二进程映射仍需实机证明为同一NC内存，不可只看返回的cacheMode元数据 |
| 同文件`:732` `surfaceHold/Unhold`，`:1421` `makeSendRight`，`:827` `IOSurfaceSendRight::free` | 客户端引用、Mach send right、内核消费者通过`holders`持有surface；最后一个holder删除表项并释放 | Mach端口分享可复用；它持有surface，但不会替测试自动持有原始BO所有者 |
| 同文件`:273` `MiniIOSurface::free` | 先释放客户映射，再complete/release客户descriptor，再归还surface自有内存 | 原始NC BO及其CPU映射必须活到所有surface/import持有者结束之后 |
| 同文件`:1866` `lockCommon` | 不互斥、不等GPU、不做cache维护；非ReadOnly锁和解锁各自更新seed | 每轮必须在应用中等待真实command completion，禁止用Lock成功推断GPU完成 |
| 同文件`:1825` `useCountCommon` | 只更新两类use计数及共享状态 | useCount不是内存fence，也不是GPU所有权转移 |
| `patches/nabu-gpu/NabuGpuMemoryPolicy.h:9` | CLIENT下user-owned BO用WC，即Normal NC；bootstrap显式模式保留 | v168的USERLAND路径可为隔离实验提供已通过的NC存储 |
| `patches/nabu-gpu/NativeAdrenoPublish.cpp:884` `AGXDeviceUserClient::mapCpu` | BoCpuMapV2取得owned BO lease，从原descriptor创建唯一映射，不覆盖其cache mode | 用该接口取得完整、独立的CPU映射；原BO不必先做GPU BoMap |
| `src/nabu/gpu/upstream/Adreno6xx/NativeAdrenoMemory.cpp:668` `importTask` | 用调用任务地址固定内存；优先Persistent内存entry；按每4KiB查询物理段和`NativeAdrenoQueryPageCacheMode`，保持既有属性 | 导入的是调用者的页面，不是根据IOSurface名字或sid伪造出来的GPU资源 |
| `patches/nabu-gpu/NativeAdrenoCpu.cpp:45` `NativeAdrenoQueryPageCacheMode` | `atop(physical)`使用当前VM页大小；WCOMB是NormalUncached；COPYBACK等归Cached；其他有条件拒绝 | 不能把物理页号直接除4096，也不能把Device/Unknown冒充NC |
| `src/nabu/gpu/a640/NativeAdrenoVm.cpp:166` `preflight` | Cached/Mixed在`cached_coherent_imports_==false`时拒绝；NormalNC允许；shareability要求2 | 小型NC包装surface通过实际BoMap，可区别于普通WB被拒的路径；完整GOP的Firmware特例与本实验无关 |
| 同文件`:332` `map` | GPU写回属性由实际backing决定，NC=0、Cached=1；每段建立4KiB SMMU映射 | 把用户请求writeback强制0不能绕过缓存资格，也不能把WB安全地变成NC |
| `src/nabu/gpu/a640/NativeAdrenoGpuContext.cpp:64` | 只有`NABU_GPU_METAL`分支调用`enableCachedCoherentImports` | v168的SYSTEM_METAL+USERLAND没有启用该分支，继续保留 |

核心IOMemoryDescriptor证据在`src/xnu-8796/iokit/Kernel/`：
`IOBufferMemoryDescriptor.cpp:280`把显式cache选项写入memory-entry属性；
`IOMemoryDescriptor.cpp:964`只在映射显式指定cache mode时要求更新memory entry。
普通MiniIOSurface没有这样的指定；返回字典里的cacheMode不能当实际硬件属性。
`NativeAdrenoABI.h`对旧版默认BoAlloc的“WB”注释也不能替代当前Nabu policy。

## 前端已有路径，以及可能造成误判的副本路径

`src/AdrenoMetal/NativeBridgeMetalFrontend.mm:1638`已经实现公开的IOSurface纹理构造：
检查base、`getpagesize()`对齐和allocation，选择plane/row，取整导入整页；plain surface
只接受plane0。`:243`的`surfaceBuffer`以`(sid,base,bytes)`复用导入，调用
`nmb_buffer_new_no_copy_releasing`并CFRetain surface。`NBTexture`还持有NBBuffer和
另一份surface引用；释放回调`releaseSurface`只在runtime释放资源时CFRelease。

`src/AdrenoMetal/bridge/NativeMetalObjects.rs:711`的`no_copy`还检查VM对象身份、串行化
首次导入，并调用runtime的`new_buffer_with_bytes_no_copy`；`:961`的
`nmb_texture_new_on_buffer(..., iosurface=true)`转到`new_texture_with_iosurface_plane`。
这些已有路径可复用，不需要重做Metal对象体系或用MiniIOSurface内核私有对象代替公开API。

**公开方法返回texture且像素正确，不足以证明共享导入。** 当前源码存在完整链条：

1. 普通MiniIOSurface页面可能成功BoImport，但在`NativeAdrenoVm::preflight`因Cached被拒。
2. `src/unixnu-turnip/patches/mesa/turnip-resource-submit-v2.patch:2523`的
   `darwin_map_failure`把一般BoMap失败（包括Unsupported）映射为
   `VK_ERROR_OUT_OF_DEVICE_MEMORY`；这不一定是真正耗尽内存。
3. `src/metal2vulkan/crates/metal2vulkan-runtime/src/buffer_descriptor.rs:553`和`:1603`
   对OutOfMemory/Vulkan error可进入`copied_buffer`，并保持对外`contents`仍为原指针。
4. `copied.rs:1`说明：commit比较CPU修改并复制到GPU自有buffer，batch完成时把GPU变化
   合并回原页面。因此普通surface即使没有共享GPU映射，也可能读回正确像素。

必须记录`host_pointer_imports_made`、`copied_host_buffers_made`及复制字节增量。
`NativeBridgeMetalFrontend`现有`N ... surface made/released`计数只表示包装器构造/释放，
不能排除runtime副本。`nmb_device_work_stats`目前也没有导出这组WorkCounts。

纹理image与共享BO应再分一层：`texture.rs:2150`的`storage_over_buffer`可选择直接
alias image或shadow image。已应用的`bridge/patches/0014`增加`InPlaceWrites`并跳过
自动in-place检查；`NativeMetalObjects.rs:169`采用该策略。`0015`的tile边界限制又被
`0020`移除，依赖Turnip的`turnip-render-mode-for-attachment-memory.patch`处理导入
线性attachment的布局。因此需要真实行间padding和尾部检查，不能声称runtime已经
替本机验证了这些边界。成功共享BO导入但使用shadow image时，应如实记录；只有
in-place计数和布局证据具备时，才能进一步称为直接image alias。

## 首轮最小改动清单

首轮只新增独立测试和必要计数出口，内核薄层、cached开关及显示代码不动。

| 文件 / 入口 | 具体拟改动 |
| --- | --- |
| `userland/nabu/src/gpu_metal_probe.mm` | 加独立surface模式，复用现有设备构造、`finish`、错误/marker/实际像素导出。保留原三项smoke；surface结果用新的文件名 |
| 同文件的测试owned-memory helper | 另开现有0x4147连接，`BoAlloc`获得小型完整页NC BO，`BoCpuMapV2`取得address/map_id/bytes；用`IOSurfaceAddress`包装。成功期间保留连接、handle、map_id；不需要给这个owner做GPU BoMap，纹理导入自身会建立GPU映射 |
| 同文件的IOSurface创建 | 明确BGRA8、BytesPerElement=4、Offset=0、plain/plane0、BytesPerRow=256、32×32、AllocSize按实际getpagesize取整；验证returned base等于包装地址、尺寸和行距吻合。状态页由MiniIOSurface另建 |
| `userland/nabu/src/gpu_metal_smoke.metal` | 增加一个读取输入texture的简单fragment/compute，使用已通过的Xcode metallib路径；原有顶点/纯色绘图可复用到BGRA target |
| 构建probe的两个脚本 | probe本体加入`-framework IOSurface`。现有前端已链接IOSurface。继续16.5/528、既有Turnip和25项runtime补丁，不启用QC偏移或scanout宏 |
| 独立测试计数出口 | 在AdrenoMetal派生源码装配中增加只读surface统计C入口，桥接`Device::work_counts()`的pointer imports/bytes、copied buffers/copy-in/merge-back、host textures in-place及shadow理由；由frontend持有的gDevice取样。无需改变runtime内存选择逻辑 |
| 释放统计 | 复用`native_bridge_metal_telemetry`的surface made/released及`native_bridge_metal_trim_surface_imports`；把检查结果写入probe JSON |

统计入口可局限在新测试构建；不要为测试把原版IOSurface/IOGPU库的类或selector替换掉。
现有`bridge/import_count_loader.cpp`可复用“只计VK_SUCCESS的host import”逻辑作为另一种
独立仪器，它不改变实际driver请求，但目前是host-only程序，尚未做iOS构建资格；
本计划优先小型只读计数出口，避免为这一步再改变loader路径。

签名先复用当前测试entitlements，观察真实IOSurfaceRootUserClient打开结果；如果拒绝，
只增加实测要求的测试进程资格，不预先加宽系统sandbox授权。系统工厂模式继续使用
已准入的`nabu-gpu-metal-probe`进程名。

## 同步、生命周期及验收顺序

**NC首轮的生产者/消费者交接：** CPU写完→Unlock→提交真实GPU命令→
`waitUntilCompleted`返回且status=Completed→ReadOnly Lock→CPU验证像素。
GPU运行期间不让CPU改写同一范围。下一epoch只有在前一epoch完成后写入。
Lock/Unlock只用于公开API/seed约定，真正等待来自command buffer。

底层的顺序证据：`NativeAdrenoSubmit.cpp:1069`提交前DSB；`:1203`观察真实CP fence；
`:806`的release在DSB后归还job引用。`NativeAdrenoVm.cpp:853`的holdJob和`:866`
的retireJobAfterCompletion维持backing引用；`:448`的unmap拒绝active job/alias，
撤销SMMU映射后才retire backing。`NativeAdrenoMemory.cpp:822/828`的publish/acquire
只有DSB，没有WB cache clean/invalidate。已应用的runtime补丁0023补host-write barrier，
但Vulkan barrier和DSB都不能替代未经证明的CPU/GPU WB硬件一致性。

前端`:1159`的finish在真实完成回调后清理resource owners并trim imports；
`:1215`的wait还等待完成handlers。runtime的`buffer.rs:1197` `HostImport::drop`
在Vulkan资源释放后运行待释放回调。这些是应复用的所有权链，仍需本机实测。

**明确释放次序：** 等完GPU→释放MTLTexture/view/command持有→释放本地IOSurface引用
及发出的Mach port→排空autorelease并trim持有的surface imports→确认导入释放计数
与本轮创建匹配→`BoCpuUnmapV2`→`BoFree`→关闭owner连接。wrapped IOSurface没有
持有原始MTLBuffer/BO控制对象的语义；不能因为`CFRetain(surface)`存在就提前归还BO。
若释放没有完成，先记录失败并保留owner，不能借强制unmap制造悬空GPU访问。

推荐分阶段记录：

1. **接口与真导入。** 打印HostImport、HardwareCoherent、CachedCoherentImports三类
   flags和IOSurface元数据；当前cached flag应为0。创建32×32 BGRA纹理，记录实际
   pointer import成功增量及零copied buffer增量；texture.iosurface和plane也须一致。
   不把CF cacheMode数值或包装器计数当导入成功。
2. **CPU→GPU。** CPU经surface base填多色、带epoch的图案；GPU通过纹理读取到
   owned NC输出，完成后核对全部像素。可先texture-to-buffer blit，再用新增shader
   采样到私有texture并沿第167轮路径读回，以覆盖真正的纹理取样和通道顺序。
3. **GPU→CPU。** BGRA render pipeline向surface绘制已通过的局部红色/其余蓝色图案；
   CPU直接从IOSurfaceGetBaseAddress读取，不先复制到readback buffer。另做一次GPU
   读回用于对照；两份结果与逻辑RGBA/BGRA预期一致，导出的是实际内存内容。
4. **重复使用与边界。** 同一texture重复至少数十个epoch，交替CPU图案与GPU局部覆盖；
   检查每行有效128字节、128字节padding和allocation尾部。通过后增加非tile整倍数
   形状（如37×129、row256，alloc按VM页取整），覆盖多个16KiB VM页/4KiB GPU页。
   最初不使用Offset非0、多平面、压缩、sRGB或MSAA。
5. **本地持有与释放。** 在提交前释放应用自己的texture/surface引用，由已编码command
   保持资源；owner NC BO仍保留。完成后验证像素和made/released平衡。计数区分纹理
   缓存暂留与泄漏；重复创建/释放后回到基线，不用进程退出掩盖未释放的导入。
6. **另一进程。** 前五项通过后用`IOSurfaceCreateMachPort`/`IOSurfaceLookupFromMachPort`
   分享给全新probe子进程，以明确的消息/ack交接先写后读。父进程保留原BO到子进程
   完成、释放端口/纹理并报告之后。不要在已经启动Metal线程的进程里fork继续执行GPU。
   先验证跨进程CPU映射，再让子进程独立导入并取样；不依赖跨进程隐式Metal同步。

每阶段JSON至少包含mode、surface ID/base/alloc/row/format、epoch、actual command status、
有效像素错误数、padding/尾部错误数、成功import/copy/in-place/shadow增量和释放计数。
原第167轮RGBA与新BGRA文件区分命名。只要发生copied-host-pages，结果应分类为
“副本路径GPU像素通过/共享导入未通过”，不能归入本阶段的真导入成功。

## 普通缓存IOSurface下一阶段需要的改变

默认MiniIOSurface实验应在**另一个新进程**运行，以免其副本缓存干扰NC模式统计。
现阶段先完整记录它的实际拒绝/副本行为；不能把texture非nil当成当前缓存开关已合格。

普通WB零拷贝资格有两个可区分方向：

- 保留页面WB，在一个独立实验构建开关下调用现有
  `NativeAdrenoVm::enableCachedCoherentImports(0x06040001)`，绝不全局打开
  `NABU_GPU_METAL`。需要把GPU context和build选项的改动局限在此实验；拥有者CPU属性
  不变。该函数目前仅检查芯片ID后设置bool，源码引用mainline/KGSL并不是本机资格。
  先记录实际CPU页属性、SMMU WB/WA+Outer Shareable和命令可见性，再做双向、反复
  修改、脏CPU cache、第二进程和释放测试，结果才可能支持生产能力位。
- 若硬件一致性不能成立，须设计每次提交/完成的cache维护与所有权协议，覆盖所有
  CPU别名和资源范围；或明确实现并计量副本后端。只在创建时复制一次、仅增加DSB、
  把IOSurface Lock当等待、或把一份WB别名单独改成NC，都不满足这个条件。

还有一个后续选项是在MiniIOSurface为**新分配**增加明确NC模式。它必须真实作用于
descriptor/映射，并使内存复用池按cache mode区分；不能只改元数据、全局改默认surface，
或复用现有仅按size匹配的WB缓存条目。首轮wrapped NC已经可以绕开这些全局变动。

`NativeAdrenoUserClient.cpp:475`目前无条件返回HardwareCoherent，只有显式启用时才
返回CachedCoherentImports；Turnip的`vkNativeAdrenoDeviceHostCoherent`却只检查
HardwareCoherent/KernelCacheMaintenance。由此`NativeBridgeMetalFrontend`的
`gDeviceHostCoherent`会跳过`flushSurfaces`。这对已验证NC是合理的，但不能证明WB正确，
也不能指望当前前端的sys_dcache_flush自动补足新WB路径；WB阶段必须重新核对这个约定。

## 保留的未确认项和显示边界

- 尚未在本机执行NC wrapped IOSurface的prepare/第二次import、另一任务映射，以及
  renderer对导入线性BGRA attachment的实际读写；这是计划的验证对象。
- 缓存开关关闭时，普通surface的精确结果可能是map拒绝后副本成功，也可能在更早处
  失败；上文给出源码路径而非宣称已观察到其中某个运行结果。
- runtime目前有“导入失败仍返回资源”的能力；需要只读统计出口或等价成功import证据。
  最后一条warning和名为surface import的前端计数都不足以可靠排除副本。
- InPlaceWrites没有自动验过本机；仅导入BO成功也不证明直接image alias或padding安全。
  明确记录shadow理由，首轮不通过伪造verdict或改格式能力位来让测试变绿。
- 当前public API没有证明跨进程隐式fence、shared event、read-only纹理写入、地址重用、
  creator退出后的全链持有、多平面/压缩/deep color，这些均不由首轮结果推出。

**IOSurface共享导入与presenter/scanout是不同工作。** 本计划不调用SwapEnd、不向
framebuffer传surface、不构造NGP handoff，也不改变DPU/vblank。
`src/hakios-8796/drivers/gpu/hakios.gpu.cpp:218`的`MiniIOSurfaceDrawn`读取旧
`surface->drawn`和hakios GPU fence；未编该GPU时`:10`的`hakios.stubs.cpp`直接返回true。
两种实现都没有连接新的NativeAdreno queue。当前默认配置包含旧HAKIOS_ADRENO实现，
但新的导入/提交路径没有写它的drawn字段。`MiniIOMobileFramebuffer.cpp:1163`还会在
500ms等待失败后继续显示。将来呈现阶段必须单独处理新fence关联和失败帧策略，不能
在独立纹理测试中借旧MiniIOSurfaceDrawn宣布同步已完成。

可复用的测试来源：当前`gpu_metal_probe.mm`的`finish`和绘图/实际像素导出；
`src/AdrenoMetal/bridge/FrontendChecks.h:159`的surface渲染/第二surface取样；
`bridge/no_copy_import_host.mm:24`的成功import计数及混合别名模式；
`bridge/resource_wait_host.mm`、`bridge/resource_lifetime_host.mm`的真实完成与资源持有。
后两者的host event/fixture不能直接冒充本机通过：首轮使用已通过的metallib和单队列
显式completion，shared event能力另行验证后再加入悬置工作测试。
