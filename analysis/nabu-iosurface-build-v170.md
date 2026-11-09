# 第170轮独立 NC IOSurface 构建与统计接口

2026-11-09。第169轮标准 `MTLCreateSystemDefaultDevice()` 和原三项实际Metal测试已通过，
用户确认桌面、触摸正常并恢复Android；日志已备份清空，APFS139。
本轮复用该内核、标准发现bundle和带bindfs权限的helper，只新增独立surface测试与必要统计。

## 统计接口与真实含义

公开头为 `userland/nabu/src/NabuMetalSurfaceStats.h`：

```c
bool native_bridge_metal_surface_stats(NabuMetalSurfaceStats *out);
void native_bridge_metal_trim_surface_imports(void);
```

结构含30个uint64_t，共240字节。前27项为runtime累计import/copy/in-place/shadow及
in-place检查计数；最后3项为原frontend的surface imports made/released与当前held cache大小。
快照不做wait、trim、资源创建、提交或策略设置；设备必须已通过标准工厂打开。
各字段并非跨层原子快照，probe需在GPU及完成handler结束、创建/释放静止后比较。

`host_pointer_imports_made` 和对应bytes的递增位于
`src/metal2vulkan/crates/metal2vulkan-runtime/src/buffer_descriptor.rs:1532–1546`：
`Memory::import_host` 成功，且 `bind_buffer` 返回Ok后才计数；拒绝和失败路径不计入。
`copied_host_buffers_*` 与实际copy-in/merge-back bytes单独输出，因此surface包装器构造
成功或像素正确不会被当作指针导入成功。in-place与shadow计数反映选择到的image路径；
它们本身不构成本机像素、padding或缓存一致性验证。

原 `Device::work_counts()` 会先调用 `deferred.lower_all()`，会触发尚未lower的render工作，
不能直接作为严格只读接口。本轮另加
`0026-nabu-read-only-surface-counts.patch`：在 `work_counts.rs` 追加
`NabuSurfaceWorkCounts` 和 `Device::nabu_surface_work_counts()`，仅执行27次
`AtomicU64::load(Ordering::Relaxed)`。原公开work_counts及其行为完全保留。
shadow拒绝原因的数组下标与原WorkCounts取值逐项对应，未合并或伪造理由。

`patches/nabu-metal/NativeMetalSurfaceStats.rs` 将窄快照送入C结构；
`NativeMetalSurfaceStats.inc` 从既有frontend gDevice查询，并在原surface锁下读取made、
released及held大小。二者只追加到项目派生副本。原releaseSurface在CFRelease前递增released，
所以released相等不是跨线程释放fence；probe仍需完整的completion/handler结束、autorelease
排空和同步trim，再归还最外层NC BO。

## 构建范围与冻结输入

`tools/build_nabu_gpu_metal_probe.py` 新增可选 `--iosurface --system-metal-input` 模式。
没有该参数时保持原Metal probe、shader、默认构建参数与产物。surface模式限定16.5/528、
Rust1.98.1、LLVM21、Xcode16.4；开启的scanout、QC、A740 replay宏仍为0，移除旧QC地址
诊断的既有适配继续生效，没有修改cached import或runtime image/import策略。

原25项runtime patch的文件与顺序原样保留；surface模式只在派生series末尾登记第26项
只读统计patch，以继续使用原装配器的完整patch核验。报告分别列出
`qualified_runtime_patches`（25项）、`runtime_patches`（26项）和
`readonly_statistics_runtime_patch`。统计patch进入原有runtime源码身份计算，因此统计版
shader cache键与上一构建自然分开；没有另加cache策略。

| 输入 | 本轮使用方式 |
| --- | --- |
| CI42576001993 / nabu-gpu-vulkan-1 | 原Turnip，复制且不重签 |
| 原pin AdrenoMetal、metal2vulkan及nabu frontend patches | 同一编译链，追加只读统计后重编frontend/Rust桥 |
| CI42603179764 / nabu-system-metal-2 | 复制第169轮合格NativeAdrenoMetal.bundle、mount helper及mount job，不重编或重签 |
| gpu_iosurface_probe.mm / gpu_iosurface_smoke.metal | 独立probe与metallib；probe basename继续为nabu-gpu-metal-probe |

构建器验证新frontend包含 `_native_bridge_metal_surface_stats`、
`_nmb_device_surface_stats`、`_native_bridge_metal_trim_surface_imports` 三个出口。
probe仍使用原GPU测试entitlements；本轮没有预先扩大IOSurface权限。

