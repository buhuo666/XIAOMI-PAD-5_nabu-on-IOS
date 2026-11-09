# 第167轮：独立Metal计算与绘图通过

2026-11-09。使用已通过Vulkan的A640内核和Turnip库，独立构造真实Metal前端，
执行自有MSL编译的metallib；用户确认桌面触摸正常并恢复Android。

| 验收 | 实机结果 |
| --- | --- |
| 原版Metal基类 | class_getInstanceSize(_MTLDevice)=528 |
| 前端和GPU | NativeBridgeMetalDevice → Turnip Adreno 640 → NativeAdrenoGpuPublished |
| MTLBlit填充及未写范围 | 4096/4096字节 |
| MTLCompute结果 | 1024/1024字，128/128保护字 |
| MTLRender及MTLBlit读回 | 1024/1024像素，红色256，未知颜色0，行间保护4096/4096字节 |
| 命令缓冲及进程 | 3个Completed，exit0，missing_selector空 |
| 桌面和触摸 | 用户确认正常 |
| 持久化及日志 | APFS136→137、fullfsync成功；4,356,279字节及完整64MiB槽备份清空 |

实际32×32 RGBA8像素从完成的GPU读回缓冲区逐行导出，未由预期图案生成：
`artifacts/nabu-metal-render-v167/nabu-metal-readback.rgba`、`readback-32x32.png`、
`readback-preview.png`。左上16×16红色，其余蓝色；已目视核对放大PNG。

## 输入与证据

- 用户态源码：`2e14b2c27befa439beef47bf28cda755a5974555`，Metal CI42590211952。
  前端dylib18,109,696字节，probe112,400字节，metallib10,470字节，最低系统16.5。
- 内核继续`artifacts/nabu-gpu-trace-v165/kernel.native-apfs.macho`（GPU源码3bbeff9）。
  Turnip仍为CI42576001993的已签名库，未重编译或重签。
- 完整内核CI42590211825通过。本轮完整Android重启后临时启动，使用原64GiB区域。
- `log/host/gpu-v167/metal-runtime/result.json`及stdout/stderr记录全部实际指标；
  `log/device/nabu-boot-20261109-167/runtime-log/runtime.log`记录GPU于116.269795秒ready
  和launchd进程退出0。汇总见`log/host/gpu-v167/result-summary.json`。

## 边界

本轮通过`native_bridge_metal_open()`直接创建设备，尚未走
`MTLCreateSystemDefaultDevice()`或系统bundle发现。未接入IOSurface、系统呈现或桌面。
前端初始化记录六个暂无答案的能力查询：gpuCoreCount、maxVertexAmplificationCount、
maxComputeThreadgroupMemory、isLargeMRTSupported、supportsComputeCompressedTextureWrite、
supportsConditionalLoadStore。本次实际调用没有缺失selector，但这不证明完整应用兼容。

下一步按[系统接入顺序](nabu-system-metal-next-steps-v166.md)，先薄accelerator和最小
bundle，让GPU ready后启动的新进程经标准Metal工厂完成同一组实际测试。
