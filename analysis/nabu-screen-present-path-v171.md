# 第171轮之后：最小实际屏幕呈现路径

2026-11-09。只读梳理，只新增本文；没有实现、编译、派发CI或操作设备。
第170轮NC wrapped IOSurface已通过；第171轮默认IOSurface的CI42612093714已编译，
本文写作时父任务正在部署，尚不预判其实机结果。内核仍是已验证的v168基线。

**现有接口足够把已完成的GPU画面送到软件presenter，但不足以构成一个有完成回执、
自动恢复桌面的独立测试。** `SwapWait`、取消、连接关闭都没有这种语义。
若下一步要求测试自身可靠恢复，建议仅增加现有presenter内部的一次性小矩形事务，
复用已完成的IOSurface和CPU绘制；先补显示读者的结束与恢复回执，不先扩展整套
CAMetalLayer/桌面Metal。若必须保持内核字节不变，本轮只能定位为可被桌面下一帧
覆盖的诊断提交，不能声称已经具备自动恢复或显示完成同步。

## 证据范围

以下路径相对项目根目录，行号对应本次读取的源码。没有重新下载、哈希审计或反编译。
采用reverse-engineer-anything的证据边界：源码行为、既有20F66汇编、实机记录分开。

| 证据 | 已确认内容 |
| --- | --- |
| `src/hakios-8796/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp` | 当前实际Mini用户客户端、0x46c请求、队列、软件绘制、持有和关闭行为 |
| 同目录`MiniIOSurface.cpp:751/776`、`MiniIOSurface.h:106` | 全局ID查找与内核持有，独立于客户端的useCount |
| `src/hakios-8796/drivers/gpu/hakios.gpu.cpp:218/985` | 旧drawn字段只关联旧hakios GPU的提交编号 |
| `log/host/display-v16/input-files.json`及`locals-IOMobileFramebuffer.json`、`IOMobileFramebuffer.asm` | 本机`16.5-20F66-iPad7_11`已取得的共享缓存输入、符号、LLVM汇编；不是17.7协议 |
| `log/host/display-v16/locals-QuartzCore.json` | 本机20F66 CAMetalLayer/Drawable函数和字段的符号位置；符号存在本身不证明具体调用分支 |
| `log/device/nabu-boot-20261109-170/runtime-log/runtime.log:366/4099` | 实际显示1600×2560、row6400；backboardd发selector4和1132字节selector5，随后Mini绘制BGRA surface |
| `src/AdrenoMetal/NativeBridgeMetalFrontend.mm:1115/1161/1215/1638` | 现有command completion、drawable转交、surface纹理接口；构建器`tools/build_nabu_gpu_metal_probe.py:111`将参考536基类检查改为本机528 |

## 当前真正接受的用户客户端协议

服务类为`IOMobileFramebuffer`，服务名`disp0`，发布
`IOUserClientClass=IOMobileFramebufferUserClient`（`:584`）。可按该类匹配服务、
用普通`IOServiceOpen(..., type=0)`请求此客户端；该Mini类没有自定义type筛选，
但独立probe打开结果及其进程权限仍须实际记录，不能由backboardd能打开推导。

| selector | 最小输入/输出 | 当前行为和限制 |
| --- | --- | --- |
| 8 GetDisplaySize | 无输入，2个64位scalar输出 | 返回逻辑宽高，必须查询；170实测逻辑和物理均为1600×2560 |
| 7 GetID | 1个scalar输出 | 固定返回1，不是当前帧或surface ID |
| 3 GetLayerDefaultSurface | 1个scalar输出 | 返回默认surface的Mach send right；`:690`首次单独分配BGRA surface，**不是当前屏幕内容或最后一次桌面swap备份** |
| 4 SwapBegin | 0输入，1个scalar输出 | 分配全局swap编号；不预留队列，不建立独占显示租约 |
| 5 SwapEnd | 0 scalar，至少0x46c字节结构输入 | 拷贝请求并按各层surface ID取得内核引用；返回不代表已绘制 |
| 6 SwapWait | 170实际使用3个scalar输入 | 仅日志及success；没有等指定swap，没有显示读者结束语义 |
| 20/52/81 Signal/Cancel/CancelAll | 当前实现不检查内容 | 直接success，不撤销队列或屏幕内容 |
| 72 Notifications + port type5 | callback/refcon/type等 | 由定时器产生软件vsync；不绑定swap编号，不证明DPU vblank或某帧显示完成 |

现有20F66汇编直接交叉验证：`_kern_SwapBegin`在`0x1af12c740`起向selector4请求
一个scalar，清零0x46c结构，并把编号写入对象+0x68；`_kern_SwapEnd`
在`0x1af12c544`起将对象+0x18、长度0x46c交selector5。因此下面偏移属于
**请求结构本身**，不是该原版对象的偏移，也不需在probe硬编码原版对象地址。
`_kern_SwapSetLayer`是用户态填表入口，不是另一个用户客户端selector；其ID字段
写入对象+0x6c+4×layer，即请求+0x54+4×layer。

