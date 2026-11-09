# 第168轮标准 Metal 工厂测试构建

2026-11-09。第167轮独立 Metal 已通过 fill4096、compute1024、guards128、
render1024、colored256、other0、padding4096，三个command buffer全部完成，
实际 `_MTLDevice` 大小为528。下一步仅验证标准工厂发现与注册，不接入桌面呈现。

## 标准发现和进程范围

内核协作字段为 `AGXAccelerator : IOAcceleratorES`，继承当前内核已有基础类；
`MetalPluginName=NativeAdrenoMetal`、`MetalPluginClassName=NativeAdrenoMetalDevice`。
服务在GPU硬件ready之后发布，不加载原版IOGPUFamily。该部分由内核子任务负责。

`gpu_metal_factory.mm` 产生薄 `NativeAdrenoMetal.bundle`，入口为
`-[NativeAdrenoMetalDevice initWithAcceleratorPort:]`。它只允许 libc `getprogname()`
完整basename等于 `nabu-gpu-metal-probe` 的进程。其余进程直接返回nil，
不加载Rust前端、不访问shader cache、不查询或打开GPU用户客户端。

允许的进程通过传入service port读取真实registry ID，再加载已经通过的
`/redwood/sbin/libnabu-metal-frontend.dylib`，调用 `native_bridge_metal_open()`。
Turnip仍通过 `NativeAdrenoGpuPublished / 0x4147` 访问已验证硬件通道；
返回device的registry ID使用工厂提供的真实AGXAccelerator ID。
bundle没有链接Rust或前端库，只有在进程筛选通过后才通过dlopen加载前端。

同一 `gpu_metal_probe.mm` 增加 `--run-system-metal`，保留原 `--run-metal`。
标准模式在实际528核验、GPU ABI预检、挂载ready核验、AGX属性和bundle文件可见后，
首次调用 `MTLCreateSystemDefaultDevice()`。没有直接构造作为备用路径。
它核对返回类、registry ID、shim调用次数，再运行与第167轮相同的全部实际GPU测试。
测试主体仅在导出元数据中增加construction字段；着色器、资源、预期计数与读回未改。

## 当前bootstrap支持的放置与挂载

当前init只把NabuInit挂回 `/redwood`，没有自动把新bundle挂入Extensions。
标准Metal工厂查找 `/System/Library/Extensions/NativeAdrenoMetal.bundle`。
所用内核已支持 `bindfs + MNT_RDONLY | MNT_UNION`；源init的/bin叠加使用同一机制。

打包位置：

| NabuInit中的路径 | 运行时用途 | Unix权限 |
| --- | --- | --- |
| `sbin/nabu-metal-plugin-mount` | root挂载助手 | root:wheel 0755 |
| `sbin/nabu-gpu-metal-probe` | mobile标准工厂测试 | root:wheel 0755 |
| `sbin/libnabu-metal-frontend.dylib` | 已通过前端 | root:wheel 0755 |
| `sbin/libvulkan_freedreno.dylib` | 已通过Turnip | root:wheel 0755 |
| `sbin/nabu-metal-smoke.metallib` | 原样复用的MSL产物 | 可读 |
| `metal-addons/NativeAdrenoMetal.bundle/*` | Extensions上层内容 | 目录/可执行文件0755，其余0644 |
| `LaunchDaemons/*.plist` | 本轮两个任务 | root:wheel 0644 |

现有 `bootstrap_permissions()` 不会把metal-addons下面的bundle executable自动设为0755，
打包时应显式设置该文件元数据。原版OS文件不写入，旧第167轮一次性测试job不应同时启用。

构建产物附带两个job模板：root `org.nabu.metal-plugin-mount` 在RunAtLoad执行，
mobile `org.nabu.system-metal-probe` 使用AGXAccelerator的IOKit LaunchEvents。
两个任务的启动先后不作为正确性的依据：

1. root助手先清除 `/var/run/nabu-system-metal.ready`，挂载只读union。
2. 核对原AGXMetalA10.bundle的原节点仍可见，新bundle的Info.plist和Mach-O从映射路径
   读回与来源一致，并检查只读union标志。
3. 全部通过后才原子发布root:wheel 0644的ready JSON，记录当前 `kern.boottime`。
4. mobile probe最多等待30秒，检查root所有权、不可由普通用户写入、同一boot时间、
   来源路径和所有通过标志，再检查AGX属性及bundle文件，最后调用标准工厂。

因此部分mount成功但回读失败不会放行；旧Data即使残留ready文件，也不能作为其他boot的
成功标志。失败有明确阶段并退出，不在未就绪状态调用一次性缓存的Metal工厂。

stdout/stderr模板放在AFC可读的Media根目录；主任务打包时可加轮次名。
实际图仍为 `/var/mobile/Media/nabu-metal-readback.rgba` 与对应 `.json`，
内容来自完成后的MTLBlit读回，不由预期图生成。

## 构建与现有验证

`tools/build_nabu_system_metal_probe.py` 从CI42590211952 / `nabu-gpu-metal-1` 原样复用
frontend、Turnip和metallib，仅编译probe、thin bundle、mount helper并签名。
不重编Rust、Mesa或已冻结前端。新工作流为 `.github/workflows/system-metal.yml`。

```text
python3 tools/fetch_sources.py --only nabu
gh run download 42590211952 --name nabu-gpu-metal-1 --dir inputs/qualified-metal
python3 tools/build_nabu_system_metal_probe.py --input inputs/qualified-metal/nabu-gpu-metal --output artifacts/nabu-system-metal
```

