# 第171轮默认IOSurface失败：内核返回与iOS复制路径

2026-11-09。读取已回收日志及v168构建源码映射；未操作设备、重编内核或启用缓存导入。
父任务另行授权的Mach读取自检已加入独立probe，见文末；runtime修复由构建代理负责。

**本轮已证实的内核返回是BoMap的Unsupported，不能把用户态OutOfMemory(Device)
解释为GPU内存耗尽。** 默认surface遇到关闭的cached导入门槛，是与实际源码最吻合的
解释，但本轮日志没有该对象的cache属性和preflight拒绝阶段，尚不能将“纯WB、且仅
这一分支”写成实测结论。复制兼容没有接住此错误，则已有另一项明确源码原因：实际
iOS构建选中了`read_pages`恒false分支。应优先修正这两处cfg覆盖，保持内核不变；
现在没有必要为了绕过复制缺口去开放WB导入。

## 已观测证据

`log/device/nabu-boot-20261109-171/runtime-log/runtime.log`为3,572,008字节。
其report标注`capture_sealed=false`、`state=incomplete`，验证范围是已回收的连续
日志流；没有完整结束记录。因此下面正向事件成立，不以“日志中没出现”证明所有
后续动作或内部清理均不存在。

| 位置 | 实际记录 | 能证明什么 |
| --- | --- | --- |
| runtime.log:32095/32098 | `proof=cp-scratch-fence ... scratch=6401cafe fence=1/1`，`state=ready` | GPU启动基线完成，不是此次surface失败前未ready |
| runtime.log:32167 | 116.608897秒，probe PID171创建surface10，32×32 BGRA，row256，0 planes，16384字节 | 普通IOSurface创建成功 |
| runtime.log:32168 | 116.609873秒，`user-buffer-failure method=3 status=e00002c7 input=32 output=8` | method3为BoMap，内核返回kIOReturnUnsupported；不是BoImport(method16)的失败回执 |
| probe stdout | base=0x100a90000、alloc=16384，工厂返回NativeBridgeMetalDevice，registry=4294967768 | 失败位于实际surface纹理导入，不在系统工厂或metallib阶段 |
| probe stderr | `surface import refused ... no-copy buffer: OutOfMemory(Device)` | 用户态保留的原始导入错误文字 |
| 结果JSON | `submit_flags=4`；pointer/copy/degraded/wrapper全0；epochs/CB均0，pixels_saved=false | cached能力位2关闭；没有成功发布导入/副本资源，没有本轮GPU像素验收 |

Probe证据在`log/host/gpu-v171/iosurface-runtime/`：
`nabu-iosurface-default-v171-probe.stdout.log`、同名stderr及
`nabu-iosurface-default-result.json`。`resources_released=false`表示没有走完测试的
释放验收，不能仅据这个字段宣称发生内核泄漏。用户已确认桌面、触摸正常并恢复Android。

## v168实际编译的路径

依据`artifacts/nabu-gpu-v168/build-report.json`的source_map，不能只读同名upstream文件：

| 单元 | v168实际源 |
| --- | --- |
| NativeAdrenoVm.cpp | `src/nabu/gpu/a640/NativeAdrenoVm.cpp` |
| NativeAdrenoCpu.cpp | `patches/nabu-gpu/NativeAdrenoCpu.cpp` |
| NativeAdrenoMemory.cpp | `src/nabu/gpu/upstream/Adreno6xx/NativeAdrenoMemory.cpp` |
| NativeAdrenoMemory.h | `src/nabu/gpu/a640/NativeAdrenoMemory.h` |
| NativeAdrenoUserClient.cpp | `src/nabu/gpu/upstream/Adreno6xx/NativeAdrenoUserClient.cpp` |
| NativeAdrenoGpuContext.cpp | `src/nabu/gpu/a640/NativeAdrenoGpuContext.cpp` |
| NativeAdrenoPublish.cpp | `patches/nabu-gpu/NativeAdrenoPublish.cpp` |

实际Cpu实现`:49`用`atop(physical)`查询当前VM页属性，适配16KiB内核页；不能把
upstream的`physical>>12`误当本轮实现。分类将COPYBACK、INNERWBACK、WTHRU都归
为Cached，将WCOMB归为NormalUncached。因此即使取得`cpuCacheMode=Cached`，仍须
记录原始WIMG/PTE/MAIR才能进一步断言WB，不能由此枚举或省略IOSurfaceCacheMode推断。