| 请求内偏移 | 类型/意义 |
| --- | --- |
| 0x50 | uint32 swap ID |
| 0x54+4×layer | uint32 IOSurfaceGetID，0表示无surface，共4层 |
| 0x64+16×layer | int32 source x/y/width/height |
| 0xa4+4×layer | enabled位置已命名，但当前绘制代码不读取它 |
| 0xc4+16×layer | int32 destination x/y/width/height，使用逻辑显示坐标 |
| 0x104 | uint32 layers-set mask |
| 0x108 | uint32 layers-cleared mask，当前只记录日志 |

最小诊断请求可全零初始化，只填层0的ID、source、destination、swap ID及set bit0。
**不要用层0 ID=0且set bit0的请求“恢复”**：`:1232`会清黑整个物理framebuffer。
非零surface是否绘制主要由ID决定，不能借enabled或未置set位让已填写的层隐身。
这四层是按顺序CPU覆盖的矩形，不是分配给不同客户端的持久overlay。

`show()`接受bytesPerElement=4且planeCount=0的surface；`drawLayer()`读取
`s->pixels()`、检查范围并按逻辑/物理尺寸缩放。首轮保持plain BGRA8及已验证row布局，
不引入压缩、多平面、旋转、透明混合。当前`fb_filter`默认2：先nearest，空闲40ms后
还会用同一surface重绘为bilinear。若把32×32 GPU结果放大成可见小块，边缘过滤属于
软件presenter，不能把它当作新的GPU渲染成果。

## GPU完成与显示读者是两次独立交接

1. 旧`MiniIOSurfaceDrawn`读取`surface->drawn`，在非零且旧gGPULock存在时，等待
   `hakios_gpu_done(fence)`。写该字段的是旧`HakiosGPUUserClient`提交路径。
   新NativeAdreno/Turnip的提交没有写这组旧fence。服务属性`HakiosWaitsForGPU=true`
   是旧EAGL路径的约定，不能当作新Metal可以提前呈现的资格。
2. presenter即使旧等待500ms失败仍继续显示（`:1163`）。因此首个新GPU显示实验必须
   在用户态等真实command status=Completed及完成handler/副本merge-back结束、
   验证实际IOSurface像素后，才把ID交给显示。禁止给drawn塞NativeAdreno编号、
   将IOSurface Lock/Unlock或`MiniIOSurfaceDrawn=true`当新fence完成。
3. selector5的`present()`在队列锁内对每个非零ID执行`MiniIOSurfaceCopy()`，内核引用
   独立持有像素descriptor。实际绘制线程取得这些引用后调用show；没有CPU/GPU写入
   新内容的许可随SwapEnd返回而自动交回生产者。
4. 队列最多2个待处理项。排队等700ms仍满会直接丢帧；`present()`是void，外层仍返回
   success。无效surface ID也可成为NULL并被跳过，不能以调用成功证明取到了surface。
5. `show():1195`在CPU绘制之前就递减队列并唤醒下一个提交者。因此填满队列、再提交
   空帧，不能充当上一帧已停止读取的屏障。
6. 非filter2时引用在show结束后释放；filter2时为settle保留，40ms重绘后仍留在
   presenter局部数组，直到下一次swap才Drop（`:1082–1121`）。这也意味着纯空闲
   屏幕可一直保有最后的surface。`IOSurfaceIsInUse/useCount`不是这些内核holders的
   等价物；Mini的useCount只由独立trap更新，不能用它检测presenter读取完成。
7. `clientClose():1392`只停此连接的通知/terminate，既不清owner全局队列，也不恢复
   最后画面。`MiniIOMobileFramebufferShow():1745`则直接memcpy到vinfo，绕开队列、
   fLock、surface持有和恢复；旧GPU的show方法还有一次copyin。它不是更完整的出口。

第一帧应只读一个**冻结**的surface，从GPU完成一直保留到显示消费结束；不边呈现边
开始下一epoch。若171默认分配路径像素通过，优先复用该普通surface，按实际结果
记录copied_compatibility或zero_copy，不偷偷开启cached imports。它避免wrapped
NC表面在显示持有期还要额外管理外部BO owner。若改用170的wrapped NC，必须把
BO连接、映射和handle保留到显示读者明确结束；前端GPU资源释放计数不代表显示已释放。

## 为什么当前接口不能独立保证恢复

