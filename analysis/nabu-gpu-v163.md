# 第163轮：A640离屏光栅测试

2026-11-09，Asia/Shanghai。承接第162轮真实CP写入和fence已通过的硬件基线。

测试使用现有GPU scratch分配中的独立区域（偏移1024、长2048字节），通过四次
CP_BLIT SOLID_COLOR绘制32×16 RGBA8红/绿/蓝/白四象限图案。CPU只写初始哨兵，
不写期望颜色；CCU清理及完成fence之后比较全部512个像素，并核对周围保护区。
原CP scratch值保持不变；读回的16行实际像素写入内核日志，用于生成可检查图像。

命令和寄存器依据已锁定Mesa `85fda3b36405bcaea8bffc64aa4f2651dc90770d` 的
`tu_clear_blit.cc`、`tu_cmd_buffer.cc`、`fd6_gmem_cache.h`、格式表和A6xx XML定义。
原件下载到 `build/nabu-gpu-render-reference/`，按下载时确认的源码及MIT许可证引用。
协议构造见 `patches/nabu-gpu/NabuA640Clear.h`。

83个dword、33个包的生产构造器通过ASan/UBSan及PM4解码检查：四矩形各覆盖一次，
目标和事件地址限定现有分配，提交流没有CP_MEM_WRITE。硬件渲染结果尚待本轮实测。
这是2D光栅路径；着色器、3D三角形、Metal、IOSurface与桌面加速分别保留未验证。

## 实机结果：通过

- 源码 `874bf02ba0a3e06651b6d9e7d1b4f447eff4bf15`，GPU本地ARM64编译，
  继续使用第162轮的已验证基础内核。完整CI `42573448474` 及查询工具CI
  `42573448158` 均通过。真实启动命令 `python log/host/gpu-v163/boot.py`。
- 原CP写入/fence 1/1再次通过；GPU绘图512/512像素全部匹配，保护区错误0，
  绘图fence 2/2，CP/GMU停止均成功。配对USB状态与内核记录一致。
- 用户确认“桌面触摸正常，已恢复 Android”。内核日志及64MiB原始槽已备份清空，
  持久化计数和完整回收记录见 `log/host/gpu-v163/result-summary.json`。
- 实际像素来自内核 `render_row` 记录，保存为
  `artifacts/nabu-gpu-render-v163/readback.rgba`、`readback-32x16.png` 和放大预览；
  `readback.json` 保留来源和维度。预览不是CPU合成的预期图案。

下一阶段：先核对现有NativeAdrenoABI用户客户端和最小Turnip库，运行Vulkan计算/
三角形，再处理20F66 Metal及系统接入。不要将2D离屏通过扩大为3D或应用加速通过。
