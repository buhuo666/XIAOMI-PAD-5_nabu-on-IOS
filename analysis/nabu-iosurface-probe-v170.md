# 第170轮独立NC IOSurface探针

本子任务新增并冻结 userland/nabu/src/gpu_iosurface_probe.mm 和
userland/nabu/src/gpu_iosurface_smoke.metal。未修改原Metal probe、factory、内核或
构建脚本；未提交、运行CI或操作设备。构建/只读统计接口由并行任务负责。
第169轮标准工厂实机已通过；本探针尚待CI编译及实机运行。

## 输入、输出与验收

产物basename为nabu-gpu-metal-probe，唯一参数--run-iosurface-nc。
保留528字节_MTLDevice检查、真实GPU ABI及A640 chip检查、当前boot的readonly
union mount ready验证、AGX插件属性、标准工厂仅打开一次和registryID匹配。
不调用独立bridge构造入口；要求HostImport/CpuMapV2存在，cached imports关闭。

metallib：/redwood/sbin/nabu-iosurface-smoke.metallib。
三个函数：nabu_surface_vertex、nabu_surface_sample、nabu_surface_color。

| /var/mobile/Media/下的文件 | 内容 |
| --- | --- |
| nabu-iosurface-probe.stdout.log / stderr.log | 构建任务配置的逐阶段输出和错误日志 |
| nabu-iosurface-result.json | 完整结果、30字段counter快照、epoch/保护区/生命周期结果 |
| nabu-iosurface-readback.bgra | 第31个epoch后从IOSurfaceGetBaseAddress实际读取的32×32 BGRA8，tight 4096字节 |
| nabu-iosurface-readback.json | 像素来源、run_id、epoch、layout和错误数 |

run_id使本次结果与像素metadata对应；早期失败时pixels_saved=false，不能采信旧文件。
实际surface行距256字节，每行有效128字节，行间128字节为0xc7。
原BO分配完整VM页并保留尾部guard；当前16KiB页下分配16384字节，尾部8192字节。

通过条件：

- result=pass、shared_import=true、copied_fallback=false；
- epochs_completed=32、completed_command_buffers=65；
- sample_pixel_errors/direct_pixel_errors/surface_padding_errors/surface_tail_errors/readback_guard_errors=0；
- lifetime_held_before_commit=true、lifetime_pixels_checked=1024、lifetime_pixel_errors=0；
- imports_released=true、owner_released=true、pixels_saved=true；
- 恰好一次实际pointer import，bytes增量等于整个owner allocation，最终import数不增加；
- 所有copied buffer/copy-in/merge-back计数保持基线。

direct_image_alias和in-place/shadow计数单独报告。共享BO导入、正确像素和资源释放
是本轮结果；若texture使用GPU shadow，不据此声称直接image alias。任何CPU副本
回写路径都直接失败，不能计为shared import通过。

## 内存、像素与释放路径

owner使用独立0x4147连接的BoAlloc和BoCpuMapV2，保留handle/map_id/connection。
它不做GPU BoMap；IOSurfaceAddress包装完整CPU映射，纹理import建立GPU映射。
返回base必须等于owner地址，plain/plane0、BGRA8、尺寸、行距和allocation必须匹配。

32轮CPU图案使用6种精确UNORM端点颜色，横向变化另带epoch/6，使32幅图案互不相同。
每轮CPU Lock写有效像素并Unlock，GPU nearest采样到私有BGRA target，再blit到带
prefix/padding/suffix保护区的owned NC readback；真实Completed后验证读回和source。
随后GPU以Load/Store保留背景，在16×16 scissor内写入本轮颜色；Completed后CPU通过
IOSurface base直接核对全部1024像素、每行padding及allocation尾部，并检查counter。

第65个command验证持有期：编码后释放应用texture/IOSurface引用并排空临时对象，
weak texture必须仍由command持有；owner BO保持。真实完成后用owner原映射验证新的
局部GPU结果。实际像素文件保留此前第31个epoch，metadata明确标识。

释放次序：最后command waitUntilCompleted（含handlers）→整个exerciseSurface
autoreleasepool退出→同步trim→静止counter检查→BoCpuUnmapV2→BoFree→关闭owner。
计数相等本身不充当跨线程fence；上游gSurfaceImportsReleased在CFRelease之前增加
的语义保持不变。失败路径不强制释放仍可能被GPU引用的原owner。

## after_import计数的同步依据

不依赖原Device::work_counts().deferred.lower_all()的副作用：

1. NativeBridgeMetalFrontend.mm:243的surfaceBuffer同步调用nmb_buffer_new_no_copy_releasing。
2. NativeMetalObjects.rs:711的no_copy在当前线程调用new_buffer_with_bytes_no_copy，
   取得结果后才返回NmbBuffer。
3. metal2vulkan-runtime/src/buffer_descriptor.rs:1533同步import_host，:1540 bind_buffer；
   成功分支:1545立即shared.counts.host_pointer_import_made(size)，然后返回placement。
4. 计数和bytes的AtomicU64 fetch_add(Relaxed)在同一线程早于构造返回后的快照；
   texture构造失败仍由probe另行拒绝。

因此严格只读Atomic load不会在这里漏掉合法的deferred import。surface wrapper计数
以及texture in-place/shadow另行记录，不能互相替代。

## 本地校验

log/host/gpu-iosurface-probe/host-check.json记录：

- 从实际probe提取的像素、保护区及副本判定函数经Clang18编译/执行通过；
- 32个epoch唯一；正确输入/局部覆盖通过；错误像素、旧epoch、行padding、尾部、
  readback前缀/行间/后缀破坏均触发失败；
- lifetime最后一轮覆盖与前一轮有256个不同像素；
- 五项copied计数分别单独变化均拒绝；
- JSON覆盖稳定统计头全部30字段；标准factory调用一次、owner无GPU BoMap，
  autorelease→trim→owner释放顺序通过检查。

这是CPU校验逻辑测试，不是GPU模拟运行结果。完整Objective-C++语法检查尚未通过：
从既有固定16.5 SDK稀疏仓库提取部分framework头后，LLVM停在缺少Security.framework头
及外部SDK inline warning，还未检查到probe主体。按父任务要求停止扩展本地SDK；
完整Objective-C++、Metal编译及签名交给macOS CI，不把本地检查写成原生编译成功。

跨进程、普通WB、presenter/scanout及GPU更新seed均后置。设备工作由父任务处理，
遵循不额外重启Android环境的用户约束。
