# 20F66：先独立 Vulkan 计算/三角形，再接 Metal

2026-11-09。只做源码与本地文件状态核对；未构建用户态 GPU 库、未操作设备、未分析原版二进制。
第162/163轮硬件结果由主任务归档。本记录不把参考17.7设备报告视为本机16.5结果。

## 建议的最短下一步

先发布 `NativeAdrenoGpuPublished : IOService`，让独立、签名的测试程序通过
NativeAdrenoABI v1 调用 BO 分配、CPU映射、GPU映射、提交和fence；再加载独立
`libvulkan_freedreno.dylib` 运行现有 fill/compute/triangle。此阶段无需
IOAcceleratorES、AGXAccelerator、MetalPluginName、IOSurface呈现或桌面接管。

`NativeAdrenoControl` 仅接受管理员的 `Start` 属性，不提供 BO/提交客户端；
不要把它误用为 Vulkan 服务。

具体源码证据：

- `src/nabu/gpu/upstream/Adreno6xx/NativeAdrenoPublish.cpp:515`：
  `NativeAdrenoGpuPublished` 的基类是 `IOService`；`AGXDeviceUserClient` 的基类
  是普通 `IOUserClient`。二者本身不依赖原版 IOAcceleratorES。
- 同文件 `native_adreno_publish()`（1830附近）先注册普通服务，随后才根据
  `native-adreno-metal` 调用 `native_adreno_accelerator_publish()`。需要编译期
  隔离该调用及其声明；仅设 bootarg=0 不会消除链接依赖。
- `src/unixnu-turnip/patches/mesa/turnip-darwin-kmd.patch:625` 已支持
  `TU_DARWIN_SERVICE=NativeAdrenoGpuPublished` 的直接 selector 模式。
- **连接类型的注释已过时**：KMD会给直接服务默认type=0，但当前
  `native_adreno_new_user_client()`（1726附近）只接受 `0x4147`。
  此阶段显式设置 `TU_DARWIN_OPEN_TYPE=0x4147`，不要依赖type=0的旧注释。

## 内核最小接入范围

复用现有已验收的硬件、VM、Ring、CPU页粒度与电源适配，在当前30个对象外接入
参考构建 `METAL_CPP` 除 `NativeAdrenoAccelerator.cpp` 的六个对象：

1. `NativeAdrenoSubmit.cpp`
2. `NativeAdrenoTimer.cpp`
3. `NativeAdrenoUserClient.cpp`
4. `NativeAdrenoClient.cpp`
5. `NativeAdrenoPublish.cpp`
6. `NativeAdrenoScheduler.cpp`

严格直接路径未发现对 `NativeAdrenoClient` 类的调用，它是191行的独立客户端工具；
保留参考清单较容易复现，随后可按未定义符号实测缩减。其余五项分别是提交/同步、
时间接口、BO/队列核心、IOKit包装和调度器。不能只加入发布对象而漏掉Submit、Timer、Scheduler。

需要的适配点：

- 新的普通服务发布模式应与现有 `NABU_GPU_METAL` 分开。复用其 `submit_.attach()`、
  `NativeAdrenoTimer`、真实DeviceInfo和窗口参数初始化，保持GPU工作线程及故障/完成轮询；
  有用户态工作期间不能在一秒后自动 `finishDiagnostic()`。
- `NativeAdrenoPublish.cpp` 的类初始化可用普通kmod构造流程，或保留其
  `native_adreno_initialize_classes()` 的显式初始化；二者只能执行一次。
  不需要 `NativeAdrenoAccelerator.cpp` 的延迟IOAccelerator父类初始化。
- 继续使用本项目 `NabuGpuKernelCompat.h`、SMMU独立命名和 `-fno-common`。
  编译输出要核对实际缺失的8796私有声明/符号（特别是 `gIOUCFilterCallbacks`、
  `mac_iokit_check_open`、CPU映射方法）；本次没有进行编译，不能声称已兼容。
- 发布代码引用 `gpu/a640/NabuGpuProblemLog.h`，其 `nabu_capture_append()` 属于
  参考ESP日志接口。本项目应接到当前日志输出/捕获接口，不能引入第二个日志槽写入者。
