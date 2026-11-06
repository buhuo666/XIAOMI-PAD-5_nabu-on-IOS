# 用户提供的 Android boot 镜像与无线修复路线核对

2026-11-07，Asia/Shanghai。目标仍是实际 Wi-Fi 联网、原生蓝牙发现/配对及共同使用；本文不把构建、能力声明或命令应答替代这些验收。

## 1. 镜像实际内容

输入：`anzhuoboot/nabuperfectboot-boot-noroot.img`，134,217,728 字节。仅离线读取和解包，没有启动或刷写此镜像。

| 项目 | 实际结果 |
|---|---|
| boot 格式 | Android boot v3，header 1580 字节、page 4096 |
| kernel | offset 4096，44,653,056 字节，AArch64 Linux Image |
| kernel 版本字符串 | `4.14.180-MJW-Uotan-g654d4b0ca732` |
| ramdisk | offset 44,658,688，gzip 25,575,267 字节；解压 newc CPIO 66,720,256 字节，共3660项 |
| ramdisk 产品 | `ro.product.bootimage.name=twrp_nabu`，`eng/test-keys` |
| ramdisk 构建时间 | 2023-09-19 08:48:52 CST；属性字符串，不证明外部来源 |
| boot header OS 字段 | 13.0.0 / 2023-08；与ramdisk的版本字符串独立记录 |
| DTB | kernel内未找到有效FDT候选，ramdisk没有DTB文件，尾部没有FDT magic |
| 无线固件/校准输入 | ramdisk清单未发现wlanmdsp、bd_k82c、crbtfw、crnv或firmware目录下的普通文件 |
| 尾部 | AVB footer v1.0；原镜像长度70,234,112，vbmeta offset70,234,112、size704；未作签名/哈希审计 |

这份文件明确带有TWRP及定制内核标识，不能当作已经确认的小米原厂镜像。当前设备Android的实读内核为`4.14.180-moon-gc580e2089`，也与此文件不同。

提取结果位于`artifacts/android-boot-reference-20261107/`：`inspection.json`、`header.json`、`kernel.config`、`ramdisk-inventory.json`及`selected-ramdisk/`。配置由kernel内`IKCFG_ST/IKCFG_ED`之间的gzip解出，没有按文件名猜测。

## 2. 镜像提供的硬件路径证据

内核实际启用：`CONFIG_ICNSS=y`、`CONFIG_ICNSS_QMI=y`、`CONFIG_QCA_CLD_WLAN=y`、`CONFIG_MSM_BT_POWER=y`、`CONFIG_BTFM_SLIM_WCN3990=y`、`CONFIG_QRTR=y`、`CONFIG_QCOM_SMEM=y`、`CONFIG_QCOM_GLINK=y`、`CONFIG_ARM_SMMU=y`及`CONFIG_QCOM_MINIDUMP=y`。`CONFIG_CNSS2`与`CONFIG_CNSS_QCA6390`未启用。

这些配置与之前从本机Android提取的ICNSS/SNOC和WCN399x路径一致，但配置本身不能证明精确封装型号。已保存的运行设备树为`log/host/wireless-v76/android/device-tree.json`：

- `/soc/qcom,icnss@18800000`：`compatible=qcom,icnss`；寄存器基址0x18800000；SMMU SID0x640、IOVA base0xa0000000、size0x10000000。
- `/vendor/bt_wcn3990`：`compatible=qca,wcn3990`，三路BT供电引用与WLAN部分共用。
- `/soc/qcom,glink/modem/qcom,modem_qrtr`：IPCRTR通道。
- Android属性`ro.wlan.chip=39xx`；UART ROM/固件查询及当前HCI版本另有实机记录。

因此不能把另一份路线的“QCA6391”当作已验证前提。本文采用证据支持的ICNSS/SNOC + WCN399x描述，保留精确封装识别问题。

## 3. 外部路线中需要纠正的事实

