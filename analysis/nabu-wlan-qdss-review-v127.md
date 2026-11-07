# v127 QDSS 投票与 MSA 对照的独立核对

日期：2026-11-08，Asia/Shanghai。仅复用已有参考、源码、设备树和产物；未下载、
未操作设备、未改生产代码或主线程的 modem power 测试。本次只新增本文。

## 结论

QDSS on/off 有具体参考实现和 SM8150 公开 Linux 描述，值得作为单独变量验证。
当前 Nabu 已保存的源码、v126 冻结内核和实际 ADT 未显示其他 APPS QDSS 投票者；
蓝牙现有路径没有 QDSS 请求。停止后撤销本轮 WLAN 请求，没有已发现的当前
驱动消费者冲突。但是 mailbox 锁不是时钟引用计数，且没有 AOP 全部投票者或
真实时钟状态读回，因此不能据此证明任何远端/开机遗留使用都不存在。

厂版 Android ICNSS 节点没有 clocks，vendor 源码也没有 QDSS clock 获取；
公开 Linux DTS 与 Raphael 成功记录不能写成“同板 Android 明确要求这条票”。
MSA identity mapping 的 v115 反证仍成立：额外恒等映射是 Raphael 的实现差异，
不是已经发现的 Nabu 原机漏项，本轮不应混入。

## 1. Raphael 的请求与生命周期

参考目录 `D:/github-IOS/research-sources/helium-hackios-raphael`，只读确认
HEAD=`57722468a3774e2ec60017705ec356ae9b31f40e`。

- `xnu/files/bsd/dev/hakios.wifi.c:4144` 的 icnss_power 在五路电源投票成功后
  设置 icnss_qdss_touched，再发 `{class: clock, res: qdss, val: 1}`。
  touched 在发送前置位，所以 ACK 超时不会丢掉后续撤票责任。
- 同函数 off 先发送 `{class: clock, res: qdss, val: 0}`，只有成功才清 touched；
  然后才逆序撤五路供电。本次只复用 QDSS 文本与生命周期，不能复制 Raphael
  五路电源/L10C 配置，Nabu 四路 LDO 也是蓝牙正在使用的共享资源。
- icnss_bootstrap 在 MSA_INFO、权限、MSA_READY、CAP 之后、BDF/CAL 之前
  调 icnss_power(true)，不是在 CE 或扫描完成之后才打开。
- mailbox_send:1626 取 hakios_aop_mailbox_lock，发送固定 64 字节、零填充
  文本，32 位写入 message RAM，再 doorbell 并等待消息长度被清零。
  这证明消息被对端消费；没有返回独立的 QDSS 频率、门控或使用计数。
- dsp_shutdown:1873 先停止 host/link，再 PAS_SHUTDOWN；只有 SMC result 和
  answer 均为零才调用 icnss_memory_stop:4223，后者撤销 QDSS/电源并归还 MSA。
  PAS 停止未确认时直接返回，不撤这些资源。
- `wifi/lx/ath10k/host.c:73` 的 regulator/clock 适配只借用 ICNSS 已持有状态，
  clk_bulk_disable_unprepare 是空操作；它不是第二套实际 QDSS 投票者。

`docs/RAPHAEL.md:71` 说明 QDSS 与固件 CoreSight 初始化有关，且作者记载补
L10C/QDSS 后两轮 FW_READY。这是该分支作者记录；被引用的原始实机日志与
固件反汇编不在此次已有参考中，不能独立确认其异常地址就是 Nabu 同一访问。

## 2. Nabu 两类 Linux 证据必须分开

### 公开 Linux SM8150 / ath10k

保留路径 `log/host/wireless-v76/source/`：

- `arch/arm64/boot/dts/qcom/sm8150.dtsi:4680` 的 wifi@18800000 为
  qcom,wcn3990-wifi；clock-names 是 cxo_ref_clk_pin/qdss，clocks 分别指向
  rpmhcc RF_CLK2 与 aoss_qmp。
- `drivers/soc/qcom/qcom_aoss.c:279` 的 qmp_qdss_clk_prepare/unprepare 发送
  与 Raphael 完全相同的 val:1/0 文本。provider 注册一个名为 qdss 的 clk_hw，
  不是给 WLAN 创建一个独立且带 WLAN ID 的硬件资源。
