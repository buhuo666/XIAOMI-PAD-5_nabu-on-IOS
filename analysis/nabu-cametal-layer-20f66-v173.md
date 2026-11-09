# 第172轮后：本机20F66 CAMetalLayer最小App入口

2026-11-09，只读静态分析。第172轮默认IOSurface经Mach读取与复制兼容后端完成
32epochs/64CB，双向像素及释放通过；本文不把该结果扩大为应用呈现通过。
未修改主源码、构建配置或设备，未派发CI。所有新增文件均在analysis下。

**可以直接进行小型App实测；在本次限定的drawable创建路径中，没有发现必须先新增
的Metal device SPI。** 真实创建最终调用已存在的
`newTextureWithDescriptor:iosurface:plane:0`。首轮应显式使用BGRA8、
`framebufferOnly=NO`、小drawable与单帧，复用172复制后端。尚未取得的是UIKit早期
隐式Metal初始化、CA图像队列交接和实际屏幕消费的运行证据；失败必须按阶段定位。

## 分析对象与方法

对象是本机iPad7,11的16.5/20F66共享缓存，QuartzCore image base为0x1881fb000，
UUID为`dc2dd4c1-7866-3443-8050-fc915a0204c1`。复用
`log/host/display-v16/input-files.json`及原始缓存/locals；未重复哈希审计。
本文地址只标识静态证据，不得作为App中的函数、对象或私有字段地址。

已按REA技能检查当前会话：无活动target；Ghidra executable_missing，Hopper
unsupported_host，IDA/Kuna未配置。没有更改REA配置、安装引擎或伪称取得REA反编译。
证据在`analysis/cametal-20f66-v173/rea-availability.json`。

本地Capstone 5.0.7可以读取已有原始ARM64指令；同时解析本机cache的v2指针、
selector专用objc_msgSend桩、优化branch stub及原版Mach-O export trie，足以确定
以下调用及参数。没有需要用伪代码填补的关键device接口缺口，故未为整库启动CI。
主要证据为该目录`calls.json`、`identity.json`和按入口地址命名的21份asm。
关键allocate_drawable_texture的六个selector调用地址另经LLVM18从既有原始text ELF
独立解码，分支目标一致，见`allocate-drawable-llvm.asm`。
函数上界取下一个不同local symbol，仅为读取边界，不声称是反编译器证明的完整body。
脚本的字面值标注是辅助信息，下面的参数结论另按寄存器流核对。

## setDevice/newDrawable/texture的实际含义

| 入口 | 本机实际行为 | 实测应据此区分 |
| --- | --- | --- |
| `-[CAMetalLayer init]`，0x188223544 | 创建CAImageQueue及回调/监听器；**在0x18822393c调用MTLCreateSystemDefaultDevice**，保存默认设备并读registryID | 工厂调用发生在App手动setDevice和nextDrawable之前 |
| `setDevice:`，0x188317e40 | 加锁，设备不同时retain/release替换，再调用layer_private_flush_async；不直接询问新的device SPI | setDevice成功不代表创建过drawable；同一默认device时基本只是比较 |
| `newDrawable`，0x188433af8 | 一次性警告后调用`nextDrawable`，保留返回对象 | 不存在另一条newDrawable专用纹理分配协议，首App用公开nextDrawable |
| `nextDrawable`，0x18821de60 | 检查device；未指定尺寸时从layer size×contentsScale取像素尺寸；消费/收集CAImageQueue，调用get_unused_drawable，然后包装CAMetalDrawable | 无设备、无surface或池等待都可能在这里失败；不要把返回非nil视为纹理成功 |
| `CAMetalDrawable texture`，0x18829cbf4 | 直接返回对象中已缓存的纹理；相关block只是警告 | 真正纹理创建发生得更早，应同时检查drawable和drawable.texture |

`init`默认MTLPixelFormat=80(BGRA8Unorm)、fourcc=BGRA、framebufferOnly=YES，
textureUsage字段为0。`setFramebufferOnly:`（0x1883084b8）更改对应标志并flush，
不会顺便把textureUsage从0改成4。0是Metal的Unknown usage；当前runtime
`texture_descriptor.rs:603`把它展开为shader read/write、render target和view能力，
并非“不能渲染”。首App无需为了它增加私有setTextureUsage调用，记录实际texture.usage。

`layer_private_flush_async`只收集队列、释放旧drawable并清回调，不调用新的Metal
纹理布局接口。`initWithDrawablePrivate:layer:`保留private结构中已创建的texture，
所以get_unused_drawable返回非nil而其texture创建失败时，App仍可能拿到texture=nil。

## 真正分配入口及精确selector

