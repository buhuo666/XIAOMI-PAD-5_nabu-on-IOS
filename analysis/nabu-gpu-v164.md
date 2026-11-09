# 第164轮：独立 Vulkan 用户态接入

2026-11-09。第163轮的512像素离屏2D结果、桌面触摸反馈和日志已归档，APFS计数133。
本轮目标是通过真实IOKit连接执行Vulkan填充、计算着色器和离屏三角形；Metal和系统呈现
仍为后续项目。当前文档记录准备结果，尚未表示实机通过。

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

待临时启动。应分别记录IOKit打开、ABI/芯片查询、1024字填充、1024字计算结果、
32×32三角形480..544个目标像素且其他颜色0，以及桌面与触摸反馈。进程退出成功、
服务发布成功或已有2D结果均不能替代以上实测。
