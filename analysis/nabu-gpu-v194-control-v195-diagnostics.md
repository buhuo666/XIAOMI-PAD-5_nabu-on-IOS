# GPU194 对照与 GPU195 独立诊断

2026-11-10，Asia/Shanghai。

## 已取得的实机结果

GPU194 与 GPU192 使用同一份实际内核及 bootstrap，启动配置只将
`nabu-dpu=1` 改为 `nabu-dpu=0`，保留 Hall、120Hz 和 DPU 检查点开关。
用户确认桌面和触摸正常，随后 MetalPresent 动画与清除图案正常。

本次 App run_id 为 `1794321266606975`，不同于启动前保存的旧结果
`1794304274496653`。当前启动的插件挂载与 accelerator ready 预检通过。
64 帧 GPU 输出和实际 IOSurface 各检查 4,194,304 个像素，错误均为 0；
3 个直接共享导入、3 个原位纹理，复制及 shadow 均为 0，清除后全部释放。
两个 drawable 各复用 32 次，64 个呈现回调。

完整 64MiB 槽及 6,504,755 字节有效日志前缀已保全，槽清空读回通过，
Android 引导分区未变。手动恢复没有正常结束记录，因此日志格式报告
`incomplete / no committed record header`；这不表示已保存的连续前缀丢失。
`NABU_METAL_FAULT armed=SIGSEGV` 是信号处理器安装记录，不能计作崩溃。

证据：

- `log/host/gpu-v194/control-config-proof.json`
- `log/host/gpu-v194/same-deployed-images.json`
- `log/host/gpu-v194/desktop-feedback.json`
- `log/host/gpu-v194/app-feedback.json`
- `log/host/gpu-v194/shared-app-check.json`
- `log/device/nabu-boot-20261110-194/runtime-log/`

结论：同内核禁用 DPU 后，桌面与既有 GPU 共享绘图基线恢复。黑屏回归
属于新 DPU 接管路径，不能归因为整个内核不可引导或 GPU 不能绘图。
GPU191/192 在 VBIF 0x200 写入检查点后停止的确切故障指令仍未取得。
GPU193 的 relaxed 写入/真实 ACK 顺序仍需实机验证。

## GPU195 的范围

使用 `nabu-dpu=0 nabu-dpu-diag=1`。启动只发布诊断能力，保持 fDpu 为空、
GOP 显示与软件节拍不变。原有 GPU 渲染和 Hall/120Hz 配置继续保留。

管理员经配对 USB helper 向 IOMobileFramebuffer 的 setProperties 发送
独立请求，每个请求有唯一 RequestID，内核线程执行并发布同 ID 的结果：

1. `DpuSnapshot`：桌面首帧出现后，读取继承拓扑、源地址、时钟与双路帧计数。
   不访问 VBIF，不修改 DPU 或 SMMU 寄存器。
2. `DpuHaltResume`：只有本次启动的快照通过才接受。先排空并阻止 GOP
   presenter 的 show/settle 写入，接管并暂停显示 IRQ；执行原机 VBIF
   request/ACK 顺序，捕获真实 ACK 后立即恢复。暂停期间不分配、不写日志、
   不做同步检查点。之后核对请求与 ACK 解除、时钟位恢复、原 GOP 地址、
   两路计数继续递增及实际 IRQ 恢复。

本轮不调用 mapper、不修改 CB2、不提交显示地址或测试缓冲区。诊断不持有
显示或 registry 请求锁执行硬件操作；GOP 写入门在排空后释放锁。硬件写入
后结果不确定时保持写入门冻结、保留状态，等待实际恢复，不伪造回退成功。

本地 11 组实际函数生命周期/并发回归通过，包括正在绘图时等待、冻结期间
阻止下一次写入、伪唤醒以及真实解除冻结。扫描协议 ASan/UBSan 回归及
ARM64 编译通过；DPU 集成对象 ARM64 编译通过，最大单函数栈 480 字节。
完整 framebuffer 本地私有头编译环境存在既有 typed-allocation 宏问题，
由完整 macOS CI 编译验证；尚未把本地替代测试视作物理 DPU 通过。

## 完整目标的状态

1. 同内核 DPU 关闭与真实 GPU 基线：通过。
2. 独立 DPU 暂停/恢复、页表、翻帧：GPU195 首先验证暂停/恢复，其他仍待验。
3. 原版系统及真实 App Metal 兼容与耗时：继续保留，尚未完成。
4. 正确、无撕裂、低延迟、持续高刷：尚未完成，120Hz 属性及 64 帧测试均不能替代。

## GPU195 实机与 GPU196 助手修正

完整内核 CI 42837281278、helper CI 42837281139、链接及加载器检查通过后，
GPU195 已临时启动。用户确认桌面和触摸正常，GPUInventory 就绪通过。
`NabuDpuDiagnosticAvailable=true`；第一次 Snapshot 的 submit_status 为
`0xe00002c1`。实际服务助手 UID 为 501，原 launch job 的 UserName 是 mobile，
与此前把它当作 root 助手的假设不符。内核的管理员检查拒绝了请求，状态仍为
`waiting-for-post-desktop-request`，没有任何 diagnostic-* 检查点或 DPU MMIO。

3,854,535 字节有效日志及完整 64MiB 槽已回收，清空读回通过，引导分区未变。
这不是新的物理 DPU 失败，也不构成暂停/恢复验证。

GPU196 复用相同的 GPU195 内核，仅更新助手与 launch job。普通服务继续 mobile；
新增 root job 以 `--dpu-only` 进入只处理两个固定 DPU 动作的入口。mobile 助手
转发配对主机请求，root 助手执行管理员 IORegistry 请求并返回同 ID 的真实结果。
结果位于 root 所有的 `/private/var/run/nabu-dpu`，只有 requests 子目录供 mobile
写入；root 不在 mobile 可替换的父目录中创建结果或修改目录所有权。
