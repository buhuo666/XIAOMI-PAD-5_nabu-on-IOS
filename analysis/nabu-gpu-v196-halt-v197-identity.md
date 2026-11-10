# GPU196 暂停/恢复与 GPU197 独立页表接管

2026-11-10，Asia/Shanghai。

## GPU196 实机通过的范围

GPU196 使用与 GPU195 相同的内核，仅更新系统服务助手并增加 root 专用
`--dpu-only` launch job。普通助手仍为 mobile；诊断回包实测 UID 0。
用户确认启动后桌面与触摸正常，GPUInventory 就绪通过。

只读 Snapshot 通过：原 GOP 地址 0x9c000000 未变，51.030ms 内两路 INTF
各增加 6 帧。随后三个独立 HaltResume 请求均取得真实 XIN0/4 ACK；恢复后
CTRL0 和 CTRL1 的对应位都解除，VIG0/1 时钟位还原，原 GOP 地址不变，
两路计数再次各增加 6，IRQ 恢复且 fault=0。每次请求都有不同 ID。

用户确认三次后桌面保持正常、触摸正常。完整 64MiB 槽与 4,334,099 字节
有效日志已保全，四次 diagnostic-complete 检查点齐全；槽已清空读回，
Android 引导分区未变。

证据目录：`log/host/gpu-v196/`；重点为 `halt-resume-summary.json`、
`dpu-snapshot-check.json`、三个 `dpu-halt-resume-*-check.json`、
`halt-resume-feedback.json` 以及 `diagnostic-checkpoints.txt`。
完整槽位于 `log/device/nabu-boot-20261110-196/runtime-log/`。

解释边界：

- halt 流程耗时 10449/10385/10403us 包含请求写入前的同步 trace，不能称为
  单纯 ACK 延迟；resume 耗时 11/10/11us。
- IRQ underrun 累计不包含暂停期间清除的全部 latched 状态，不据此声称没有
  短暂 underrun。GPU197 额外保存 resume 时的 masked top status。
- 成功验证了修正后的 ACK 顺序和独立执行路径；GPU192 没有故障 PC，不能
  把这三次结果写成已证明 DSB 是旧黑屏的唯一原因。
- 本轮没有启用显示页表、切换源地址或验证无撕裂高刷。

## GPU197 候选

继续 `nabu-dpu=0 nabu-dpu-diag=1`，桌面仍由 GOP presenter 更新。新增
`DpuActivateGop` 请求，须先在本次启动中通过 Snapshot 和 HaltResume。
请求在专用内核线程执行，步骤为：

1. 排空并冻结 GOP 像素写入；不持门锁调用同步日志或硬件访问。
2. 启用硬件观察器，复用真正显示路径的 mapper prepare/preflight、IRQ 暂停、
   XIN halt、CB2 编程、TLBI/同步以及 resume。
3. 保持扫描地址 0x9c000000，使用该地址到原物理内存的 identity 映射。
4. 读回实际 SCTLR、TTBR0/1、CBAR/CBA2R、TCR/TCR2、MAIR、FSR、GFSR 和
   TLB 状态；比较完整路由快照及全部 4000 个 GOP 4K 页表叶子。
5. 验证扫描地址与时钟、双路计数和 IRQ 恢复，然后解除 GOP 写入门。

接管后保留表池与硬件观察器，继续检查 idle 时的实际 SMMU fault；允许再次
Snapshot 观察运行状态，不允许重复 ActivateGop 或覆盖已有 IRQ 绑定。
仍不创建测试显示缓冲区、不翻帧、不接管桌面 SwapEnd。

本地实际 mapper 回归包含坏 GOP leaf、SCTLR 改变、路由改变和 FSR 故障的
拒绝，ASan/UBSan 与 ARM64 编译通过；11 组生命周期/写入门回归通过。
完整云端编译和实机接管仍须完成。

完整目标继续 active：第 1 阶段通过，第 2 阶段的独立 halt/resume 通过；
页表、翻帧、系统/App Metal 兼容及持续高刷验收仍待完成。