- `NativeAdrenoIntegration` 的显示回调可以为空；不要接入参考scanout或QuartzCore地址。
- 直接服务上的真正IOServiceOpen/selector准入仍需要实测。现有签名使用
  `com.apple.security.iokit-user-client-class = [AGXDeviceUserClient]` 和 no-container；
  不要通过伪造MetalPluginName/AGX父类身份来绕过这项验证。

源文件尺寸：六文件合计约268.6KB源码、6083行；这不是对象代码尺寸。
未运行编译，因此没有可引用的机器码或DATA大小。主任务已找到原预链接布局的内部空闲段，
可以先编译并按真实Mach-O节尺寸安排空间，无需为了估算而删掉调度或映射功能。

## 只构建 Turnip 的入口及依赖

真正只产生Vulkan库的入口是：

```text
src/unixnu-turnip/scripts/build-turnip-darwin.py --target ios --abi-directory <当前NativeAdrenoABI.h目录>
```

它要求**已装配的构建树**，根目录下有 `.cache/mesa-work`、`.cache/mesa-venv`、
`.cache/mesa-tools/bin` 和记录的补丁序列。输出：
`build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib`。
第52行硬编码 `arm64-apple-ios17.0`，必须在本项目派生构建脚本中改为16.5；
构建后验证Mach-O最低系统版本和实际依赖。

已有完整装配编排可借鉴：

```text
python3 src/nabu/source-ci/nabu_turnip_ci.py --device src/nabu --work <新构建目录> --output <新产物目录>
```

**上述命令原样产物仍是iOS17，不能直接部署。** `nabu_turnip_ci.py` 会获取Mesa、
应用补丁、构建Turnip，并自动构建下面的独立probe；不加 `--plugin` 就不会编译Metal前端。
建议为20F66编写项目内包装：复用这个顺序，改编译目标和probe调用，保留所有输入版本。

已确认的输入版本和依赖：

- UniXNU构建工具 `cd2dd1bd0d79a441424f2bd014144bd719ba56f7`。
- Mesa `85fda3b36405bcaea8bffc64aa4f2651dc90770d`，19个有顺序的补丁，加
  `src/nabu/patches/mesa-turnip-a640-trace-guard.patch`。
- 运行时ABI来自当前 `src/nabu/gpu/upstream/Adreno6xx/NativeAdrenoABI.h`；
  内核、KMD和probe必须消费同一份头文件。
- Python包：meson1.6.1、mako1.3.8、pyyaml6.0.2、packaging24.2；ninja、
  glslangValidator；Bison3.8.2（编排脚本从锁定包构建，macOS系统Bison2.3不够）。
- macOS/Xcode iPhoneOS SDK，独立脚本禁止在非macOS GitHub Actions上构建。
- **仅Turnip+Vulkan probe不需要Rust、metal2vulkan、LLVM-as或Apple AIR。**
  Rust1.98.0、LLVM21+、Cargo依赖属于后续Metal桥；本地metal2vulkan仓库的
  rust-toolchain.toml声明1.98.1，届时需要核对旧桥脚本显式`+1.98.0`与MSRV。

本地状态：源码AdrenoMetal、metal2vulkan、UniXNU工具及Mesa补丁已在；完整Mesa
checkout、mesa-venv、私有bison安装、Turnip dylib、Rust桥静态库均未生成。
`D:/VulkanSDK/1.4.350.0/Bin` 有glslangValidator与spirv-val，可用于廉价shader语法验证。
根 `patches/mesa` 不存在，`configs/gpu-reference.json` 里的补丁路径需相对
`src/unixnu-turnip` 或派生构建树解析，不能直接相对根目录执行。

## 独立签名测试程序

参考入口：`src/nabu/scripts/build-nabu-gpu-userprobe.py`，参数
`--turnip-library <dylib> --turnip-headers <mesa/include> --adrenometal <src/AdrenoMetal>`。
它内嵌GLSL生成的SPIR-V，构建ARM64 executable，并复制/签名同目录的Turnip库。
AdrenoMetal源码锁定 `baad47ca22b181bf0ef0d08412d3ed1f96945e16`。

需要项目内派生修改：

- 目标改 `arm64-apple-ios16.5`；`validate_macho()`最低系统值由 `0x110000`
  改为 `0x100500`。签名、动态库目标及依赖也验证16.5。
