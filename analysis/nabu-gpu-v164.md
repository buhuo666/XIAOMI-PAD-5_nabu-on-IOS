# 第164轮：独立 Vulkan 用户态接入

2026-11-09。第163轮的512像素离屏2D结果、桌面触摸反馈和日志已归档，APFS计数133。
本轮目标是通过真实IOKit连接执行Vulkan填充、计算着色器和离屏三角形；Metal和系统呈现
仍为后续项目。IOKit连接已通过，Vulkan在首个global BO初始化失败，着色器尚未开始。

## 输入和实现

- 延续CI42570303718的8796内核及已验收无线、ADSP、+16dB扬声器与桌面输入基线。
- `tools/build_nabu_gpu.py --userland`以当前8796头文件构建36个GPU对象，新增BO/客户端、
  提交、计时和调度对象。GPU完成初始CP证明后注册`NativeAdrenoGpuPublished : IOService`，
  保持工作线程与故障/完成轮询。没有发布Metal accelerator或接入scanout。
- `NativeAdrenoPublish.cpp`的类构造函数改为一次显式晚初始化；Mach-O自动构造节改名且
  类型设为普通数据，构造函数符号公开给现有初始化入口，避免重复元类注册。
- 预链接DATA在v162基础上扩展1MiB，原组件VA保持不变。链接器通过显式
  `--reuse-executable-gaps`选项复用原执行段中无组件占用且全零的区间；默认布局保持原行为。
- 用户态由`0ae4acfe2d69895e25e010ab4cfd869357795ae6`、Vulkan CI42576001993产生，
  目标`arm64-apple-ios16.5`。使用相同NativeAdrenoABI与直接连接类型`0x4147`。

## 主机证据

- 本地36对象编译通过，61对象完整内核链接通过，无未解决导入。
- 实际保存候选重建字节一致：8,951条直接分支和2,666条远分支全部解码正确；521个veneer。
- 48个原组件段内容逐字节保持。新增执行段819,200字节，原零区间约7.49MiB。
- DarwinBoot真实解析器及最终布局检查在ASan/UBSan下通过；候选span616,857,600字节，
  含启动器保留区共625,295,360字节。
- Vulkan云端构建与签名成功。独立launchd任务、APFS读回和设备结果随后记录。

证据目录：`log/host/gpu-v164`、`log/host/gpu-gap-link-check`；候选内核
`artifacts/nabu-gpu-trace-v164/kernel.native-apfs.macho`。

## 实机验收

- 临时启动成功，用户确认桌面与触摸正常并恢复Android。
- CP scratch `0x6401cafe`、fence1/1通过，GPU保持ready；普通IOService发布成功。
- 新job由IOKit事件触发，仅运行一次；签名、动态依赖、AFC日志回收均通过。
- 预检真实打开`0x4147`、查询ABI1、芯片`0x06040001`、GMEM1MiB并关闭成功。
- Vulkan返回stage5、`VK_ERROR_OUT_OF_DEVICE_MEMORY`；对应`tu_CreateDevice`的首个
  global BO初始化（tu_device.cc:3093），尚未进入其CPU映射或fill/compute/triangle。
  当前错误摘要不能独自区分用户态IOVA与内核BoAlloc/BoMap；下一轮补具体内核失败输出。
- 回收4,007,943字节运行日志及67,108,864字节完整槽；备份后清空并读回验证。
  APFS持久化133→134，fullfsync成功。源码4598e0c的完整CI42581440060也通过。

源码复查发现USERLAND条件未延伸到`NabuGpuMemoryPolicy.h`：用户BO仍落入WB池，
但A640 VM仅接受已经验证的Normal-NC；同时VM映射对象数仍为硬件自检用的16。
这两项配置需要修正后复测。该源码问题不等于本轮已经记录到某个确定的BoMap错误码。
