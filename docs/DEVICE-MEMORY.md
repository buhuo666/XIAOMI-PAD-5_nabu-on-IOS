# nabu 实机内存记录

采集时间：2026-11-03，Asia/Shanghai。输入是正在运行的 Android 导出的 FDT、`/proc/iomem`、`/proc/meminfo`；本轮没有改变设备状态。

**FDT RAM 减去固定 `no-map` 预留，精确等于 Linux 的 8 段 `System RAM`。** 高地址部分连续 11 GiB，但尚未把这段范围选为 XNU 管理窗口。

## 证据与复现

本地输入位于 `device/inventory-20261103-205739/`。完整机器可读结果保存在 `device/memory-map.json`，包括每个输入文件的 SHA-256、FDT 头部、节点名、属性、区间与比较结果。原始设备信息和 JSON 保留在本地，不随源码提交。

- `device.dtb`：715,588 bytes；SHA-256 `beac5c2b12dcf9545b748b715a7ebe2307fd3ad06e058915ca81cfc23b9a20c1`。
- FDT version 17，根节点与 `/reserved-memory` 均为 `#address-cells = 2`、`#size-cells = 2`；预留节点的 `ranges` 为空，采用恒等地址映射。
- FDT 头部 reserve map 没有非零条目；固定预留来自 `/reserved-memory/*/reg`。
- 区间一律写成 **左闭右开 `[start, end)`**，单位为 byte 地址。原始 `iomem` 的右端包含在范围内，解析时已加 1。

在工程根目录运行：

```powershell
python tools/inspect_device_memory.py device/inventory-20261103-205739 --output device/memory-map.json
```

## FDT 声明的 RAM

`/memory/reg` 包含 3 个条目。下表按地址排列，括号内保留原始条目序号。

| 地址范围 | 大小 | 原始条目 |
|---|---:|---:|
| `[0x80000000, 0xb9900000)` | 965,738,496 bytes | 1 |
| `[0xc0000000, 0x180000000)` | 3,221,225,472 bytes | 3 |
| `[0x180000000, 0x380000000)` | 8,589,934,592 bytes | 2 |

三个条目没有重叠，后两个高地址条目相邻。总计 **12,776,898,560 bytes = 12 GiB − 103 MiB**。外部跨度内的 `[0xb9900000, 0xc0000000)` 共 103 MiB 未被 FDT 声明为 RAM；它不是本次从 `/reserved-memory` 推算出来的预留。

## 固定预留

共 21 个节点，状态均有效。其中 20 个含 `no-map`，合计 **449,146,880 bytes**。另一个是 36 MiB 的 `cont_splash_region`。固定预留彼此没有重叠。

| 节点（`/reserved-memory/` 下） | 地址范围 | bytes | `no-map` |
|---|---|---:|---|
| `hyp_mem@85700000` | `[0x85700000, 0x85d00000)` | 6,291,456 | 是 |
| `xbl_dump_mem@85d00000` | `[0x85d00000, 0x85e00000)` | 1,048,576 | 是 |
| `xbl_aop_mem@85e00000` | `[0x85e00000, 0x85f40000)` | 1,310,720 | 是 |
| `smem@86000000` | `[0x86000000, 0x86200000)` | 2,097,152 | 是 |
| `removed_regions@86200000` | `[0x86200000, 0x8b700000)` | 89,128,960 | 是 |
| `camera_region@8b700000` | `[0x8b700000, 0x8bc00000)` | 5,242,880 | 是 |
| `pil_wlan_fw_region@8bc00000` | `[0x8bc00000, 0x8bd80000)` | 1,572,864 | 是 |
| `pil_npu_region@8bd80000` | `[0x8bd80000, 0x8be00000)` | 524,288 | 是 |
| `pil_adsp_region@8be00000` | `[0x8be00000, 0x8e000000)` | 35,651,584 | 是 |
| `modem_region@8e000000` | `[0x8e000000, 0x97600000)` | 157,286,400 | 是 |
| `pil_video_region@97600000` | `[0x97600000, 0x97b00000)` | 5,242,880 | 是 |
| `pil_slpi_region@97b00000` | `[0x97b00000, 0x98f00000)` | 20,971,520 | 是 |
| `pil_ipa_fw_region@98f00000` | `[0x98f00000, 0x98f10000)` | 65,536 | 是 |
| `pil_ipa_gsi_region@98f10000` | `[0x98f10000, 0x98f15000)` | 20,480 | 是 |
| `pil_gpu_region@98f15000` | `[0x98f15000, 0x98f17000)` | 8,192 | 是 |
| `pil_spss_region@99000000` | `[0x99000000, 0x99100000)` | 1,048,576 | 是 |
| `cdsp_regions@99100000` | `[0x99100000, 0x9a500000)` | 20,971,520 | 是 |
| `cont_splash_region@9c000000` | `[0x9c000000, 0x9e400000)` | 37,748,736 | 否 |
| `qseecom_region@0x9e400000` | `[0x9e400000, 0x9f800000)` | 20,971,520 | 是 |
| `cdsp_sec_regions@0xa4c00000` | `[0xa4c00000, 0xa8800000)` | 62,914,560 | 是 |
| `ramdump_fb_region@af000000` | `[0xaf000000, 0xb0000000)` | 16,777,216 | 是 |

