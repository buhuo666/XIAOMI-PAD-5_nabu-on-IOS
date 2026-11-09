# 第166轮：A640真实计算与3D绘制通过

2026-11-09。用户确认桌面、触摸正常并手动恢复Android；日志已备份清空。

| 验收 | 实机结果 |
| --- | --- |
| IOKit直接连接 | NativeAdrenoGpuPublished，type0x4147，ABI1，chip0x06040001 |
| GPU缓冲区填充 | 1024/1024字匹配 |
| 计算着色器 | 1024/1024计算结果匹配 |
| 顶点/片元着色器与三角形读回 | 32×32目标中的512像素为三角形颜色，其他未知颜色0 |
| Vulkan进程 | stage0、vk0、exit0，stderr空 |
| 桌面、触摸 | 用户确认正常 |
| 持久化及日志 | APFS135→136，fullfsync成功；3,968,265字节与完整64MiB槽备份后清空 |

这已证明GPU真实执行计算、顶点与片元着色器。Metal API、IOSurface呈现和系统/应用
硬件加速尚未验收，不由以上结果推出。

## 精确输入和证据

- GPU/策略源码`3bbeff91991864dd85b23b0219554f42b53c5331`，链接器`4598e0c`。
- 内核`artifacts/nabu-gpu-trace-v165/kernel.native-apfs.macho`；bootstrap
  `artifacts/nabu-bootstrap-gpu-v165/bootstrap.apfs`，与第165轮完全相同。
- 底层8796内核和非GPU服务沿用CI42570303718；当前源完整CI42583890919第二次通过。
- Vulkan程序与Turnip来自`0ae4acfe2d69895e25e010ab4cfd869357795ae6`、CI42576001993。
- 实际stdout/stderr/JSON：`log/host/gpu-v166/vulkan-runtime`。因为镜像完全复用，
  设备job和文件名仍含v165；主机证据归属本次166，165此前没有生成这些输出。
- 内核日志`log/device/nabu-boot-20261109-166/runtime-log/runtime.log`：ADSP在64.104578秒
  完成INIT，GPU在115.831187秒ready；launchd记录测试进程退出0。
- 汇总`log/host/gpu-v166/result-summary.json`，Android完整重启记录
  `log/host/gpu-v166/android-reset.json`。

第165轮独立的ADSP续调停滞仍需改善；一次同镜像成功复测不能证明跨重启稳定性。
下一步构建面向16.5的独立Metal前端，实际验证MTL计算和离屏绘图，再接入系统链路。