| 外部说法 | 本项目的证据与结论 |
|---|---|
| WLAN运行在RISC-V子核 | 当前实际加载的`firmware/nabu-wireless/wlanmdsp.mbn`为ELF32，e_machine=164，readelf识别为QUALCOMM DSP6/Hexagon，入口0xb0000000。RISC-V说法不适用于此固件。 |
| GLINK没起来 | 第103轮报告明确agreed=1、open=1、broken=0、tx2504/rx2533、close-ack=1；4,331,136字节WLAN固件经TFTP完成，真实WLFW服务69已经上线。 |
| registration-status=0x4表示GLINK握手失败 | 原机`wlan_firmware_service_v01.h`定义0x04为`QMI_WLFW_MSA_READY_V01`，这是WLAN状态位，不能当作GLINK错误码。 |
| 0x4005/0x4006是WLAN服务端口 | 它们是本项目新分配的APPS侧DIAG控制/数据端口；WLFW服务69的远端端口从真实公告学习。 |
| boarddata已经确认校验失败 | 没有这样的报错。第103轮五段BDF下载共26,328字节均成功应答，之后CAL_REPORT请求成功，再出现WLAN RT异常PC0xb019b9bc。成功应答不证明BDF内部所有语义正确，但也不能把后续异常命名为校验失败。 |
| 当前在灌别的机型BDF | 现在用的是该设备Android实际选中的`/vendor/firmware_mnt/image/bd_k82c.bin`，第91轮已替换通用bdwlan.bin。来源与选择日志保存在`wireless-v91/android/`。 |
| 必须先导出每机OTP形成BDF | 未找到此设备需要这条导出流程的证据。BDF、主机校准缓存、固件内部OTP/NVM不能混称。本boot.img未包含可导出的这些输入。 |
| 0x0c03证明Apple私有命令兼容 | 0x0c03是标准HCI Reset，OGF=3/OCF=3；并不是0xC0xx或厂商FCxx命令。Reset成功不能证明Broadcom/Apple VSC在QCA上可用。 |
| fce2/fce9只因coex未上线而失败 | 已保存的原生bluetoothd静态证据将它们映射为Broadcom Olympic WBS/LE settings和LEMetaEnableFeatures；没有证据表明上线某个QRTR coex服务就会令QCA接受这些厂商语义。 |
| 蓝牙循环完全是WLAN下游故障 | 第103轮独占HCI诊断已直接复现Reset后200b成功，另一Reset区间204a成功后相同200b返回12，最终Reset及版本/地址核对成功。至少存在独立的标准命令族策略冲突。 |

无线实机证据：`log/host/wireless-v103/wireless-report.txt`。蓝牙首次完整诊断的无关日志过滤版：`log/host/wireless-v103/le-family-first-boot.txt`。Broadcom VSC静态映射：`analysis/nabu-bluetooth-interface-findings.md`中的“daemon下一层确实仍使用Broadcom VSC表”。标准命令族规则复用已保存的Bluetooth Core5.4原文`wireless-v101/bluetooth-analysis/core54-hci-section-3.1.1.txt`。

## 4. 本轮取得的真实进展与限制

第103轮用户确认桌面正常。与第102轮使用同一内核/bootstrap，本轮等桌面确认后才开启USB服务探针；这一次未重现HALTED，不能据一次对照宣称已经确定或修复第102轮停机原因。

蓝牙首次诊断的初始/分隔/最终Reset均status0、response-bytes1；A/B/C为0/0/12；最终版本/地址检查成功、boot生命周期errno/status均0。原生daemon随后仍按旧策略初始化，因此仍有712扫描重启；诊断成功不是扫描修复。

Wi-Fi仍在0xb019b9bc出现WLAN RT异常。DIAG控制源实际送来FEATURE mask `f7 fe 03`和NUM_PRESETS值2；数据实例当前0包。MODEM↔TZ公共目录entry10、offset0x163000、size0x2000，仅观察目录，未访问受保护payload。

第103轮15,234,415字节有效日志及完整64MiB槽已备份清空回读，APFS计数72→73、fullfsync成功。没有终止记录，不能把有效前缀称作完整终止日志。设备当前已回Android。

## 5. 依据证据继续推进