## CI与打包步骤

新工作流为 `.github/workflows/gpu-iosurface.yml`，artifact名
`nabu-gpu-iosurface-<run_number>`，内容目录 `nabu-gpu-iosurface/`。
本子任务没有提交、push或派发CI。主任务可在源码冻结后执行：

```text
gh workflow run gpu-iosurface.yml --ref nabu16-bootstrap
```

工作流下载上表两个合格artifact，安装同一编译器后执行：

```text
python3 tools/build_nabu_gpu_metal_probe.py --iosurface \
  --system-metal-input inputs/system-metal/nabu-system-metal \
  --work build/gpu-iosurface --output artifacts/nabu-gpu-iosurface \
  --turnip-input inputs/turnip-vulkan/nabu-gpu-vulkan \
  --mtl-device-bytes 528 --llvm-as "$(brew --prefix llvm@21)/bin/llvm-as"
```

修改共用构建器也会触发现有gpu-metal.yml；若本次只需要第170轮，可由主任务取消该次
冗余独立Metal构建，不改旧工作流的默认行为。

CI完成后下载对应artifact，仅在此次下载完成时按项目规则审查。检查build-report的
`result=signed_not_run`、528、工具链、25+1 patch清单、三个统计出口、原Turnip来源，以及
复用bundle/helper的 `source_ci.run_id=42603179764`。

| artifact内文件 | NabuInit位置 |
| --- | --- |
| nabu-gpu-metal-probe | sbin/nabu-gpu-metal-probe |
| libnabu-metal-frontend.dylib | sbin/libnabu-metal-frontend.dylib |
| libvulkan_freedreno.dylib | sbin/libvulkan_freedreno.dylib |
| nabu-iosurface-smoke.metallib | sbin/nabu-iosurface-smoke.metallib |
| nabu-metal-plugin-mount | sbin/nabu-metal-plugin-mount |
| NativeAdrenoMetal.bundle | metal-addons/NativeAdrenoMetal.bundle |
| LaunchDaemons/org.nabu.metal-plugin-mount.plist | 对应LaunchDaemons位置 |
| LaunchDaemons/org.nabu.iosurface-probe.plist | 对应LaunchDaemons位置 |

目录及可执行文件root:wheel 0755，plist和签名资源0644；bundle executable仍需显式0755。
本轮替换前次标准Metal/独立Metal测试job，只保留mount job和本轮surface job。
新job为mobile、LaunchOnlyOnce、AGXAccelerator LaunchEvents，运行
`/redwood/sbin/nabu-gpu-metal-probe --run-iosurface-nc`，保留同一mount-ready gate和工厂准入名。
内核可复用第169轮；本次只换bootstrap测试内容。

结果为 `/var/mobile/Media/nabu-iosurface-result.json`，实际像素为
`nabu-iosurface-readback.bgra`，元数据为 `nabu-iosurface-readback.json`；stdout/stderr为
`nabu-iosurface-probe.stdout.log` 和 `.stderr.log`。这些文件与旧Metal结果分开。
预定32个epoch各采样和覆盖一次，加1个生命周期command，共65个真实完成；输出in-place/
shadow分类，任何copied-host-buffer或对应复制字节增量均不能判为共享导入通过。

用户已明确后续真机不额外重启Android：由主任务在当前恢复后的Android直接回收/部署，
仅为临时启动切到bootloader。本构建子任务不操作设备。

## 本地检查与仍待验证内容

- Python语法、workflow YAML、生成的mobile/AGX job及工厂复用装配通过。
- 原默认stage不含统计；surface派生只追加前端/桥接出口和登记的只读patch。
- 原25项加统计patch的正向应用与整套反向还原核验通过；Windows host临时核验设
  `core.autocrlf=false`以保持源码行尾，CI路径未改。
- C/Rust的30项字段顺序一致；C++实际wrapper经WSL clang++的-Wall/-Wextra/-Werror编译，
  240字节及逐项offset、快照值、无计数修改、失败不改输出均通过。
- 新runtime方法仅27次原子load；原work_counts完整保留，未调用deferred lowering。

证据：`log/host/iosurface-v170/stage-check.json`、`stats-check.json`、
`surface-stats-compile.log`、`surface-stats-host.log`。
本机没有Rust或完整iOS SDK；原生Rust/Objective-C/Metal编译和签名须由CI确认。
这些host检查不是IOSurface实机验收，也不代表普通WB surface或桌面呈现已通过。
