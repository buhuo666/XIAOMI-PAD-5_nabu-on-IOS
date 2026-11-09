# 第171轮：默认分配IOSurface探针

新增并冻结 userland/nabu/src/gpu_iosurface_default_probe.mm。
第170轮probe、shader、统计头、前端及内核均未修改。新构建只重编此probe，
复用170实机合格的nabu-iosurface-smoke.metallib及三个shader函数。
本子任务未提交、派发CI或操作设备；不拼装本地SDK，不额外重启Android。

## 默认分配与测试范围

IOSurfaceCreate只提供Width、Height、BytesPerElement、BytesPerRow、PixelFormat五项。
没有IOSurfaceAddress、AllocSize、CacheMode或独立NC BO owner。
0x4147连接只查询既有GPU ABI/caps，随即关闭；不发BoAlloc、BoMap、CpuMapV2。
系统工厂、528字节检查、当前boot的readonly插件挂载检查沿用170。
cached-import能力仍要求为0。

保留同样的32个唯一epoch、GPU nearest采样到私有BGRA target及blit读回、
GPU 16×16局部改写后CPU直接读取、行padding/尾部/读回保护区检查。
总计64个Completed命令缓冲，不执行170的提交前释放第65个command。
所有CPU base读取均在surface仍被持有的exerciseSurface作用域内。
完成后排空autorelease，调用既有trim，确认资源释放计数和held恢复基线。

这项测试称为“默认分配IOSurface”。未指定CacheMode不等于已经证明页面为WB。
zero_copy枚举只表示真实pointer导入且没有CPU主机副本；GPU图像是否直接别名还须
结合direct_image_alias和shadow计数，不能扩大为所有层都无复制。实际CPU页cache
属性仍应结合内核证据。IOSurface的cacheMode返回值不是PTE证据，
本轮不直接取得WB硬件一致性资格，也不接入presenter/scanout。

## 严格分类

下表全部为相对before_import的增量，整个测试必须维持同一路径：

| 计数 | zero_copy | copied_compatibility |
| --- | --- | --- |
| host_pointer_imports_made | 1 | 0 |
| host_pointer_import_bytes_made | 实际surface allocSize | 0 |
| copied_host_buffers_made | 0 | 1 |
| copied_host_buffers_refused | 0 | 0 |
| copied_host_buffers_degraded | 0 | 1 |
| copied_copy_in_bytes | 0 | 每轮GPU完成后相对基线须>0 |
| copied_merge_back_bytes | 0 | 每轮GPU完成后相对基线须>0 |
| host_textures_in_place | 记录 | 记录，不参与路径判定 |
| shadowed_textures | 记录 | 记录，不参与路径判定 |
| shared_import | true | false |
| direct_image_alias | 仅in-place增量1且shadow增量0时true | 始终false |

copied_compatibility中的degraded=1是已明确允许的已知导入失败触发副本计数：
turnip-resource-submit-v2.patch的darwin_map_failure把一般BoMap失败转为Vulkan OOM，
runtime buffer_descriptor.rs:553/1603的copies_after可进入copied_buffer。
这一计数不被当作真实共享导入成功；具体设备失败原因仍看实际日志，不能仅凭计数推断。
caller import-gate拒绝造成的refused>0、混合路径、错误大小、多次构造或路径变化均失败。

分类不是最终通过：还须32epoch/64CB、所有像素和guard错误为0、实际像素成功保存，
surface包装器made/released各增量1且held恢复基线。shadow的全部理由保留在30字段
counter快照中；复制兼容成功不称为shared import或direct-image-alias。
复制兼容路径的GPU临时存储也可能使用内部alias，因此in-place增加不拒绝该路径，
也不等同原IOSurface的零CPU副本或直接图像别名。

## 参数、输出和字段

产物basename仍为nabu-gpu-metal-probe；唯一参数--run-iosurface-default。
metallib仍是/redwood/sbin/nabu-iosurface-smoke.metallib。

/var/mobile/Media/下：

- nabu-iosurface-default-probe.stdout.log / stderr.log：probe日志。
- nabu-iosurface-default-result.json：完整结果及counter/epoch快照。
- nabu-iosurface-default-readback.bgra：实际32×32 BGRA8，tight 4096字节。
- nabu-iosurface-default-readback.json：run_id、epoch、layout、来源和路径分类。

实际surface的source row为256。allocSize由IOSurface返回并记录，必须完整页、
大于8192字节像素行范围，以实际尾部作为guard。当前16KiB页预期尾部8192字节。
像素文件在最后一个epoch或像素检查失败时从仍持有的surface直接保存；
run_id把它与本次结果关联。pixels_saved=false时不能读取旧文件冒充本次结果。

完整结果关键字段：

- result=pass/fail，path_classification=zero_copy/copied_compatibility/invalid/unclassified。
- shared_import、copied_fallback、direct_image_alias。
- pointer_imports_delta、pointer_import_bytes_delta、copied_buffers_delta、
  copied_refused_delta、copied_degraded_delta、copy_in_bytes_delta、merge_back_bytes_delta。
- epochs_completed=32、completed_command_buffers=64。
- sample_pixel_errors/direct_pixel_errors/surface_padding_errors/surface_tail_errors/readback_guard_errors=0。
- resources_released=true；lifetime_before_completion_tested=false；
  release_after_completion_tested在32轮64CB完成后才为true。
- counters_before/created/after及逐epoch快照全部保留；创建失败时after也保存最新快照。

## 必要本地检查

log/host/gpu-iosurface-default-probe/report.json：实际分类函数经Clang18编译和执行，
零CPU副本、已知复制兼容、复制路径内部alias、真实复制流量及12项异常/混合负例
通过检查；路径变化会失败。
像素/guard判定和颜色绘图函数与170完全相同，未重复构建模拟GPU测试。
另检查默认创建仅五项属性、无独立BO owner、无提前释放、工厂只调用一次和64CB条件。
git diff --check通过。完整Objective-C++编译和设备执行由后续CI/父任务负责。

## 第171轮失败后的Mach读取自检

第171轮实机在surface_import失败，尚未执行GPU命令。后续测试在普通surface创建、
整份allocSize写入既有0xc7保护字节之后，GPU导入之前，新增实际
mach_vm_read_overwrite(mach_task_self(), ...)调用。目标是独立malloc CPU缓冲，
预先清零；须KERN_SUCCESS、完整读取allocSize且memcmp完全相同才继续。
不改变surface原始初始化、32个GPU epoch、64个command或路径分类。

marker为0x6e12，stage=surface_mach_read。JSON新增mach_read_attempted、
mach_read_status（未调用为-1）、mach_read_requested_bytes、mach_read_copied_bytes、
mach_read_equal和mach_read_passed。该CPU诊断复制不计入runtime的copied-host-buffer
统计，不代表GPU导入或副本后端已经成功。真实Mach调用的验收由后续iOS实机完成。
