# GPU183：默认 IOSurface 直接页面共享

2026-11-10。按用户最新要求，目标是尽量保留原版Apple用户态路径，IOSurface直接
共享物理页，当前60Hz稳定流畅、以后120Hz。GPU182复制优化候选停止上机；其CPU测试
和Mach测试通过，但iOS编译因方向调整取消，不作为此轮输入。

## 实际阻塞与最小修复

必须按构建source_map核对：v168/181实际使用`gpu/a640/NativeAdrenoVm.cpp`，不是
upstream同名文件。A640版本已允许0x06040001，其导入路径由IOMemoryDescriptor固定
原任务页面并枚举物理段。实际关闭点是NativeAdrenoGpuContext.cpp的编译条件：
只在NABU_GPU_METAL调用enableCachedCoherentImports，而系统构建使用USERLAND+
SYSTEM_METAL，故默认WB表面在BoMap被拒，runtime建立副本和影子纹理。

本轮仅把现有共享导入初始化覆盖到SYSTEM_METAL，并打印其真实返回值及启用状态。
不更改芯片名单，不更改owned BO的Normal-NC策略，不改变CPU页缓存属性，不启用
尚未接入的GopFramebuffer扫描输出。保留GPU181八连接及GPU180用户态。

Linux v6.12 `a6xx_catalog.c`将0x06040001列为HAS_CACHED_COHERENT；小米
nabu-r-oss A640有ADRENO_IOCOHERENT。原厂IOCOHERENT导入映成IOMMU_CACHE，叶项
Normal-WB/OuterShareable；当前ArmSmmu4K的writeback1/shareability2对应同样属性。
具体下载来源、行号和局限记录在`log/host/gpu-zero-copy/reference/`及同目录研究报告。
这支持受控资格测试，但不能代替本机脏CPU缓存与GPU写回的真实读写验证。

## 验收边界

新增`check_nabu_metal_present_frames.py --require-zero-copy`要求：
标准工厂及64帧实际像素、保护区、释放原检查继续通过；同时必须有真实pointer导入、
in-place纹理，copied buffers、copy-in、merge-back及shadow texture增量全部为0。
旧GPU181虽像素通过，但其61个副本会被新验收明确拒绝。

原版CA/IOSurface用户态和内核Mini实现的跨进程descriptor共享无需另建App入口。
此轮仅验证GPU和IOSurface间的直接存储；最后一跳MiniIOMobileFramebuffer仍CPU绘制
到固定GOP，vblank仍是软件计时。DPU同页扫描、GPU完成/扫描读完fence与真实硬件节拍
仍需接入，不能把此轮通过写成全系统零拷贝或60/120Hz验收完成。

GPU181实测显示最后一跳绘制2.261–5.413ms/帧、等待0–4µs，但到达驱动的swap本身
稀疏；低帧率原因优先在合成和提交上游核实。见`log/host/gpu-zero-copy/native-path-review.md`。

本地共享页上下文已编译，沿181链接命令只替换一个对象，内核分支、返回跳转和实际
引导器布局通过。候选`artifacts/nabu-gpu-ready-v183/kernel.native-apfs.macho`，
真机状态见`log/host/gpu-v183/continuation.json`。