- `drivers/net/wireless/ath/ath10k/snoc.c:54` 列两个时钟名；:1796 用
  devm_clk_bulk_get_optional。:1027 在 regulator enable 后调用
  clk_bulk_prepare_enable；:1044 在 power_off 时 disable_unprepare。
  这证明该公开树支持并使用 QDSS，但 optional 获取不能证明所有设备配置
  均须由 ath10k 显式提供这一票。
- 同一 DTS 的 stm@6002000、funnel@6041000 等 CoreSight 节点也引用
  aoss_qmp，名称为 apb_pclk。由此可知 QDSS 在平台上不是 WLAN 私有时钟。
  Linux 使用公共 clock provider 管理这些客户端；直接发 QMP 的 Nabu 路径
  没有因此自动获得 Linux 的客户端生命周期管理。

### 厂版 Android 原始 FDT / ICNSS

本次用已有 `tools/inspect_device_memory.py` 的 read_fdt 只读解析
`log/host/wireless-v76/android/device.dtb`，确认
`/soc/qcom,icnss@18800000` 的全部属性中没有 clocks 或 clock-names；其唯一
子节点是 qcom,smp2p_map_wlan_1_in。不是 JSON 漏选字段：
`tools/collect_nabu_wireless.py:62` 对选中的节点保存全部属性。

`log/host/wireless-v76/source/vendor/drivers/soc/qcom/icnss.c:140`
的 clock 表只有 `{NULL, "cxo_ref_clk_pin", 0, false}`；:2829 获取失败在
required=false 时忽略，:484 遇到空 handle 就跳过，没有 qdss 条目。

厂版 FDT 并非全无 QDSS：phandle 0x44 对应 `/soc/qcom,aopclk`，compatible
为 qcom,aop-qmp-clk、mbox-names 为 qdss_clk，部分 CoreSight funnel 引用它。
这说明厂版系统存在另一套 trace clock 路线，不证明 WLAN 直接请求它，也不
证明其在 Android 或 iPadOS 中始终开启。已有
`log/host/wifi-recheck-v114/android/clocks.txt` 是 0 字节，不能从空文件推断
enable_count=0 或某个具体投票者没有运行。

所以正确措辞是“公开 SM8150 Linux 路线与 Raphael 实测支持的候选补全”；
“同板必需”“厂版也逐次发该消息”“已定位 Nabu PFR 根因”均超出当前证据。

## 3. 当前 iPadOS 基核与蓝牙消费者核对

检查范围为 `src/hakios-8796/drivers`、Nabu patches、当前实际链接基核及
冻结 v126 内核。主线程正在加入的 v127 QDSS 代码不算已有第二消费者。

- 基核 `drivers/wifi/hakios.wifi.c` 只见 wpss image load_state；
  `drivers/audio/hakios.adsp.c` 只见 adsp image load_state；
  `drivers/modem/hakios.mpss.c` 只见 modem image load_state。三者与 Nabu
  共享 `drivers/core/hakios.platform.c:52` 定义的 mailbox mutex，没有
  qdss 或 class:clock 请求。
- 只读搜索 `artifacts/nabu-services-prelink-v79/kernel.native-apfs.macho`
  与 `artifacts/nabu-wireless-v126/kernel.native-apfs.macho`：两者 qdss
  大小写不敏感命中 0、class:clock 文本命中 0；class:image 分别 6/7 处。
  这与源码一致，但字符串负搜索不排除未识别的动态生成或远端固件行为。
- 解析 v126 实际 `artifacts/nabu-chain-v126/EFI/Nabu16/Payloads/
  kernel.macho.adt`：只有 chosen/cpus/arm-io/gic/psci/defaults/options/
  product/nabu-touch/nabu-bluetooth/nabu-modem 等节点，无 QDSS/CoreSight。
  不可把 Android FDT 的 trace 节点当成当前 ADT 中实际启动的消费者。
- `NabuBluetooth.cpp:1038` 共享电源是 ldoa1、ldoa7、ldoc2、ldoc11；
  serial_clock:79 使用 GCC wrapper2 AHB/GENI serial3 时钟；传输与休眠是
  UART/IBS 路径，已有逻辑明确 shared supplies retained。未发现 QDSS
  请求或 QDSS 依赖的直接 MMIO 操作。
