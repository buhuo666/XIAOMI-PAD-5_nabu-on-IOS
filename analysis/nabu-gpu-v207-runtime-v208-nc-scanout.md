# GPU207 实际存储证据与 GPU208 NC 取数对照

2026-11-11，Asia/Shanghai。GPU207源码`358eedd8dce2ada41dc60d7791ee2173d254e9d2`，
完整内核CI42972474193、助手CI42972474176通过。桌面和触摸正常；普通暂停/恢复、
不暂停XIN的页表接管（5386us）和独立显示IRQ恢复再次通过画面验收。

## 原始翻帧仍未显示图案

GPU207的原始CPU红蓝表面保持10,001,023us后返回GOP：

- 翻帧前后各10,240个样本，红/蓝各5120，错误0，哈希相同。
- Active表面前后各4000页，CPU实际物理地址、描述符和L1/L2/L3全部匹配。
  首页`0x2c6a4c000`，末页`0x2c6593000`；叶使用MAIR index1的WB属性。
- 双VIG在停留前后均为IOVA`0x20000000`、stride6400，CTL flush均0。
- IRQ及双vsync各增加1204，新增underrun0；回到GOP后映射与表面释放成功，frozen0。
- SCR0实际为`0x2e0406`，CLIENTPD为0；不是全局关闭翻译。
- 用户确认：黑了几秒后返回桌面，无红蓝，触摸正常。

这些结果排除了已采样CPU图案错误、软件看到的4000页映射不一致和停留边界的源寄存器
回退；**不能证明DPU实际从这些页取出了正确像素**。翻帧视觉验收仍失败，未接入桌面。

完整67,108,864字节槽及5,277,593字节连续日志已回收，清空读回通过；Data184→185，
Android引导分区未变。记录位于`log/device/nabu-boot-20261111-207/`和`log/host/gpu-v207/`。

## 原机DMA属性对照

固定MiCode版本`71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c`：

1. `msm_smmu.c:220`普通显示DMA映射初始attrs=0，经DMA API分配IOMMU保护属性。
2. `arch/arm64/mm/dma-mapping.c:58,1106,1649`的`is_dma_coherent`和
   `__get_iommu_pgprot`仅在设备/显式请求一致性时添加`IOMMU_CACHE`。
3. `drivers/staging/android/ion/ion.c:348`的`ION_FLAG_CACHED`影响CPU同步是否跳过，
   不直接等同`IOMMU_CACHE`。普通和导入内存的CPU缓存属性不能作为DPU叶WB的依据。
4. 原机显示DT节点`/soc/qcom,mdss_mdp@ae00000`及所有祖先均未声明`dma-coherent`；
   现场列表保存在`log/host/gpu-v207/original-dma/android-display-dma-profile.json`。
5. `io-pgtable-arm.c:548`未加CACHE或另行upstream/LLC提示的普通映射使用MAIR index0，
   即Normal NC。`MSM_BO_KEEPATTRS`的upstream路径另有条件，不把它视作所有表面的默认值。

新增原机源码的下载记录在`log/host/gpu-v207/original-dma/sources.json`。这些源码和DT
说明存在明确的属性选择差异，尚未证明它是图案黑屏的根因。

## GPU208 改动与验证

只把普通DPU slot的叶属性从`(3<<53)|0xec7`改为`(3<<53)|0xec3`：
MAIR index1/WB→index0/NC。CPU内存仍为原始缓存表面；保留CPU PoC发布、GPU producer
完成栅栏、物理页共享、页表WB发布、恒等接管、IRQ/CTL顺序和退休协议。

诊断报告新增`test_leaf_attributes`，逐页读回和主机检查器验证实际NC叶；旧GPU207的WB
结果仍可按原格式回看。沿用GPU207助手和10秒图案，不重新引入限时请求窗口。

本地页表完整4GiB遍历及ArmSmmu4K NC编码对照、实际Mapper/ARM64、Display全文ARM64，
20组翻帧/生命周期与77,824,000原始像素回归通过。GPU208实机结果待验。

下一项依旧是独立接管、恢复IRQ、原始图案/GOP往返及真实画面；系统桌面持续呈现和
高刷新验收均未完成，完整GPU四阶段目标保持active。
