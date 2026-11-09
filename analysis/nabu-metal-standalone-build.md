# iOS 16.5 独立 Metal 前端与读回测试

2026-11-09。第166轮已经验证同一 Turnip 库的真实 Vulkan fill、compute 和 triangle。
本文件记录下一步 Metal 用户态构建；它尚未经过 macOS CI 编译或设备执行。

## 接入边界

可直接调用固定 AdrenoMetal 的 `native_bridge_metal_open()`。原
`NativeAdrenoMetalDevice` 是系统 discovery 的入口壳，最终也调用这个函数并返回
`NativeBridgeMetalDevice`。该对象持有真实 metal2vulkan runtime，经原样复用的 Turnip
连接 `NativeAdrenoGpuPublished`，open type 为 `0x4147`。独立测试不要求发布
`AGXAccelerator`，不调用 `MTLCreateSystemDefaultDevice()`，不加载原版 IOGPUFamily。

前端动态继承进程中 Metal.framework 的 `_MTLDevice`，添加零个实例变量。
原源码的 iPhone 大小检查硬编码536，对应17.7；20F66原版静态元数据为528：

- Metal UUID：`88922408-fd68-3396-8465-3775ce66ff60`。
- `_MTLDevice`：instanceStart=8、instanceSize=528；class VA `0x1e1b2dc98`，
  class_ro VA `0x1d56991a8`。
- 原版读取证据：`log/host/metal-20f66/classes.json` 与 `read-classes.py`。

派生前端改为528；探针在打开GPU前打印并检查实际 `class_getInstanceSize()`。
这仅核验一个必要的布局条件，不能替代公开方法、继承行为和真实GPU执行测试。
本实现不使用 OfflineFrontend 的 SharedEventListener 布局，也不测试共享事件。

## 构建范围

`tools/build_nabu_gpu_metal_probe.py` 只编译 `NativeBridgeMetalFrontend.mm` 与 Rust bridge，
产生 `libnabu-metal-frontend.dylib`。不编译 `NativeAdrenoMetalPlugin.mm`，不产生插件发现
标记、系统任务替代文件或显示呈现组件。

保留 `nabu_metal_plugin_ci.py` 包装中适用的三个补丁：optional shader cache、
QuartzCore错误记录结构、problem observer。跳过scanout与CoreImage stitching补丁。
Rust runtime采用AdrenoMetal规定的25项补丁顺序。

编译时 `NATIVE_ADRENO_SCANOUT_COPY`、`NATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE`、
`NATIVE_ADRENO_A740_REPLAY` 均为0。另在派生源码中整体删除无条件的
`quartzCoreCallers()` 私有地址诊断体；仅设宏不能移除这段21H461偏移。
不设置 `CA_FORCE_GENERIC_SHADERS` 等generic shader选项。

依赖仍采用 `configs/sources.lock.json` 中的固定版本。metal2vulkan commit 为
`624bab3918de5b978e1101517abca2b4fa426565`，其工具链固定1.98.1、MSRV为1.98；
派生桥脚本将旧的显式 `+1.98.0` 改为1.98.1，并把部署版本改为16.5。
LLVM至少21，用于桥的已有AIR fixture。Cargo先生成依赖锁文件，之后以 `--locked`
编译，并将实际 Cargo.lock 随产物保留。

Metal测试着色器由项目自有 `gpu_metal_smoke.metal` 经Xcode编成真正的
`nabu-metal-smoke.metallib`，探针通过 `newLibraryWithFile:error:` 加载。
测试不调用桥的裸AIR fixture入口，也不编译原版QuartzCore着色器。

Turnip使用CI `42576001993` / artifact `nabu-gpu-vulkan-1` 的已签名库；
CDHash `2efb6446d343ec4dd3e8ee699d912852ad9a41d3`，原样复制，不重新签名。

## 验收内容与命令

`nabu-gpu-metal-probe --run-metal` 先查询真实ABI版本和A640芯片，然后执行：

1. MTLBlit fill：4096字节，部分区域为0x5a、其余保留0xa5，全部验证。
2. MTL compute：1024个 `i*3+0x1000` 结果，前后共128个保护字保持不变。
3. MTL render：32×32私有纹理，左上16×16红色、其余蓝色；通过MTLBlit复制回
   CPU缓冲区，核对1024个像素、256个红色像素、0个其他颜色及4096字节行间padding。

每个命令缓冲都必须到达Completed；进程只在三项全部通过且没有缺失selector时退出0。
有8MiB测试线程栈和180秒进程警戒，保留阶段、错误、指标、JSON与内核NM摘要。
着色器缓存和管线日志放在 `/var/mobile/Media/NabuMetalCache`。
完成纹理读回后，将实际缓冲区每行前128字节顺序写入
`/var/mobile/Media/nabu-metal-readback.rgba`（共4096字节），另存同名 `.json`
记录32×32 RGBA8Unorm与验证计数。导出直接使用GPU读回数据，不使用预期图案生成。

macOS CI入口：

```text
python3 tools/fetch_sources.py --only nabu UniXNU-turnip-reference AdrenoMetal metal2vulkan
gh run download 42576001993 --name nabu-gpu-vulkan-1 --dir inputs/turnip-vulkan
brew install llvm
rustup toolchain install 1.98.1 --profile minimal --target aarch64-apple-ios
python3 tools/build_nabu_gpu_metal_probe.py --work build/gpu-metal --output artifacts/nabu-gpu-metal --turnip-input inputs/turnip-vulkan/nabu-gpu-vulkan --mtl-device-bytes 528 --llvm-as /opt/homebrew/opt/llvm/bin/llvm-as
```

工作流 `.github/workflows/gpu-metal.yml` 随其四个实现文件的push触发；手动命令为
`gh workflow run gpu-metal.yml --ref nabu16-bootstrap`。本子任务未提交、push或派发CI。

本地已通过Python语法、实际派生源码装配和三个nabu补丁应用、528检查改写、旧QC偏移
移除检查、25项Rust补丁应用和反向还原校验及工作流YAML解析。
Windows的Git默认CRLF转换已在staging clone中显式关闭；校验记录位于
`log/host/metal-20f66/metal-build-host-check.json`。
2026-11-09后续：源码2e14b2c、CI42590211952全部编译和签名成功，完整内核CI42590211825
也通过。第167轮独立Metal各项实测通过，运行时尺寸528匹配；实际RGBA已回收。
详见[第167轮](nabu-gpu-v167.md)。六个设备能力查询暂无bridge答案，未被本次测试使用，
后续工厂和应用兼容仍需逐项验证。