- `userprobe/nabu_gpu_userprobe.cpp:371` 改为匹配 `NativeAdrenoGpuPublished`，
  原先要求MetalPluginName和MetalPluginClassName的身份断言换成真实芯片/ABI/服务标识。
- `nabu_turnip_stage::run()`（336附近）不再强制 `IOAcceleratorES`，而设置上述
  直接服务名与open type。`NativeTurnipSmoke.h` 的setenv overwrite=0，能保留调用者选择。
- 使用本项目独立launchd job或现有受控probe调度；不安装参考包的bluetoothd、
  iomfb_fdr_loader替代plist，不接任系统桌面。

现有 `NativeTurnipSmoke.h` 已有实际验证：1024个fill字、1024个compute shader结果、
32×32离屏三角形，顶点+片元shader、copy-to-buffer再CPU读回，三角形像素应为480..544，
未知颜色像素必须为0。每次提交有5秒fence等待；外围有15/45/90秒进展和150秒进程警戒。
应保留这三项独立结果，不能只看最终进程返回（原probe末尾返回值主要覆盖owned-BO测试）。

## 后续Metal范围与工作量

最短Vulkan路径是“一次受控内核客户端接入 + 一次macOS依赖/库/可执行文件构建 +
一轮实机分配/提交/计算/三角形验证”。本次没有新构建耗时数据，不给未经测量的完成ETA。
代码修改集中在发布条件、16.5目标和独立probe身份/服务选择；运行时IOKit映射、调度、
cache同步是否存在16KiB差异，只能由实际编译/实机结果进一步确认。

完整Metal还需原版20F66接口验证、Rust桥和Frontend、IOSurface与长期调度。
`build-adreno-metal-plugin.py` 原始默认开启A740 replay、A740 QuartzCore地址及scanout；
均不适合直接套用。参考nabu的包装脚本已禁用前两项并且明确不部署替代系统daemon，
但它仍以17.7和自己的scanout/易失Data布局为目标；需要按本项目独立接入。

## 已实现的16.5独立Vulkan构建

项目内新增 `tools/build_nabu_gpu_vulkan_probe.py`、
`userland/nabu/src/gpu_vulkan_probe.cpp` 和 `.github/workflows/gpu-vulkan.yml`。
仅复制所需工具和20个Mesa补丁到新的工作目录，复用锁定nabu生产脚本的Bison/Mesa准备函数。
Turnip编译脚本只在副本中把目标改为 `arm64-apple-ios16.5`，原始源码checkout不变。

CI构建命令：

```text
python3 tools/fetch_sources.py --only nabu UniXNU-turnip-reference AdrenoMetal
brew install ninja glslang
python3 tools/build_nabu_gpu_vulkan_probe.py --work build/gpu-vulkan --output artifacts/nabu-gpu-vulkan
```

工作流跟随 `nabu16-bootstrap` 上这三个文件的push，或由主任务显式执行
`gh workflow run gpu-vulkan.yml --ref nabu16-bootstrap`。
本子任务未提交、push或派发CI。

产物 `nabu-gpu-vulkan-probe` 和 `libvulkan_freedreno.dylib` 均为4KiB页ad-hoc签名，
各自CDHash、Mach-O最低系统版本验证和动态依赖写入 `build-report.json`；
另保留未strip的库供定位调用栈。CI构建成功仍标记 `gpu_exercised=false`、
`runtime_qualified=false`。

设备执行 `./nabu-gpu-vulkan-probe --run-vulkan`，动态库须在可执行文件同目录。
先直接打开 `NativeAdrenoGpuPublished` / `0x4147` 查询ABI版本与A640芯片，关闭预检连接后
交给Turnip创建自己的连接。实际fill、compute和triangle全部通过才退出0；进展及NV摘要
通过已有0x4147xxxx标记发送到内核，并输出详细文本及JSON。外围警戒为150秒。
构建不产生Metal插件、scanout组件、QuartzCore补丁或替代系统daemon。

2026-11-09主机验证：Python语法与帮助输出通过；staging包含19+1补丁且复制后的脚本
解析通过、目标为16.5；三个GLSL分别经glslangValidator编译和spirv-val验证；工作流YAML
解析通过。主机验证材料位于忽略目录 `build/host-gpu-vulkan-check-20261109`。
macOS链接/签名和真实GPU结果仍待主任务CI与实机验证。