`nextDrawable → get_unused_drawable(0x1882fcff8) →
allocate_drawable_texture(0x188433470)`是关键链。
无合适旧drawable时，get_unused_drawable先创建IOSurface，再创建纹理并向CAImageQueue
注册该surface。正常新分配调用传入resourceIndex=0，plane固定0。

| 接收对象/selector | 本机指令中的参数 | 当前实现关系 |
| --- | --- | --- |
| 原版MTLTextureDescriptor `texture2DDescriptorWithPixelFormat:width:height:mipmapped:` | layer pixelFormat、drawable width/height、NO | Apple本机descriptor类提供；无需自建descriptor类 |
| descriptor `setRotation:` | CA当前rotation；普通路径0–3，压缩分支有另外处理 | 前端textureDescriptor会读取rotation；首App限制portrait并记录实际值，不抄私有字段 |
| descriptor `setIsDrawable:` | YES | 前端已有isDrawable字段解析 |
| descriptor `setFramebufferOnly:` | 仅framebufferOnly分支传YES | 前端已有framebufferOnly字段解析 |
| descriptor `setUsage:` | framebufferOnly时4(RenderTarget)，否则layer textureUsage，默认0 | 前端与runtime已有处理；不必加新selector |
| descriptor `setForceResourceIndex:` / `setResourceIndex:` | 仅resourceIndex非0时使用 | 当前get_unused_drawable新建调用显式传0，首轮不会因此要求这些额外行为 |
| **device `newTextureWithDescriptor:iosurface:plane:`** | x2=上述descriptor，x3=实际IOSurface，x4=0；调用点0x188433594 | 与172已验证的标准IOSurface入口相同；布局和isDrawable仍属本次新组合 |
| 返回texture `setLabel:` | 名称来自当前drawable分配 | NBResource已有label属性；nil接收者不会报错，所以App必须自己验证texture |

本链没有调用`newTextureLayoutWithDescriptor:isHeapOrBufferBacked:`或
`newTextureWithBytesNoCopy:length:descriptor:deallocator:`。
它们在当前前端的未实现状态，**不是本次已确定的前置阻塞**。
私有descriptor setters由系统Metal类提供，不应误记成要给NativeBridgeMetalDevice
新增的方法。此分配函数没有显式setStorageMode；实际descriptor.resourceOptions/
texture.storageMode要记录，不能照搬172显式Shared的日志当成本次已经相同。

选择`framebufferOnly=NO`还有明确作用：get_unused_drawable构造的surface flags
此时只有0或来自commpage的bit2，不置bit1或0x1c0。
`create_iosurface_with_pixel_format`（0x1882bcfa8）只有对应压缩flag满足时才转换fourcc；
这个首轮分支因此保持plain BGRA。随后调用CAIOSurfaceCreate，具体bytesPerRow、
allocSize和planeCount仍由实际返回值确认。不要先开放压缩、多平面或XR10。

`layer_private_check_pixel_format`（0x1882e880c）仅对内部XR10格式范围查询
`supportsExtendedXR10Formats`。当前前端将它明确限制为NO；BGRA8不需要新增XR10能力。

## UIKit早期初始化必须单独落盘

进程basename准入覆盖整个App，不局限某个CAMetalLayer实例。原版Metal默认工厂
具有进程缓存；一旦进程内其他消费者取得该device，不能假定只有测试代码会调用它。
必须在启动该进程前使GPU及只读插件挂载ready，而不是进UIApplicationMain后再等GPU。

**已证实的早期调用**是CAMetalLayer自身init就调用默认工厂。另在同一个QuartzCore
text内限定扫描对CAMetalContextCreate的直接BL，发现：WindowServer renderer、
AsynchronousDispatcher renderer、IOSurface→CGImage block、CA::CG::AccelRenderer::acquire
等调用入口。CAMetalContextCreate本身最终也调用同一个默认工厂（本机实际目标
0x181a2cb3c）。其中绘图/CGImage入口可位于App进程；WindowServer入口不能混称为
“每个UIKit App都会执行”。完整列表在`metal-context-callers.json`。

这些静态入口**不能证明UIApplicationMain必然无条件初始化全套CA Metal**；本次没有
遍历整个UIKit或宣称取得启动trace。但它们足够说明在创建测试layer前触发Metal具有
实际路径。不要把早期缺SPI、系统metallib或CG绘图问题误报为nextDrawable失败。

建议App保留以下独立、立即落盘的阶段：main入口/工厂前后、UIApplicationMain之前、
didFinishLaunching、窗口建立、CAMetalLayer创建前后、setDevice前后、nextDrawable
前后、texture元数据、GPU提交/完成、present调用/回调、移除测试layer及恢复桌面。
仅写UIApplicationMain之后的标记无意义，因为正常运行期间它不返回。
若main文件都没有出现，结合进程启动/退出与crash日志判断，不能把缺记录直接归因GPU。

