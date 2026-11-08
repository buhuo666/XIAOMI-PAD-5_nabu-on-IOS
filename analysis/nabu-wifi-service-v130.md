# 第130轮候选：原版wifid与原生接口发现

日期：2026-11-08，Asia/Shanghai。第129轮已证明真实ath10k被动扫描及蓝牙恢复，
但WirelessInventory显示wifid job与en0均不存在。此候选补齐原生服务发现边界，
保留已有被动扫描和蓝牙验证；尚未连接原生station控制。

## 实现

- `userland/nabu/jobs.json`通过source_job_allow恢复原版com.apple.wifid。
  `_LimitLoadToDeviceTree`、七个MachServices及其他原件条件保持，仅stderr送console。
- 新增`update_nabu_wifi_bootstrap.py`，明确指定baseline镜像和目录，基于已验证v114
  目录仅添加wifid job，重建NabuInit并运行apfsck，Boot/App从该baseline复制。
- `--wlan-native-service`显式增加真实wlan ADT节点，MAC来自本板原地址，寄存器
  0x18800000+0x800000，compatible=qcom,wcn3990-wifi。
- `NabuWlanService.cpp`在无线调查线程开始时调用已有hakios_net_attach，发布一次
  en0/IO80211Controller/HakiosWLAN；不定义重复IOKit类。link保持down，TX明确拒绝。
- `nabu-wifi-control-state.patch`修正基核的Apple80211查询：没有station时POWER=off，
  不宣称加密能力，设备名称不再写成WCN6750/ath11k。其他未接入控制继续返回真实错误。

当前ath10k仍执行独立的真实被动扫描并停止扫描接口。没有把它当成可供wifid调用的
station，也不把存在的en0当成已关联网络。下一轮须从原版服务的实际IOCTL与退出原因
判断发现路径，再接入持续station控制、扫描、关联、密钥与TX/RX。

## 构建与验收

本地真实查询代码回放、接口发布代码、ADT编码通过ASan/UBSan；arm64模块编译通过。
v130 bootstrap基于v114已生成并通过apfsck。完整内核CI和实机结果待补充。

本轮修改的是基核内的控制函数，部署必须使用包含该patch的新完整内核，再重新执行
原版APFS/USB/FairPlay预链接和外部模块链接。不得继续以v79/v128预链接基核部署，
否则仅更新模块不会修复POWER查询。ath10k后端源码未改，沿用第128轮已验证合并对象。

实机分别记录：桌面/USB、wifid job和进程、实际IOKit父子关系、BSD en0、POWER与
控制请求errno、真实ath10k扫描结果，以及蓝牙Reset/lifecycle/系统栈结果。
设置按钮的外观只作为用户反馈，不单独证明Wi-Fi可用。