1. `importBo():293`先做参数与entry检查，调用`memory.importTask()`；成功后返回
   handle。`importTask():668`建立/prepare调用者内存descriptor，按GPU的4KiB粒度
   查询物理段及CPU cache分类，按连续性和属性聚合span。Unknown会在导入阶段拒绝；
   普通surface并不因Cached在这里拒绝。成功BoImport不等于成功GPU映射。
2. `mapBo():326`校验entry、IOVA、permissions等。`:353`只有VM已准入且内存为Cached
   才认为coherent；请求writeback=1而coherent=false会直接返回Unsupported。
   当前Turnip的`darwin_map_storage`请求writeback=0、shareability=2；`mapBo():362`
   仍将实际映射传给VM，并非把CPU页面改成NC。
3. 实际`NativeAdrenoVm::map():339–345`根据backing重算writeback：Cached为1、
   Mixed为2、NC为0，然后进入preflight。`:176–178`在Unknown、shareability不是2，
   或“不是NormalUncached/合格FirmwareUncached且cached_coherent_imports_关闭”时
   返回Unsupported。这个门槛发生在后续range数组分配和SMMU页表更新之前。
4. `NativeAdrenoGpuContext.cpp:64`只有`NABU_GPU_METAL`配置才调用
   `enableCachedCoherentImports(0x06040001)`。v168是SYSTEM_METAL/USERLAND配置，
   未启用该宏；实测caps=4也与此一致。现有enable函数`:132`只按芯片ID准入并置bool，
   没有执行本机一致性试验，注释中mainline/KGSL支持不等于当前移植已合格。
5. `Publish.cpp:1642`的错误日志只打印BoAlloc/BoMap/BoCpuMapV2的selector、status及
   结构尺寸，未打印BoImport成功、handle、cache模式、请求writeback或preflight阶段。
   因而本轮这行Unsupported可以明确定位到BoMap边界，不能独自消除所有内部候选。

已取得的Turnip补丁`src/unixnu-turnip/patches/mesa/turnip-resource-submit-v2.patch`
中`darwin_map_failure`将Busy转UNKNOWN、NotResponding转DEVICE_LOST，其余普通失败
转OUT_OF_DEVICE_MEMORY；Unsupported就在后一组。该函数还尝试释放失败对象，成功
才归还IOVA/ID。现有日志没有逐项释放回执，不能用零前端计数替代其清理证明。

结合默认分配、同一次纹理创建紧邻的BoMap失败、关闭的caps和上述源码，cached门槛
是强推断；仍缺原始cache属性及具体拒绝阶段。此次失败没有测试GPU读取WB脏数据、
GPU写后CPU可见性，也不是任何WB一致性成功或失败的硬件结果。

## 为何copy/degraded仍全0：已确认的iOS平台分支缺口

构建代理定位并在本任务复核的26patch派生树为：
`build/nabu-iosurface-stats-v2-host/.cache/gpu-reference/metal2vulkan/`
`crates/metal2vulkan-runtime/src/`。170产物及171复用前端来自iOS目标，不是macOS目标。

- `buffer_descriptor.rs:550–556`：可复制的pointer import遇到合格错误会进入
  `copied_buffer(..., Some(error))`，保留原OOM。
- `copied.rs:242–267`：真实`mach_vm_read_overwrite`只在`target_os="macos"`编译。
  `:271–273`的`not(any(linux,macos))`包括ios，因此iOS读取函数恒返回false。
- `CopiedBuffers::add():118–119`在初次快照读取失败时返回Unreadable。
- `buffer_descriptor.rs:1297/1344–1350`将Unreadable映射回先前的`failed`，所以外层
  仍看到原始OutOfMemory(Device)，不是一个明确写着“copy快照不可读”的新错误。
- `:1380`才递增copied/degraded计数；前一步已经退出，故本轮全0与此分支完全吻合。

这说明“复制兼容资源未成功建立”，不说明“runtime没有尝试选择副本路线”。修复只需
让iOS与macOS使用同一Mach读取实现，并把ios从恒false分支中排除；保持错误处理、
真实copy-in/merge-back及计数不变。不能把`read_pages`改成无条件true，也不能只把
结果判定放宽来绕过这个问题。