所有客户端进入同一个presenter，probe与backboardd的请求会串行竞争；下一次桌面
swap可能立即盖掉测试块，也可能桌面处于静止而一直没有后续swap。四层mask不提供
独占权，关闭连接、发cancel、发空swap、睡两帧都不提供恢复保证。
selector3拿到的默认surface也不是当前桌面截图，不能拿来覆盖后冒充恢复。
本文读取范围内没有可用的“读取当前framebuffer/取得最后桌面swap/请求全屏重绘并等
回执”用户客户端方法。此结论只限当前Mini类；不推导整个20F66没有其他显示API。

因此，**内核不变的raw-swap probe可以做受控的单帧诊断，却无法满足自动恢复的完整
验收要求**。用户触摸导致下一桌面帧或系统恰好刷新，只是运行时恢复现象；如实记录，
不能把它写成已经实现的释放/恢复协议。也不建议为此挂起、重启backboardd。

## 建议的最小新增实现：presenter内部的一次性小矩形事务

这是后续实现建议，本轮未修改代码。新增范围限定到独立probe和当前Mini framebuffer，
复用现有source/destination验证与CPU绘制，不新增GPU fence类型或DPU协议。

建议增加一个明确区别于原版swap的新诊断请求及可查询结果；selector编号等实现时
依据本树分配，不使用NGP的0x7000+或0x5343映射。请求只需关联token、surface ID、
source/destination和短暂显示时限，结果明确accepted、drawn、reader_released、
restored或具体失败；**drawn仅指CPU已写framebuffer，不命名为硬件presented/vblank**。
不要把原selector6的空实现改成表面等待来兼容这个实验。

最小顺序：

1. probe完成GPU、完成回调及必要merge-back，验证像素，冻结surface；随后才发送请求。
2. 由现有presenter线程接手，取得surface持有，并在任何framebuffer改动前准备好
   保存目标物理矩形的内存。保存当前屏幕该矩形，再绘制测试块；普通show、settle、
   测试绘制和恢复必须在同一线程及现有framebuffer锁序列中执行。
3. 一次性测试不走filter2的延迟重绘缓存；CPU读取结束即释放测试surface的内核引用，
   再报告reader_released。屏幕已保存的像素与测试源内存可以分离，不必一直占有GPU BO。
4. 最小恢复策略：到期、连接关闭，或**下一次普通桌面show/settle之前**，先由该线程
   恢复备份小矩形，标记restored，然后照常处理桌面帧。正常桌面帧可提前终止测试，
   不能丢弃、拦住或复用旧surface压住桌面。若太快被抢占，报告实际drawn到restored
   的持续时间为观察不足，不宣称用户已看见。
5. 定时到期和连接关闭只给presenter发唤醒/结束请求，不能另起无锁timer去写vinfo。
   即使后续没有普通帧，线程也必须在该事务期限唤醒并执行恢复。先恢复再更新完成状态，
   且在恢复后清除这次测试的延迟绘制/持有状态，避免迟到settle重新覆盖桌面。
6. probe收到reader_released后才允许复用/释放表面及外部owner；收到restored后才能
   记为一次完整通过。若需要证明正常桌面流水继续推进，再记录其后普通swap，并由用户
   确认桌面、触摸正常；不把回写旧矩形本身等同桌面服务持续正常。

这比保证“无论桌面怎么更新都保持overlay若干秒”的方案更小。后者还需每次桌面绘制
更新备份、重叠合成和期限处理，先不纳入。该事务只是消除当前已经存在的恢复及读取
回执缺口，不增加通用显示调度框架。也不向用户态暴露物理framebuffer地址。

| 失败点 | 本次测试应采取的行为 |
| --- | --- |
| GPU error/超时、完成handler未到、像素错误 | 不发显示请求，保留真实失败和资源状态，不把未完成表面交给旧Drawn |
| Surface找不到、布局不符、队列拒绝、备份分配失败 | 在画面改动前失败；不能像原selector5一样返回虚假accepted |
| 连接在绘制前关闭 | 取消该测试请求并Drop；不更改桌面 |
| 绘制后到期/客户端退出/下个桌面帧到达 | presenter串行恢复；恢复后释放备份并记录原因，桌面正常推进 |
| Probe等结果超时 | 不复用未确认结束的wrapped BO；记录未完成，不能把sleep、cancel success或进程退出当回执 |

内核整体不再运行时无法保证软件恢复；本文没有把设备reset当此事务的清理办法。

## 与CAMetalLayer小型app的实际差别

CAMetalLayer更接近应用的正常窗口生命周期，移除自己的view/app后由系统恢复桌面，
但`MTLCreateSystemDefaultDevice()`和IOSurface测试通过，还没有覆盖其drawable路径。

