# GPU200 原机 GOP 属性对照与独立往返

2026-11-11，Asia/Shanghai。GPU199 完整槽已回收，保留 5,663,714 字节
有效前缀及 67,108,864 字节备份，清槽读回通过，Android 引导分区未变。
用户确认接管后持续黑屏。日志证明接管返回、计数和拓扑通过，但没有最终
IRQ、mapper 或解冻结果；不能把最后持久化行当作故障PC。

## 原机对照

固定 MiCode `71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c`：

- `log/host/gpu-zero-copy/source/android/sde_kms.c:882` 的 continuous splash
  identity map 只使用 `IOMMU_READ | IOMMU_NOEXEC`，没有 `IOMMU_CACHE`。
- `log/host/gpu-zero-copy/reference/nabu-r-oss-io-pgtable-arm.c:555` 对未设
  `IOMMU_CACHE` 的映射保留 AttrIndex0；MAIR index0 为 `0x44` Normal NC。
- 当前实现此前把原 GOP 也映为普通 slot 的 AttrIndex1／`0xff` WB。

GPU200 将永久 GOP 的4000叶改为 `GopLeafAttributes=0xec3` 加原PXN/UXN；
普通 IOSurface slot 仍为 `LeafAttributes=0xec7` 的 WB。
这修正了明确的原机属性差异，尚未证明它是黑屏原因。

## 恢复后诊断

XIN halt/resume、CB2 上下文编程和扫描地址流程保留。接管返回后，先读取
实际 mapper/fault 再执行其他诊断 checkpoint：

- FSR/GFSR、64位 FAR、FSYNR0、CBFRSYNRA 原值及 TLB status。
- 实际上下文、全部路由和4000个 NC GOP identity叶。
- 已 active 但 poisoned 时仍返回现场，保持失败并禁止资源释放。
- 同步日志 checkpoint 的返回另有标记，区别“已打印进入”和“真正返回”。
- 暂停/接管后 IRQ 必须在新观察窗口内推进，累计值大于零不再够用。

## 独立往返入口

`DpuFlipGop` 仅在同启动完整 `ActivateGop` 已通过后准入：

1. 创建原始 MiniIOSurface，直接写红/蓝左右半屏，发布 CPU cache，再获取
   NativeAdreno descriptor read lease。它是 CPU 图案扫描测试，非 Metal 绘图。
2. 排空并冻结 GOP 写入，复用真实 `flip/submitFrame/Scan::poll` 扫描这份
   表面的原始物理页；不复制桌面，不使用 shadow scanout。
3. 保持3秒，再以新的扫描序号提交永久 GOP。
4. 双路提交后跨帧、CTL flush 清零、地址/stride 读回确认接受后，
   `acceptGop` 退休旧 slot，完成实际 TLBI 与 descriptor release，再释放
   IOSurface/read lease，最后由生产收尾解除 GOP gate。

扫描 sequence 来源于已接受状态，与页表 mapping token 分开。任一不确定
写入、接受或 TLBI 失败保留相关资源；请求标志与实际地址改变证据分别报告。
GOP 属性调整和这个诊断都不表示整个桌面已改为零复制呈现。

## 验证状态

本地 PageTable、Mapper、ScanoutCore 的实际函数、ASan/UBSan 与 ARM64
回归通过，包含 NC/WB 区分、往返复用、旧 token、单路/flush 拒绝和故障保留。
显示生命周期12组通过，完整 Display ARM64 对象通过。

独立往返主机测试执行真实 Display、ScanoutCore、PageTable 及 Mapper
生命周期，另检查实际诊断字典；最终结果保存于
`log/host/gpu-v200/flip-gop-check.json`。它不是实机接受或视觉验收。
后续仍须完整云端内核/助手编译、64对象链接、加载器与 APFS 检查，再实机
先验证接管、原桌面画面、独立往返及资源释放。

完整四阶段目标保持 active，系统/App Metal 兼容和持续高刷新验收仍待推进。
