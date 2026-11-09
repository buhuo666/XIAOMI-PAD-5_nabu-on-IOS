# 第171轮普通 IOSurface 分配路径：轻量构建

2026-11-09。第170轮NC wrapped IOSurface实机通过：真实pointer import一次/16KiB，
copy0、in-place1、shadow0、65个command buffer完成并释放；用户确认桌面、触摸正常，
日志已备份清空，APFS140。第171轮仅观察普通 `IOSurfaceCreate` 默认分配路径，
内核cached imports继续关闭；现有copied-host-pages兼容路径与共享导入分别验收。

## 构建范围

新增 `tools/build_nabu_iosurface_default_probe.py` 和
`.github/workflows/gpu-iosurface-default.yml`，不修改第170轮源文件或旧构建流程。
仅用Xcode16.4编译 `userland/nabu/src/gpu_iosurface_default_probe.mm`，目标iOS16.5、
`_MTLDevice`尺寸528，链接Foundation、Metal、IOSurface和合格统计前端。
新程序仍名为 `nabu-gpu-metal-probe`，走已通过的标准工厂准入路径。

全部依赖来自CI42607114009 / `nabu-gpu-iosurface-1` 的 `nabu-gpu-iosurface/`：

| 合格内容 | 第171轮处理 |
| --- | --- |
| libnabu-metal-frontend.dylib | 原样复制；保留30字段只读统计ABI |
| libvulkan_freedreno.dylib | 原样复制；来源仍可追溯CI42576001993 |
| nabu-iosurface-smoke.metallib | 原样复制；复用三个surface shader |
| NativeAdrenoMetal.bundle | 原样复制；保留第169轮标准工厂入口 |
| nabu-metal-plugin-mount | 原样复制；保留唯一bindfs entitlement |

构建器只读取合格输入的build-report确认来源和16.5/528契约，再复制依赖；不重新哈希、
审计或签名旧native文件。新probe使用第170轮相同的GPU测试entitlements，执行4KiB页
ad-hoc签名、strict verify、实际签名entitlements回读和目标检查。没有新增权限。
输入原始report保存为 `qualified-iosurface-input-report.json`，新report的每个复制项
保留原来源字段并增加 `reused_from_ci=42607114009`。

本轮没有Rust、LLVM工具链安装或编译，没有shader、Mesa、frontend、bundle/helper重编，
没有内核、cached import、runtime策略、scanout、QC或旧地址修改。

## 程序与计数契约

参数为 `--run-iosurface-default`，32个epoch、64个真实command buffer。
本轮没有提交前释放引用的NC owner生命周期子测试；释放验证在completion和handler结束后进行。
像素、padding、allocation尾部、command状态和资源释放必须全部通过，再按实际计数分类：

| path_classification | 指针导入增量 | 复制对象增量 | 复制字节增量 | 对外含义 |
| --- | --- | --- | --- | --- |
| zero_copy | pointer1，bytes等于surface allocation | made0、refused0、degraded0 | copy-in0、merge-back0 | shared_import=true；image alias还需单独看实际in-place/shadow计数 |
| copied_compatibility | pointer0、bytes0 | made1、refused0、degraded1 | copy-in和merge-back均大于0 | shared_import=false，direct_image_alias=false，仅复制兼容GPU通过 |

degraded1在此处表示已有runtime因真实导入失败而选择复制后端，是复制兼容路径预期计数。
不能为得到成功把它误要求为0，也不能把复制后的正确像素称为零拷贝。混合路径、后续路径
变化或其它计数组合由probe判失败；in-place/shadow原值继续单独报告。

输出使用独立前缀：

- `/var/mobile/Media/nabu-iosurface-default-result.json`
- `/var/mobile/Media/nabu-iosurface-default-readback.bgra`
- `/var/mobile/Media/nabu-iosurface-default-readback.json`
- `nabu-iosurface-default-probe.stdout.log` / `.stderr.log`
- `nabu-iosurface-default-mount.stdout.log` / `.stderr.log`

## CI与打包

新workflow为 `gpu-iosurface-default.yml`，macOS15/Xcode16.4，15分钟任务上限。
仅下载合格artifact和nabu ABI头，随后执行：

```text
python3 tools/build_nabu_iosurface_default_probe.py \
  --input inputs/qualified-iosurface/nabu-gpu-iosurface \
  --output artifacts/nabu-gpu-iosurface-default
```

主任务在全部源文件冻结后可派发：

```text
gh workflow run gpu-iosurface-default.yml --ref nabu16-bootstrap
```

产物名为 `nabu-gpu-iosurface-default-<run_number>`，内容目录
`nabu-gpu-iosurface-default/`。新路径不触发原重编Rust的gpu-iosurface/gpu-metal工作流。
此次下载按项目规则完成一次审查即可；新report应显示只有probe编译/签名，所有依赖的
`*_rebuilt=false`、`reused_ci_run=42607114009`，实际执行仍标为未验证。

打包沿用第170轮内核，替换bootstrap测试内容：

1. `sbin/`放入新probe及四个复用文件：frontend、Turnip、surface metallib、mount helper。
2. `metal-addons/NativeAdrenoMetal.bundle/`保持合格bundle，executable显式root:wheel 0755；
   目录和其他可执行文件0755，plist/签名资源0644。
3. 只启用 `org.nabu.metal-plugin-mount.plist` 和 `org.nabu.iosurface-default-probe.plist`。
   移除本轮bootstrap中的旧 `org.nabu.iosurface-probe` 测试job，避免与NC测试并发。
4. mount job仍为root/RunAtLoad/LaunchOnlyOnce，只改变日志名；新probe job仍为mobile、
   LaunchOnlyOnce、AGXAccelerator matching，保留mount-ready和标准工厂检查。

设备由主任务操作：用户恢复Android后直接回收/部署，仅为临时启动切bootloader，不额外
重启Android。本构建子任务没有提交、push、派发CI或设备操作。

## 本地检查

Python语法、workflow YAML、合格输入复制装配、root mount job仅日志变化、mobile AGX
matching和参数、独立日志名均通过；确认没有复制旧probe充当新程序，且只有一次clang++
编译调用，没有Rust或Metal编译调用，也没有对旧依赖的签名命令。
记录位于 `log/host/iosurface-default-v171/build-source-check.json`。
原生Objective-C编译/链接/签名仍需新CI完成；普通surface的真实路径分类须由第171轮设备
结果确认，不能由第170轮NC成功推定。