1. WLAN：沿用已核实的本机固件/BDF，对照ICNSS原机电源、SMMU/MSA权限和状态机；继续DIAG真实能力/ID协商，定位MMIO异常对应的访问及所缺依赖。取得证据前不改未知保护位、不猜读OTP、不把host缓存缺失直接判为根因。
2. 蓝牙：统一原生host实际使用的legacy/extended命令族，继续检查原生配置入口；单独核对所需Broadcom VSC与QCA可提供的真实功能。不能期待WLAN就绪自动改变两家厂商的命令语义。
3. 最终验收仍包括原生服务稳定、实际Wi-Fi扫描/连接/收发、蓝牙发现/配对/目标外设、冷启动和2.4G共同使用；共存机制要依据本机接口实现及实测，不能仅以服务名判断。

DIAG协商与蓝牙slot18源码候选已保存为`log/host/wireless-v104/parked-*.patch`，从本轮生产工作树撤出，不参与第104轮。蓝牙候选通过替换原生初始化函数槽改变流程，属于上层拦截式兼容；虽然没有伪造HCI回应或修改控制器能力，也不能将它称作“完全无拦截”。原生配置调查见同目录`bluetooth-native-policy-options.md`：现有AE Disable键只能禁用芯片默认能力，不能把枚举13的false提升为true；尚未找到绕过slot24的原生偏好入口。

## 6. 随后提供的官方 V14.0.7.0 线刷包

用户随后提供`mi_pad5_miuiV14.0.7.0.TKXCNXM/nabu_images_V14.0.7.0.TKXCNXM_13.0/`并说明来自小米官方线刷包。此来源与前述TWRP文件分开记录。仅离线解析，不执行flash脚本，不写入设备。

已经从Android sparse super元数据精确提取1,300,422,656字节vendor_a，不需要展开整个super。ext4使用debugfs默认只读模式导出cnss-daemon、QMI库、蓝牙HAL、无线配置及init文件。`vendor_boot.img`提取5个FDT；`dtbo.img`7个overlay中index6明确为NABU/board-id0x30。NABU overlay中的蓝牙compatible仍为`qca,wcn3990`；vendor属性`ro.wlan.chip=39xx`、Bluetooth SoC为`cherokee`。官方kernel为`4.14.180-perf-gcc5ee28d3084`，2023-10-25构建。

产物与来源索引：`artifacts/miui14-official-reference/`、`artifacts/miui14-official-wireless/`；可复现提取脚本`log/host/wireless-v104/extract_official_reference.py`。

### 官方包与目前使用输入的实际差异

| 内容 | 逐字节比较结果 |
|---|---|
| bd_k82c.bin | 完全一致 |
| 原始crbtfw32.tlv、crnv32.bin | 完全一致；部署版NVM另有已记录的本机地址/波特率/sleep配置变更 |
| 7个servreg文件 | 完全一致 |
| WLANMDSP.MBN | 总大小一致；781字节不同全部位于PHDR1认证元数据段，所有PT_LOAD代码/数据完全相同；WLAN版本字符串一致 |
| MPSS/modem | OEM构建20230306与当前20240516不同，12个可加载段存在实际差异；不是只换签名的问题，尚不能归因为当前PFR |
| cnss-daemon | 官方与此前读机版本均95112字节，全文完全一致 |

细节：`log/host/wireless-v104/official-firmware-comparison.md`及JSON。以上比较用于实际版本差异分析，没有再次进行哈希审计。

### 官方确认的请求缺项

原daemon的CAL_REPORT发送函数及真实QMI编码表共同确认：空缓存时body为
`01 01 00 00 11 01 00 00`；现有实现此前只有`01 01 00 00`。缺项是optional
TLV0x11、长度1、值0。官方daemon再次独立提取确认，字段语义名仍未知，不将其命名为OTP或校准完成开关。

第104轮仅补此四字节，保留第102/103轮其它内核行为、固件和蓝牙bootstrap；协议回放按官方独立wire向量验证并通过ASan/UBSan。实际FW_READY、PFR是否改变仍需实机结果。BDF、主机缓存、固件内部OTP的区别及原始编码表证据见`log/host/wireless-v104/boardcal-provenance-review.md`。
