# v125：按已停用上下文条件释放 WLAN DMA

日期：2026-11-08，Asia/Shanghai。

## v124 实机证据

`log/device/nabu-boot-20261108-124/runtime-log/runtime.log:28405`：

```text
NABU WLAN DMA: stop cleanup incomplete; bank/tables/buffers retained status=7 phase=5 offset=0x10d8 expected=0 actual=0x1f300 readback=1 bank=54 program-phase=7 disabled=1 tlb-sync=1 retain=0
```

前一条 PAS command=6 的 result/response 均为 0。
`0x10d8 = GR1 CBAR base 0x1000 + 54*4`。清零写入没有改变已编程的
CBAR54=0x1f300；上下文停用与 ASID TLB 同步已成功，库明确返回
must_retain_tables=0。本轮证据定位了真实失败点，不再仅是 TCR2 候选解释。

## 释放条件依据

保存的同板 vendor 驱动
`log/host/wifi-recheck-v114/smmu-source/arm-smmu.c` 中
`arm_smmu_destroy_domain_context` 停用 SCTLR，移除中断并释放页表和 bank；
它不清零 CBAR、CBA2R、TCR、TTBR 或 MAIR。

固定版本库 `ArmSmmu4KDisableOwnedContext` 先核对完整上下文配置，拒绝
外部所有者的根、ASID、格式和属性；然后写 SCTLR=0 并核对真实读回，执行
TLBIASID/TLBSYNC，只有同步完成才清除 must_retain_tables。禁用后的配置值
不是仍有页表访问的证据。下一所有者在启用前必须重新编程自身完整配置。

## 修改范围

`NabuWlanDma::release_after_stop` 不再清零禁用后的配置寄存器；移除原阶段 5，
保留阶段 6/7 的既有编号。释放必须满足：

1. 调用方已经确认 PAS 停止（既有调用约定）。
2. WLAN 两个租用流槽仍属于本实例，ACTLR 符合本实例平台设置。
3. 两个 S2CR 写为 FAULT 并真实读回。
4. 对已编程上下文，库确认完整所有权、SCTLR=0、TLB 同步成功，且
   status=0、disabled_verified=1、tlb_synchronized=1、must_retain_tables=0。
5. 两个 SMR 恢复为选择时保存的无效值、S2CR 恢复为原值，全部核对读回。
6. ACTLR 恢复原值并核对读回后，移除故障处理并释放内存。

以上仍在共享 SMMU 配置锁内串行执行。仅尝试 ACTLR 初始化而从未编程
上下文的失败路径继续保留原有处理：确认 M=0 并恢复 ACTLR。其余归属、
停用、同步、流槽恢复或 ACTLR 失败仍保留内存和租约。

成功日志增加 bank、disabled、tlb-sync、retain、phase，并明确禁用配置保留。
失败日志继续输出已有准确阶段与读回。故障处理移除放到 ACTLR 恢复成功后；
这样 ACTLR 恢复失败时仍保有原处理器，完整的禁用配置也允许真实重试验证。

## 离线验证

旧代码使用与 v124 一致的 bank54、slot6/7、原 S2CR=0x200ff、ACTLR=3，
模拟 CBAR 零写入被忽略，并同时保留 Qualcomm FAULT 编码/TCR2 读回特征。
测试重现完全相同的 status=7、phase=5、offset=0x10d8、actual=0x1f300、
disabled=1、tlb-sync=1、retain=0；成功释放断言失败，退出 134。
证据：`log/host/wireless-v125/dma-disabled-before-fix/test.stderr`。

修正后通过 clang-18 ASan/UBSan：

```text
python tools/check_nabu_wlan_dma.py --output log/host/wireless-v125/dma-disabled-test
```

`report.json` 记录 hardware_tested=false，退出 0。测试确认 129 项分配释放，
CBAR/CBA2R 和 TCR/TTBR/MAIR 配置原样保留且停止期间没有写入，ACTLR 恢复为 3，
两个 WLAN 流槽恢复原始值，USB/UFS 和其他流槽不变。

外部流槽或上下文根被改写、TCR2 出现库不接受的 0x80 位，仍拒绝处理相应
外部状态并保留内存。FAULT 写被忽略、SCTLR 停用被忽略、TLB 超时、SMR
恢复失败和 ACTLR 恢复失败均保留资源。ACTLR 恢复失败的重试不再需要测试
手动恢复上下文映像，直接解除写故障即通过。原高地址内存和翻译测试仍通过。

此修改修复停止后资源保留问题，不是 WLAN 固件 PFR、FW_READY 或扫描修复。
arm64 构建、链接和 return-trace 检查已通过，候选位于
`artifacts/nabu-wireless-trace-v125`。完整 CI 和 v125 实机效果尚待验证。

## v125 实机验证通过

4f42554、完整 CI 42402284763 两个 job 全部成功后临时启动，桌面及 USB 正常。
完整日志确认 PAS6 返回成功后，bank54 的 disabled=1、tlb-sync=1、retain=0、
phase=7，随后明确记录映射和全部分配释放。清理问题已由实机闭环，配置保持
禁用状态下的旧值不再导致错误保留。

首次 WLAN PFR 仍在 43.631126 秒，PC=0xb019b9bc，FW_READY/INIT_DONE=0，
CE/HTC/WMI没有启动。蓝牙0x2005/0x200b/0x200c成功回执保持，另有一次0x200b
status12及后续成功；本轮未操作耳机。用户观察设置中的Wi-Fi按钮可见但不能点击，
当轮软件清单仍无wifid job、IO80211/IONetwork接口，BSD只有lo0/utun。

用户回Android且蓝牙关闭后，3,015,907字节连续日志及完整64MiB槽已备份清空，
清空回读成功，boot分区未改变。日志未封口，APFS94→95、fullfsync成功。
证据：`log/host/wireless-v125/result-summary.json`、
`log/device/nabu-boot-20261108-125/runtime-log/runtime.log:28761`。
