# 第173轮：息屏、SLPI诊断与CAMetalLayer统一测试

2026-11-09。用户安排由“30”等“息屏1”“传感器2”报告齐全后统一整合并测试。
本轮统一实測已完成。未额外重启Android，仅部署后切bootloader临时启动。
用户后续指定传感器全部交由“传感器3”，本对话继续GPU多帧呈现。

## 组合产物与来源

| 部分 | 来源与边界 |
| --- | --- |
| 核心内核 | bcd4def、CI42621253671通过，息屏display01实测通过的内核基底 |
| 服务/GPU对象 | 保留息屏保存链接命令中的61个对象，替换NabuDataKmod入口、增加NabuSlpi，共63个，GPU37个 |
| 组合内核 | `artifacts/nabu-display-sensors-integrated/kernel/kernel.native-apfs.macho` |
| 用户态 | 第172轮已实机通过的Metal前端；v173仅root插件挂载助手，无旧GPU探针自动任务 |
| SLPI固件 | 本机原始MDT和19个非空段，添加到Boot APFS `/fw`，sensor_pd未实现 |
| 启动包 | `artifacts/nabu-bootstrap-combined-sensors/bootstrap.apfs`，74,575,872字节 |
| 可见App | 19b5b72、CI42621723942成功，`org.nabu.MetalPresent`，IPA95,559字节 |

SLPI候选源码与交接时通过主机检查的快照相同。组合内核核对9,097个直接分支、
2,747个远分支，48个原组件区间保持。正式加载器树的parser/layout检查通过，
候选span616,857,600字节。SLPI写入范围0x97b00000..0x98f00000落在板级保留
PIL_REGION 0x8b700000..0x9ab00000内，不属于正常分配的RAM区。

启动包重新生成Boot APFS并通过apfsck；20个固件文件原生读回一致。NabuInit和App
沿用已检查的v173产物。既有输入复用下载时审查，不重新审核原GPU库或固件。

App的配套CI42621723810未完成内核/ath10k两个作业：GitHub报告macOS hosted runner
容量不足，未取得执行器后取消；无线主机检查通过。它没有给出源码编译错误，仍不能
将该任务写成全部通过。后续组合源码e595e0e3df695ab93bfdf0fdcc3166c0b639d3c7的
完整CI42627788010已完成，三个作业全部成功；本轮实际部署的是上述本地组合产物。

## 本轮操作与验收

采用独立`integrated-unixnu.toml`，启用`nabu-slpi=1`、日志slot1。旧slot14清单绑定
v168，保留其记录，不复用到组合内核；新清单绑定本轮最终内核。此前APFS计数143。

1. 检查桌面和USB就绪，回收SLPI PAS、SMP2P、GLINK及动态SSC服务发现结果。
2. 安装并从桌面打开“GPU呈现测试”；先验证真实GPU完成、drawable与IOSurface
   像素，再请求呈现。用户确认图案、清除图案及返回桌面；回收Documents中的结果和像素。
3. 复测背光完全关闭、唤醒与触摸，分别记录，不把GPU通过代替息屏回归验收。
4. 手动恢复Android后，备份完整日志槽和可恢复的日志前缀，再清槽。

传感器当前仅为底层诊断，不发布原生传感器服务。真实iPadOS读数、坐标/时间转换、
自动旋转和自动亮度未完成。安全世界SMC若不返回，APPS线程超时无法取消它，
应保留enter/return边界日志；不得将有限轮询等同所有硬件调用都保证返回。

## 第173轮实际结果

用户确认：“图案显示、清除和息屏唤醒均正常”，之后手动恢复Android并连接USB。
App结果见`log/host/gpu-v173/app-verification.json`，原始Documents见`app-runtime/`。

- run_id 1794232074136014，标准工厂返回NativeBridgeMetalDevice，registry4294967771。
- CAMetalDrawable为32×32 BGRA，surface13、row256、allocation16384。
  GPU读回和直接IOSurface读回各1024像素全部正确，读回保护区0错；1个命令Completed。
- 实际4096字节BGRA、同run_id元数据和PNG已回收到`artifacts/nabu-metal-present-v173/`。
- 普通IOSurface使用复制兼容：pointer0、copied1/degraded1、shadow1/in-place0，
  copy-in0、merge-back2688字节。本应用仅由GPU写表面，不扩大为零复制。
- 清除后前端导入made/released1/1、held0，首次释放检查通过，layer_removed及
  entered_background均为true。
- 呈现回调确已观察，用户实际看到图案；但presented_time和drawable_id均0，
  未证明硬件vsync/page-flip计时。原始App JSON保留awaiting_visual_confirmation，
  主机app-verification.json另存真实用户确认，不改写原始输出。

这是一个正常容器UIKit App的单帧CAMetalLayer呈现通过，不等于全桌面/所有应用GPU
加速完成。六项非致命设备能力查询仍记录为no device answer，未进行推测性补丁。

息屏回归7次背光请求均正确，bus-error0，包含启动过程和用户两次锁屏/唤醒。
传感器诊断本轮停在SLPI ready超时，原始结果已保存为`log/host/gpu-v173/slpi-result.json`；
后续由“传感器3”修复，本记录不将PAS返回成功表述为传感器可用。

日志槽1的4,556,035字节连续前缀及完整67,108,864字节均已备份，之后清空并读回确认。
没有END记录，因此是已捕获前缀，不是封口的整个运行期日志。原生syslog回收5,356,788
字节。APFS143→144、fullfsync=ok，设备由用户恢复Android。

下一步沿用已合格前端，验证连续多帧更新、drawable复用、实际像素和清除后的资源平衡。
动态状态和检查证据见`log/host/gpu-v173/continuation.json`、`integration-provenance.json`
和`integrated-runtime-evidence.json`。完整设备回收位于`log/device/nabu-boot-20261109-173/`。