`cont_splash_region@9c000000` 的 `[0x9c000000, 0x9e400000)` 同时出现在 Linux `System RAM` 资源内。这只证明资源范围重叠，不能据此认定启动交接时 framebuffer 已释放，或可覆盖该区域。

## 动态预留请求

8 个动态节点共请求 **310,378,496 bytes = 296 MiB**。它们均为 `shared-dma-pool`、带 `reusable`；FDT 提供的是 `size`、可选 `alignment` 和 `alloc-ranges`，没有固定 `reg`。当前快照不足以确定实际分配地址，不把请求大小再从 Linux RAM 总量中机械扣除。

| 节点 | 请求大小 | 对齐 | 备注 |
|---|---:|---:|---|
| `adsp_region` | 16 MiB | 4 MiB |  |
| `cdsp_region` | 4 MiB | 4 MiB |  |
| `user_contig_region` | 16 MiB | 4 MiB |  |
| `qseecom_ta_region` | 16 MiB | 4 MiB |  |
| `sp_region` | 8 MiB | 4 MiB |  |
| `secure_display_region` | 160 MiB | 4 MiB |  |
| `mem_dump_region` | 36 MiB | 未指定 |  |
| `linux,cma` | 40 MiB | 4 MiB | 默认 CMA |

这些节点的 `alloc-ranges` 原始值均为 address `0`、size `0xffffffff`；报告保留其原始长度语义，不把它误记为已分配地址或固定 4 GiB 区域。

## 与 Linux 的交叉核对

| Linux `System RAM` 地址范围 | bytes |
|---|---:|
| `[0x80000000, 0x85700000)` | 91,226,112 |
| `[0x85f40000, 0x86000000)` | 786,432 |
| `[0x98f17000, 0x99000000)` | 954,368 |
| `[0x9a500000, 0x9e400000)` | 66,060,288 |
| `[0x9f800000, 0xa4c00000)` | 88,080,384 |
| `[0xa8800000, 0xaf000000)` | 109,051,904 |
| `[0xb0000000, 0xb9900000)` | 160,432,128 |
| `[0xc0000000, 0x380000000)` | 11,811,160,064 |

这 8 段彼此没有重叠，全部位于 FDT RAM 内。它们的并集与 `FDT RAM − no-map − header reserve map` 逐字节相等，总计 **12,327,751,680 bytes**。

`MemTotal` 为 **11,766,512 kB = 12,048,908,288 bytes**，比上述资源并集少 **278,843,392 bytes**。`System RAM` 资源和内存统计口径不同；现有三份快照没有逐项解释这部分差额，不能将其整体归因于 CMA、显示或某一个驱动。

## 对 XNU 移植的含义

`[0xc0000000, 0x380000000)` 是本次 Android 快照中实证连续的 11 GiB RAM。能否以及如何用于 8796，需要结合启动时的 UEFI memory descriptors、DarwinBoot/内核/ADT 装载地址、framebuffer 占用和 8796 的映射限制再确定。当前 `xnu_policy.managed_window` 保持未选择。

低地址区被固件和协处理器预留拆成多段，不能用 `MemTotal` 从某个物理起点向后铺成连续窗口。动态池实际地址、UEFI 阶段占用以及 Android 与 XNU 两条启动链的预留差异仍是后续取证项。