- `NabuWireless.cpp` 与 `NabuGlink.cpp::runtime_tick` 会在 WLAN ready/loss
  后排队 BT，BT 可以在 WLAN 停止清理之前已运行。因此停止边界不能以
  “BT 尚未开始”为理由；应只撤独立 QDSS 请求，保留四路 LDO 和 BT GCC。

限定结论：没有发现当前自有 APPS QDSS 使用者会被本轮 off 覆盖；现有 BT
源码没有共享这个投票。尚未取得 AOP 资源状态、所有远端票、bootloader 留存
票或实际 QDSS 门控寄存器读回，不能绝对保证 off 对所有隐藏消费者无影响。
本轮仍需在 off 后观察原生 BT HCI/服务与桌面/USB 基线。

## 4. 单独 QDSS 候选的释放边界

最小实现应保持以下可审查条件，不依赖 UI 或伪造 ready：

1. 仅 WLAN 初始化请求 QDSS，先于本轮固件/BDF/CAL，持续覆盖其运行期。
2. 与现有 image load_state 共用 mailbox 锁，记录请求是否实际写入及 ACK。
   请求发出但 ACK 未到仍可能生效，应保留 touched/待撤状态。
3. 没有发过本轮 on，不发送“顺手 off”。若已尝试启动 PAS，须 PAS6 明确
   成功才可 off；失败时保留 QDSS/MSA/DMA 等当前所有权。未请求 PAS 的前期
   失败可撤已发送的本轮 QDSS 请求。
4. off ACK 成功才清本轮 pending-off。该 ACK 表示消息消费，不等于测得
   物理时钟已关闭，也不说明别的 firmware master 的票被清除或保留。
5. 不改 Nabu 四路电源、BT UART/GCC、不新增 MSA 映射或 Raphael L10C，保持
   FW_READY、首次 PFR 与后续目标通信的因果对照。

共享 mutex 只能防止两个消息同时覆盖 mailbox，不能防止两个未来 QDSS 客户端
先后发送 on 后其中一个 off。若今后实际接入 CoreSight 或另一客户端，必须
在那时由共同资源所有者管理引用/请求状态；不能沿用“每调用一次 on 就各自 off”
作为多消费者协议。当前只发现这一候选使用者，不为未实现消费者增加空框架。

## 5. MSA identity mapping：v115 已有证据并未被新参考推翻

复用并重新核对 `analysis/nabu-wlan-prerequisite-followup-v115.md:61`：

- 保存的 ath10k `snoc.c:1605` 的 ath10k_fw_init 首先查 wifi-firmware 子节点；
  不存在则 use_tz=true 并返回。只有存在该节点时才建立单独 firmware device/
  IOMMU domain，把 MSA PA 恒等映射到 fw_start_addr。
- 厂版 device.dtb ICNSS 下没有这个子节点，固定 MSA phandle 生效。
- vendor `icnss.c:2647` 的 icnss_smmu_init 创建 0xa0000000 IOVA 窗口、配置
  atomic/fast/stall-disable/non-fatal、attach ICNSS device，不映射 MSA。
- 该文件唯一直接 iommu_map 在 :2535 的 icnss_smmu_map，使用 IPA 窗口，
  不是固定 MSA 初始化。固定 MSA :3766 路径 memremap 物理保留区，随后由
  QMI 与 hyp assign 管理实际物理范围和安全所有权。
- Raphael icnss_smmu_prepare:5082 确有
  radio_enter(0x8bc00000,0x8bc00000,0x180000,RADIO_PTE)，这是明确的额外
  实现差异，但不能反推 Nabu 原机也要求该 host stream 映射。

被排除的是“从这两段参考代码即可认定 Nabu 缺少必需 MSA identity map”这个
推断；没有证明固件所有可能地址访问永远绕过 APPS SMMU。若后续拿到实际
MSA IOVA/SID fault 或新目标路径证据，应再作单独对照。当前 FW_READY 前
PFR 没有相应地址/stream fault 证据，保留现有 host DMA 映射更利于本轮归因。

本次产出是适用性边界与停止条件核对；没有新的 Nabu QDSS on/off 实机结果，
也没有新的 WLAN ready 或联网证据。