**该精确修复可以先保持v168内核不变。** 复制后端使用已有owned内存接纳CPU副本，
提交时同步CPU改动，完成时merge-back回普通IOSurface，不要求GPU映射原Cached页。
下轮应先见Mach自检成功，再见copied_buffers=1、degraded=1、pointer imports=0、
两向复制流量>0，然后32epoch/64CB、全部像素/guard正确及资源释放。BoMap Unsupported
仍可能在尝试原始导入时出现；若副本随后正确完成，它是已记录的降级触发，不应宣称为
共享导入。in-place/shadow仍单列，副本的内部alias不能变成原surface零CPU副本。

## 如果后续仍要单独做WB一致性实验

先补证据再开放该试验；以下是限定范围的设计建议，没有实现或启用。

**最小诊断**只针对本次probe的surface地址/长度和导入handle：记录BoImport阶段及
返回值、CPU cache枚举和实际WIMG、物理span数量/各span属性，BoMap请求和VM重算的
writeback/shareability、cached许可来源、精确preflight拒绝原因及返回值。若试验允许
映射，再只记录这几页的实际用户/内核别名PTE与MAIR解释、GPU叶PTE/MAIR/SH、实际
完成fence和SMMU fault状态。CPU分类来自pmap元数据，不能替代真实PTE的独立证据。
现有`map_failure_reason=Other`不足以单独确认cache门槛。无需先为复制修复重编内核
加入这些诊断，它们属于后续WB专项。

**最小开关必须真正限于测试调用。** `Publish.cpp:776/1888`显示各客户端共享g.vm；
直接调用现有`enableCachedCoherentImports()`会改变所有客户端的VM资格，不能因为
调用者是probe就称为按进程隔离。应使用默认关闭的独立试验构建/启动开关，将允许
Cached的资格绑定到已准入测试进程本次import对象/地址范围，并作为该次map的显式
许可传到preflight；关闭连接后取消资格。普通客户端、旧Metal能力声明和owned NC
策略保持原样，不泛开`NABU_GPU_METAL`，不全局声明CachedCoherentImports已合格。

保留CPU原有缓存属性；单独把某个别名改NC、仅增加DSB或修改IOSurfaceCacheMode
元数据都不是WB试验。若实际确认全部为WB，映射仍按该backing属性选择WB及Outer
Shareable，并记录GPU实际页表；不以chip quirk替代数据验证。

首个有界试验可复用本轮单surface、显式completion和32种像素模式，但必须关闭副本
兜底或用真实统计严格拒绝副本，避免将副本通过算成WB通过。至少覆盖：

1. CPU写入脏cache后GPU读取，GPU结果由已验证的NC输出读回，不先flush原WB页来
   掩盖硬件一致性问题。
2. CPU先读取旧内容使cache有效，GPU局部改写，真实fence完成后CPU直接读取；记录
   有效像素、同cache line未改写区域、行padding及尾部，避免把局部覆盖误当整页写入。
3. 在生产者/消费者明确互斥下重复交替；Surface、所有别名及导入对象保留到GPU完成
   与读者结束，再按既有顺序释放。测试不接presenter、无跨进程隐式同步或扫描输出。

当前`NativeAdrenoMemory.cpp:821/828`只做DSB，没有WB clean/invalidate；前端因现有
HardwareCoherent标志可跳过flush。二者都不是WB资格证据。第一块16KiB通过仍只说明
该用例；多页/多别名/另一进程及重复释放要分阶段验证，完成前不能提升全系统能力位。

## 本次新增的实际Mach读取自检

父任务在确认平台缺口后授权修改
`userland/nabu/src/gpu_iosurface_default_probe.mm`：surface用既有0xc7初始化整个
allocSize后，调用一次`mach_vm_read_overwrite(mach_task_self(),...)`读到独立、
预先清零的malloc缓冲。须KERN_SUCCESS、完整字节数和memcmp相同才进入GPU导入。
失败stage为`surface_mach_read`，marker为0x6e12；JSON记录attempted/status、
requested/copied bytes、equal/passed，未调用status=-1。真实Mach调用留下一轮iOS
验收，Linux检查没有模拟它为成功。

自检位于before_import计数基线之前，不改变GPU像素流程、32epoch/64CB或严格路径
分类；该诊断CPU复制也不写runtime copied计数。Clang18原有分类检查通过，新增调用
顺序检查通过，git diff --check通过。未拼装本地Apple SDK；完整编译由后续macOS CI负责。