手动派发命令：`gh workflow run system-metal.yml --ref nabu16-bootstrap`。
本子任务没有提交、push、派发CI或操作设备。共用probe改动也会触发现有gpu-metal.yml，
由主任务协调取消这次冗余Rust构建，不修改冻结构建条件。

本地验证：Python语法、YAML、job plist往返、v167测试主体逐字比较通过；
实际mount helper经host桩编译运行，核对root限制、只读union、原bundle保留、新bundle读回、
全部检查后原子发布ready、任一检查失败不发布ready。记录位于
`log/host/system-metal-v168/source-check.json` 与 `mount-helper-host.*.log`。
这些host测试不验证设备的挂载权限；第168轮实际结果与修复见下文。

## 第168轮挂载权限错误与最小修复

CI42601686196的编译和签名通过，设备也正常启动；用户确认桌面、触摸正常并恢复Android。
`log/host/gpu-v168/metal-runtime/nabu-system-metal-mount.stderr.log` 记录：

```text
NABU_METAL_MOUNT result=fail stage=union_mount errno=1 text=Operation not permitted
```

此阶段在 `geteuid()==0`、来源文件stat、目标目录statfs通过后才执行。
probe随后在 `plugin_mount_ready` 等待30秒后退出，未调用标准Metal工厂；因此本轮没有新的
GPU测试结果，Media里已有像素文件仍是第167轮的结果。

明确的拒绝条件在 `bindfs_mount()`：原XNU只接受 `com.apple.private.bindfs-allow`，
hakios补丁增加了PID1豁免，实际条件为：

```c
if (!IOCurrentTaskHasEntitlement(BINDFS_ENTITLEMENT) && proc_getpid(current_proc()) != 1) {
    return EPERM;
}
```

证据为 `src/hakios-8796/xnu/hakios.patch:1060–1076`，以及已应用补丁的
`build/xnu8796-capacity/tree/bsd/miscfs/bindfs/bind_vfsops.c:142–148`。
原有 `init.c` 的LaunchDaemons/HAL和可选 `/flash/bin` union均由PID1直接mount；
launchd启动的root子进程没有这个PID1豁免。第168轮构建脚本给helper签名时没有传入entitlements，
对应CI的 `build-report.json` 中helper签名命令也没有 `--entitlements`。

其它候选检查与本轮条件：

| 检查 | 源码/构建证据 | 判断 |
| --- | --- | --- |
| union未编入时直接EPERM | `vfs_syscalls.c:920–925`；CI42570303718的 `kernel-build.log:1205` 为DEVELOPMENT_ARM64_BCM2837，`MASTER.arm64.bcm2837:29` 的FILESYS_DEV启用config_union_mounts | 本次构建支持union |
| 覆盖目录所有者/root | `vfs_syscalls.c:1902–1914` | root通过身份条件；若getattr本身失败仍可映射为EPERM，但未有这类证据 |
| VFC_VFSLOCALARGS | `vfs_syscalls.c:1171–1178`、`vfs_conf.c:179–190` | bindfs仅有VFC_VFS64BITREADY，且此调用来自userspace；不适用 |
| 根卷改为可写/更新 | `vfs_syscalls.c:927–953,1249–1261` | 本次是Extensions目录新挂载且MNT_RDONLY；不适用 |
| MAC mount钩子 | `kern_minimac.c:113–116,351–354` | 当前AMFI/Sandbox stand-in未注册mount拒绝钩子，无需额外sandbox entitlement |

专用key的读取链路已经核对：

1. `src/xnu-8796/iokit/bsddev/IOKitBSDInit.cpp:1508–1534` 将当前进程交给
   `amfi->OSEntitlements.queryEntitlementBooleanWithProc()`。
2. `src/hakios-8796/xnu/files/libkern/amfi/miniamfi.c:94–96,250` 转入
   `miniamfi_entitlement_boolean()`。
3. 同目录 `miniamfi_entitlements.cpp:33–78` 调用 `cs_entitlements_blob_get()`，解析
   签名XML；仅当该key对应 `kOSBooleanTrue` 时返回KERN_SUCCESS。
4. `src/xnu-8796/bsd/kern/kern_cs.c:1723–1729` 要求CS_SIGNED；本内核
   `kern_minimac.c:45–62` 的签名钩子为已有签名设置此位。`ubc_subr.c:845–891` 读取
   已验证签名中的CSSLOT_ENTITLEMENTS。既有system-service-probe和GPU probe同样使用
   ad-hoc codesign、entitlements XML、strict verify及签名内容回读。

据此，最小修复只改 `tools/build_nabu_system_metal_probe.py`：mount helper签入
`{'com.apple.private.bindfs-allow': True}`，保留原4KiB签名页和identifier；执行
`codesign --verify --strict`，再以 `codesign --display --xml --entitlements -` 回读，
要求只有这一项且类型为boolean true，并把实际回读值写进 `mount_helper.entitlements`。
共用Vulkan `sign()` 固定核对GPU probe权限，故helper在本脚本单独签名；未改共用构建器、
内核、init、mount helper C代码、probe、bundle或已通过前端。

本地Python语法和签名runner测试通过：仅单一boolean true被接受，缺key、false、整数1和
额外key均拒绝。记录：`log/host/system-metal-v168/mount-entitlement-check/report.json`。
这是构建脚本的host验证；新的实际codesign回读需下一次macOS CI完成，修复后的挂载、ready
文件和标准工厂实际执行仍需下一轮实机验证。现有日志没有内核mount分支trace，不能把
明确缺少的必要权限条件表述为设备上已观测到的唯一返回点。
