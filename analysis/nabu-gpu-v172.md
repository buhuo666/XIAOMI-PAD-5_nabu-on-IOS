# 第172轮：默认 IOSurface 的 iOS 复制读取

源码 `862987a2322c3d27b7a24068205dd900e4c087ae`。继续使用第168轮内核及其
SYSTEM_METAL/USERLAND 配置，cached imports 关闭。普通 IOSurface 原指针导入
失败后，修复后的用户态允许 iOS 调用既有 Mach reader 建立复制兼容资源。

## 修改与构建

- `0027-nabu-ios-copied-host-read.patch` 只修改两处平台条件及对应注释，使 iOS
  与 macOS 使用同一 `mach_vm_read_overwrite` 函数体。原25项补丁及统计补丁26保留。
- 默认 surface 探针在 GPU 导入前读取整份 allocation 到独立缓冲，验证 Mach
  返回值、字节数和内容。iOS SDK 不提供 mach_vm.h，使用已核对的显式 ABI 声明。
- 重编 Rust/Metal 前端与探针；Turnip、metallib、插件和挂载助手复用第170轮产物。
- 本地27项补丁正向/反向应用、旧构建模式和路径分类检查通过。
- 原生探针编译 CI42615860437、配套编译 CI42615860520 三项检查、新前端
  CI42615860281 全部通过。最初头文件失败 CI42615556910 已由当前源码修复。
- 新探针134,944字节、前端18,109,920字节，在下载时完成一次审查；
  `nabu-gpu-iosurface-copy-read-2` 产物包含27项补丁。新APFS bootstrap共68,034,560
  字节，apfsck和原生文件读回通过，bundle executable显式保持root:wheel0755。

## 实机状态

第172轮已部署并临时启动。用户确认桌面、触摸正常并手动恢复Android。遵循用户
要求，没有额外重启Android；部署后仅切换bootloader并临时fastboot boot。

| 项目 | 本轮实际结果 |
| --- | --- |
| 标准工厂/挂载 | NativeBridgeMetalDevice、实际AGX registry4294967771；只读union及原插件保留通过 |
| 默认IOSurface | ID10，32×32 BGRA8，row256，alloc16384；未用IOSurfaceAddress |
| Mach自检 | 返回0，请求/读回16384字节，内容完全相同 |
| GPU命令 | 32epoch、64command buffers Completed，实际图像已回收 |
| 双向像素 | GPU采样32768、CPU直接读取32768，错误均0 |
| 保护区 | surface行间262144、尾部524288、读回147456字节，错误均0 |
| 复制分类 | pointer0/bytes0，copied1、degraded1、refused0，shared_import=false、direct_image_alias=false |
| 真实复制流量 | copy-in65920、merge-back13568字节 |
| 纹理存储 | in-place0、shadow1；placement拒绝计数1，单独报告shadow路径 |
| 释放 | 完成后drain/trim，surface made/released1/1、held0；未测试完成前释放 |

实际像素文件和metadata的run_id均为1794227944790732，最终epoch31。
图像为红黄横条、中央洋红矩形，保存在`artifacts/nabu-iosurface-default-render-v172/`。
成功前还有内核`BoMap Unsupported`（runtime.log:32529），对应原始指针导入拒绝；
修复后的复制兼容随后完成，不能把该行当作整轮失败，也不能声称原Cached页已通过GPU一致性测试。

内核CP写入及fence1/1、state=ready见runtime.log:32462/32465。完整64MiB槽和
3,309,688字节连续日志前缀已备份，清空后读回验证通过。日志没有结束记录，
因此不把捕获前缀称为内核全生命周期完整日志。APFS记录:482为141→142、fullfsync=ok。

复制兼容通过仍不等同原IOSurface零复制、应用呈现或桌面加速。下一步核对本机
20F66 CAMetalLayer实际调用，并使用当前已合格前端实现小型可见应用；保留内核
cached imports关闭，不通过扩大设备能力声明替代运行结果。

主机记录：`log/host/gpu-v172/result-summary.json`；实际输出位于同目录
`iosurface-runtime/`，内核备份位于`log/device/nabu-boot-20261109-172/runtime-log/`。