| 环节 | 当前已有 | 小型CAMetalLayer app仍需验证或补齐 |
| --- | --- | --- |
| 启动/设备 | 528布局、ready后新进程工厂、插件只准入`nabu-gpu-metal-probe` | 真正可见的UIView/CAMetalLayer、app/scene生命周期及实际权限；可先沿用该basename，改名则明确增加该单一测试app准入 |
| nextDrawable/texture | plain IOSurface的`newTextureWithDescriptor:iosurface:plane:`已存在 | 20F66 QuartzCore实际如何分配drawable、选择格式/行距/plane及调用device SPI；不得假定一定走同一公开创建方法 |
| GPU编码/完成 | 实际渲染、wait与handler已有 | 只用一个drawable、一帧、BGRA8及已合格shader，记录真实纹理和完成结果 |
| present调用 | 前端`:1115`在成功completion后调用`[drawable present]`；atTime同理 | 这只是转调QuartzCore对象，前端没有实现自己的CAMetalDrawable，也没有因此证明CA已收到/显示该帧 |
| 跨进程交接 | Mini IOSurface ID/port及持有基础存在 | app→CoreAnimation/backboardd的surface与完成交接、drawable再用条件、合成完成回调；GPU completion与didPresent/didComposite必须区分 |
| 事件/私有布局 | 进程内event和fence有接口 | `NBSharedEvent newSharedEventHandle`明确返回nil（`:603`）；raw texture layout两个方法`:1597/1602`也返回nil。只有20F66实际走到相应分支才算必补接口，不能提前宣称CAMetalLayer一定依赖它们 |
| 恢复 | 正常app/view可撤除自己的窗口内容 | 验证移除layer/退出app后的最后drawable释放、桌面重绘和触摸；未完成present不能靠杀进程冒充释放验收 |

首个CAMetalLayer app可采用完成后才present的保守顺序，避免为一个单帧测试预先建设
新的跨进程异步fence。但**是否仍会要求shared-event handle或其他SPI目前未知**，
不能用关闭某个私有属性或返回假的handle绕过。现有missing-selector记录可以作为
实际最小调用集的入口；能力查询/纹理创建失败也要保留，不能只看是否发生unrecognized
selector。该app不需要先把backboardd切到新Metal设备，其服务端消费方式仍需观察。

## 如后续选择CAMetalLayer，限定反编译范围

下一步若选上述presenter诊断事务，不需要新的原版反编译。若选择CAMetalLayer app，
先查以下**已定位的本机20F66**函数及一层直接被调函数；拿到selector、参数和数据流后
再判断具体缺口，不分析整库。地址仅用于现有缓存定位，不能写入运行程序。

| 已有local symbol | 20F66地址 | 要回答的具体问题 |
| --- | --- | --- |
| `-[CAMetalLayer setDevice:]` | 0x188317e40 | device资格/配置查询和可见layer初始化分支 |
| `-[CAMetalLayer nextDrawable]` | 0x18821de60 | 超时、可用drawable池、直接调用入口 |
| `-[CAMetalLayer newDrawable]`及其block | 0x188433af8 / 0x188433f34 | surface分配属性、纹理创建的实际device selector |
| `-[CAMetalDrawable texture]`及其block | 0x18829cbf4 / 0x18843384c | 缓存纹理、IOSurface/plane、是否需要私有layout方法 |
| `-[CAMetalDrawable present]` / `presentAtTime:` | 0x1882a0708 / 0x188432fa8 | 进入提交路径的参数、完成前提 |
| `layer_private_present` / `layer_private_present_impl` | 0x18821567c / 0x188214cbc | surface提交、seed、共享event/服务器同步的实际分支 |
| `releasePrivateReferences:` / `didPresentAtTime:` | 0x188215394 / 0x188214ba4 | 消费完成、回调与drawable归池的真正条件 |

必要时只顺着该路径进入`_didCommitLayer:`（0x188200efc）或明确被调的IOSurface
交接函数。无需先逆向MetalContext全套shader/metallib、整桌面合成或其他系统版本。
本次没有执行这些函数的新增反编译，因此上表不声称已证明它们的内部控制流。

## 验收口径

最小呈现报告分别保留GPU真实completion/像素、surface路径分类与持有、显示请求
accepted、CPU绘制结束、读者释放、恢复结束以及用户可见结果。若使用复制兼容后端，
记录copy-in/merge-back流量；若使用共享导入但有GPU shadow，继续分别记录。
屏幕侧的CPU缩放/复制始终另计，不能因GPU生成了像素就称DPU直接扫描该IOSurface。

现有panel是bootloader留下的framebuffer，软件presenter更新其中字节，软件定时器
提供vsync通知。本轮建议不重新编程SM8150 DPU、不设置扫描地址、不复用NGP/17.7/
sheng/A740接口；能看到GPU生成的测试图，只能证明“GPU结果经当前软件presenter到屏幕”。
它不等同CAMetalLayer、全桌面GPU合成、硬件page flip、DPU scanout或无复制呈现通过。
