# Build 5 实机结果

2026-11-14，CI 43586744462，源码 574a04a。设备仍为 jailbreak-02：i4-10 内核和 i4-12 启动包，没有重启或改写占用的持久化日志槽。

证据目录：`D:/github-IOS/XIAOMI_PAD5-NABU/log/host/jailbreak-20261114/setup-05/result-01/`。本次读取确认安装器 build 5，setup.json 自报 build 5。

## 已验证

- Sileo USTAR 包通过真实 dpkg 解包/配置；apt-get check 通过，原依赖未篡改。
- 原生 APFS 上的 setuid launcher 以 UID 501 启动 helper，helper 返回 UID 501/EUID 0。两个临时文件删除成功。
- 原 App 资源在安装后的实际 mode 为十进制420，即0644；IPA中的同一文件是0755。之前不能仅凭IPA权限解释EACCES，本轮已取得安装后权限证据。
- 键盘配置新增 Sileo、TrollStoreLite、TrollApps，含NUL为501字节，旧内核写入成功。
- 用户确认 Sileo 键盘能弹出并输入。syslog在18:50:00记录12次 `retain base layout height for {800, 0}`，证明Sileo实际触发了生产修正。TrollStoreLite/TrollApps仅完成配置，未有本轮输入反馈。
- 自有测试包安装、无注入基线、TweakLoader过滤、卸载和删除验证通过。

## 布局查询的实际限制

96项查询均返回正高度，但安装器看见的是768×1024点、1536×2048像素的兼容画布。没有一次派生setter调用，也没有0→-1转换；不能作为1600×2560的Nabu布局通过证据。需修正诊断应用的实际屏幕配置，不能为了测试而伪造UIScreen返回值。临时观测方法已恢复。

## 剩余插件故障

唯一失败步骤是 `tweak_hooked`，信号11。日志表明MSHookFunction已返回原函数跳板，但调用跳板的第10阶段崩溃：

- 原目标：0x100898000；原函数未hook时返回7。
- ElleKit：基址0x100a80000，MSHookFunction 0x100a86104。
- 返回的跳板：0x100914000。
- 故障PC、FAR、x16：0x10496007c；ESR：0x82000006。

NOP机器字为0xd503201f；若错误按B指令的imm26解码，其偏移0x040c807c加上原目标地址恰为故障地址。该数值对应是重定位错误的具体线索，实际库中的分支判定仍需核对。未启用通用tweak配置，测试包已清除。

## 本轮画面路径耗时

本轮采集的是安装/输入/故障日志，没有启用画面性能测点。

| 阶段 | 最小 | 最大 | 平均 | 原因、合理性、优化判断 |
| --- | --- | --- | --- | --- |
| 请求到UIKit提交 | 未测 | 未测 | 未测 | 无本轮测点，不能判断 |
| UIKit/CoreAnimation | 未测 | 未测 | 未测 | 无本轮测点，不能判断 |
| 合成/GPU执行 | 未测 | 未测 | 未测 | 无本轮测点，不能判断 |
| DPU接受 | 未测 | 未测 | 未测 | 无本轮测点，不能判断 |
| 面板扫描结束 | 未测 | 未测 | 未测 | 无面板完成测点，不能用DPU接受替代 |
