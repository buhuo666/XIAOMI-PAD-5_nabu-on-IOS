# 第172轮：修复 iOS 的 copied-host-pages 初次读取

2026-11-09。第171轮标准工厂、ABI、默认IOSurface创建通过，但创建纹理时得到
`no-copy buffer: OutOfMemory(Device)`；pointer/copy/degraded/wrapper计数均为0，
尚未执行GPU command。用户桌面、触摸正常并恢复Android。

## 实际生产路径中的原因

此次依据第170轮CI42607114009、源码926fea73的实际26patch派生树，路径为：
`build/nabu-iosurface-stats-v2-host/.cache/gpu-reference/metal2vulkan/`。
CI报告明确列出25项合格patch加0026统计patch；bridge构建命令为 `--target ios`，
最终Rust目标为 `aarch64-apple-ios`，不是macOS host构建。

该树 `crates/metal2vulkan-runtime/src/copied.rs:241–268` 的Mach reader仅由
`#[cfg(target_os = "macos")]` 启用；`:270–273` 的替代函数排除列表只有linux/macos，
故iOS实际选择了恒定返回false的 `read_pages()`。

错误和计数的顺序是：

1. `NativeMetalObjects.rs:711–765` 使用 `HostMemory::new` 并转交runtime；没有额外的
   禁止复制gate。frontend surfaceBuffer传入Shared选项。
2. `buffer_descriptor.rs:550–556` 将可复制的导入OOM/Vulkan错误交给 `copied_buffer`。
3. `copied.rs:105–114` 初次读取返回false，于是 `CopiedBuffers::add` 返回Unreadable。
4. `buffer_descriptor.rs:1344–1350` 释放刚分配的复制存储，并将Unreadable映射回原导入错误，
   因而外层仍显示OOM(Device)。直到`:1380`才递增copied/degraded计数，故本轮两者均为0。

内核日志另有BoMap Unsupported（method3/status e00002c7），它解释原导入的拒绝；
copy reader的平台遗漏解释为何既有复制兼容路径也无法建立。日志没有copy分支内部trace，
不能排除早于初读的独立内存分配错误；但iOS的false分支是确定存在、必须修复的障碍。
这组证据不构成开启cached imports的理由。

## 最小修复与Mach ABI

新增 `patches/nabu-metal/0027-nabu-ios-copied-host-read.patch`，仅改变两处cfg和两处注释：
Mach reader适用范围扩为macOS或iOS；false替代分支相应排除iOS。
Mach函数体、错误处理、复制/合并算法、计数和资源所有权均保持原样。
原25项patch和0026只读统计patch的内容与顺序保持不变。

第170轮Cargo.lock的libc版本为0.2.191。该版本的 `src/unix/bsd/apple/mod.rs` 是由
`target_vendor="apple"`共用的模块，iOS与macOS都有以下类型：

| 类型 | 定义 |
| --- | --- |
| mach_port_t | c_uint |
| vm_map_t | mach_port_t |
| mach_vm_address_t / mach_vm_size_t | u64 |
| kern_return_t / KERN_SUCCESS | c_int / 0 |

它们与现有extern声明及XNU `vm_user.c:890–921` 的Mach接口一致。`mach_task_self_`
也已被本前端在iOS的pages_identity路径使用；不需要额外entitlement。
libc源包经本地19999代理下载，在下载时完成一次类型审查，记录为
`artifacts/iosurface-copy-read-libc-source/download-review.json`；未修改依赖或重复哈希审计。

default probe同时新增真正的self-read自检：在默认surface整份allocation初始化、Unlock后，
GPU导入前，以 `mach_vm_read_overwrite(mach_task_self(), base, allocSize, ...)` 读到独立
CPU缓冲并比较。stage为 `surface_mach_read`，marker0x6e12；新增
`mach_read_attempted/status/requested_bytes/copied_bytes/equal/passed` JSON字段。
只有调用成功、完整读取且内容相等才继续导入。此probe改动由ioaccelerator子任务负责。

## 新构建模式与保留行为

完整builder新增：

```text
--iosurface-copy-read --iosurface-input <CI42607114009的nabu-gpu-iosurface目录>
```

该模式隐含surface统计，使用27项patch，编译修复后的Rust/frontend和default probe，
并原样复用第170轮Turnip、surface metallib、标准工厂bundle及bindfs helper。
Rust1.98.1、LLVM21、Xcode16.4、iOS16.5/528保持不变。
metallib不重编；新frontend不会被复制的旧输入覆盖。

原无surface模式仍使用25项patch和原Metal probe；原 `--iosurface` NC模式仍使用25+26，
没有0027；第171轮轻量default builder仍默认复制全部合格依赖。
其 `reuse_inputs` 只新增可选skip参数，供新完整builder跳过已生成的frontend和Turnip，
默认调用行为不变。

没有修改内核cached imports、memory policy、host texture策略、scanout、QC或旧地址路径。
复制兼容仍必须报告 `shared_import=false/direct_image_alias=false`，以及
pointer0、copied_made1、refused0、degraded1、真实copy-in/merge-back正增量。
32个epoch/64个GPU command、实际像素、保护区和完成后释放的标准不变。

## CI及打包

新工作流为 `.github/workflows/gpu-iosurface-copy-read.yml`。父任务统一审阅、提交后可派发：

```text
gh workflow run gpu-iosurface-copy-read.yml --ref nabu16-bootstrap
```

工作流只下载一个合格artifact作为复用输入，然后执行：

```text
python3 tools/build_nabu_gpu_metal_probe.py \
  --iosurface-copy-read --iosurface-input inputs/qualified-iosurface/nabu-gpu-iosurface \
  --turnip-input inputs/qualified-iosurface/nabu-gpu-iosurface \
  --work build/gpu-iosurface-copy-read --output artifacts/nabu-gpu-iosurface-copy-read \
  --mtl-device-bytes 528 --llvm-as "$(brew --prefix llvm@21)/bin/llvm-as"
```

artifact名 `nabu-gpu-iosurface-copy-read-<run_number>`，内容目录
`nabu-gpu-iosurface-copy-read/`。新report区分重编frontend与复用的metallib/helper/bundle，
并列出 `ios_copied_host_read_patch`、27项完整清单和Mach自检标准。
修改共用builder/default probe会触发部分旧workflow；父任务可取消本次冗余构建。

内核继续复用第171轮。bootstrap的sbin替换新frontend、新probe，放入原Turnip、
`nabu-iosurface-smoke.metallib`和mount helper；bundle放入metal-addons。
仅保留mount job与 `org.nabu.iosurface-default-probe`，参数仍为 `--run-iosurface-default`。
default日志/结果文件名保持第171轮协议，由父任务打包时加轮次前缀。
目录和executable 0755，plist/签名资源0644，bundle executable显式0755。
用户恢复后的Android不额外reset，只为临时启动切bootloader。

## 本地验证与边界

27项patch完整正向应用/反向还原通过。新增patch与预期两处cfg/两处注释完全一致，
Mach函数体不变；frontend/bridge逻辑与第170轮派生源码一致。
Python/YAML、复用内容不会覆盖新frontend、原三个构建模式的源码/装配检查均通过。

记录：`log/host/iosurface-copy-read-v172/build-source-check.json` 和 `old-modes-check.json`。
原生Rust/iOS编译、链接及Mach自检仍需新CI和实机；本地没有把这一修复宣称为复制GPU已通过。
本子任务不提交、派发CI或操作设备。