创建layer前已有Metal activity时，统计是全进程值；分别在阶段边界快照，不强制把
整进程的texture/import/command计数都等同测试自己的单一drawable。创建工厂次数、
内部工厂调用次数、实际device/plugin初始化次数也不是同一个计数。

## present和事件的边界

`register_drawable`（0x18830692c）调用
`CAImageQueueRegisterIOSurfaceBuffer(queue, surface, flags)`保存buffer ID。
`layer_private_present_impl`在0x188214fe0调用CAImageQueueInsertImage，随后设置
insertSeed/status、安排回调，并令所属layer需要commit。它不是直接调用本机Mini
framebuffer的SwapEnd；必须经过实际CA层树和服务端消费，只有App纹理正确不算屏幕通过。

需要纠正先前的候选阻塞：本机class_ro明确解得drawable中的对象是
**IOSurfaceSharedEvent**，layer监听器是**IOSurfaceSharedEventListener**，证据见
`selected-classrefs.json`。不是NBSharedEvent或MTLSharedEventListener。
因此不能由`NBSharedEvent::newSharedEventHandle`返回nil，推导CAMetalLayer此处必失败。

`layer_private_present`（0x18821567c）在相应queue/server标志成立且sharedEvent非nil时，
调用`IOSurfaceSignalEvent(surface,event,drawableID,0)`，再
`notifyListener:atValue:block:`；不满足该条件则直接进入present_impl。事件也是
drawable初始化按queue/server flags有条件创建。当前MiniIOSurface未找到专用的
shared-event实现，但该条件分支是否会被实际App选中、对象是否创建成功，本次没有
运行证据；这是要记录的真实边界，不能提前伪造事件成功，也不需要先泛补Metal共享事件。

首帧使用172已验证的完成与merge-back顺序，完成后才交给drawable present。
现有前端`presentDrawable:`就是注册成功completion后调用系统`[drawable present]`，
可以复用；App主线程保持可处理CA事务，不用阻塞UIApplicationMain的方式等GPU。
强持有drawable/texture直到该帧完成及测试layer撤除，不在未知CA回收状态下反复复用。
系统present回调、CPU合成结束和物理面板可见分别记录；Mini仍是软件复制及定时vsync。

## 最小App可以马上验证的条件与明确停止点

首轮使用已准入的测试basename和172的27patch前端，GPU/挂载在进程启动前ready。
选择普通可见UIView中的CAMetalLayer，BGRA8、framebufferOnly=NO、固定小drawable尺寸
（可先32×32，再由layer放大显示）、单一队列和一帧已验证shader图案；保留退出/移除
测试视图恢复桌面的正常UI生命周期。无需先把backboardd切到新Metal或更换内核。

| 阶段 | 明确停止点/应保留证据 |
| --- | --- |
| UIKit/CA早期 | 在测试layer前已缺SPI/崩溃：按该阶段处理，保留selector、receiver、调用栈/错误；不报告drawable失败 |
| nextDrawable | nil或长时间等待：保留可见性、drawablesize、队列状态和阶段；不以循环重试掩盖 |
| texture | drawable非nil但texture=nil；或非plain BGRA/plane0：停止GPU提交，记录真实元数据及前端错误 |
| GPU | 命令未Completed、像素错误、copy后端未merge-back：不present失败帧；仍用真实状态，不用返回success绕过 |
| CA交接 | present调用返回而无实际图像/回调：调查CAImageQueue/事件/服务端消费；不认为GPU成功就代表显示成功 |
| 恢复 | 移除视图/退出后桌面或触摸异常：单独记恢复失败，不把进程结束作为显示读者结束证明 |

当前没有已确定、必须在这次App编译前修复的device创建selector；可直接实测上述
有限路径。若出现新阻塞，再按实际receiver/selector或队列分支定位，必要时把对应
20F66函数交GitHub Actions反编译；不先反编译整个UIKit/QuartzCore。

静态结果只支持这次最小App入口的可行性，不表示全桌面GPU合成、隐式跨进程fence、
无复制呈现或DPU直接扫描IOSurface已经完成。

## 父任务App候选的限定只读核对

核对`userland/nabu/apps/MetalPresent/main.mm`的`:293`配置段、`:112`纹理/表面验证、
`:174`提交/完成及`:312`取得drawable和后续present，没有修改该文件。
framebufferOnly=NO、BGRA8、32×32及maximumDrawableCount=2未见已知20F66契约冲突；
texture非nil/布局、真实Completed及GPU和IOSurface两路像素验证后才在主线程present，
并持有drawable，符合上述首帧顺序。现有阶段可区分layer init、setDevice和nextDrawable。
这次核对只覆盖已分析的调用契约，不代替App编译、UIKit/CA运行及用户屏幕验收。
