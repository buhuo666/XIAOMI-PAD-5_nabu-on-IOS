# GPU下一阶段可行性与首个目标

2026-11-09，Asia/Shanghai。第161轮桌面和Spotlight已验收，用户恢复Android后选择GPU。
本记录是源码核对及实施路线，不代表已构建或部署GPU候选。

## 当前证据

- 第161轮runtime.log记录CoreAnimation无法初始化Metal或OpenGLES；显示仍经
  MiniIOMobileFramebuffer工作，当前没有GPU硬件加速验收。
- src/nabu/gpu/a640/NativeAdrenoService.cpp有真实的供电、SMMU、GMU/HFI、GX、
  SQE/ZAP和命令处理流程；服务发布前要求GPU写出0x6401cafe及完成栅栏。
- src/nabu/gpu/nabu/NabuGpuResources.cpp提供SM8150/A640板级地址、映射及固件接口。
  本机所需GPU固件此前已保留，见docs/SOURCE-BASELINE.md。
- src/AdrenoMetal存在Metal/Turnip桥接代码，但src/nabu/board.toml的参考系统是
  iPadOS17.7/21H16。当前系统为16.5/20F66，configs/gpu-reference.json明确记为
  尚未验证ABI；不能直接把参考插件及私有接口当成当前系统可用。
- src/NabuAdreno和hakios内置GPU实现另有A642L平台输入，不能混用其地址、固件和芯片参数。
- “别人的GPU资料”中的0100加速器补丁为返回零输出的占位实现，GMU加载器也有
  映射地址截断及跳过外部内存固件块的问题，不作为完整可用驱动导入。

## 实施顺序

1. 以现有A640实现核对20F66内核接口和板级输入，构建独立诊断入口。首个硬件验收是
   GMU真实响应、GPU写入测试内存、栅栏完成及资源停止；保留当前已通过的桌面路径。
2. 完成离屏清屏/三角形渲染并读回实际像素，随后验证连续提交、内存映射和完成同步。
3. 核对20F66用户态设备接口、Metal插件、着色器与IOSurface共享，再接入实际应用和桌面。

可行性判断：已有真实A640执行链和用户态适配参考，有明确实施基础；完整Metal兼容、
持续桌面稳定性和性能尚无本机证据，不能承诺所有应用或游戏。Safari视频黑屏仍分别
核对解码、像素格式、IOSurface与最终呈现，不将GPU成功直接等同视频问题全部解决。
