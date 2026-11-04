# 桌面服务观测

日期：2026-11-04，Asia/Shanghai。

第十四轮照片确认用户态持续运行到 `lsd[22]`，读取 15,502 次、失败 0 次，八个 CPU 的 timer／SGI 计数均增长。定时回调在 CPU 4 报告 `mode=normal-return`，屏幕 TIMER MARKER 为 YES；这是设定的观察窗口结束，不能仅因返回画面而称作内核崩溃。照片 SHA-256 `2e987857928e5559bb44e1247a138e243640c58c5305cff224ea974734f106c4`。返回 Android 后 30 份 GPT 元数据与 14 个受检引导分区哈希一致。

照片中的 `programs 194` 是内存统计量，不是进程数量。`0 surfaces` 是该时刻的统计信息；目前没有 SpringBoard／backboardd 就绪或实际桌面证据。反复出现的 `lsd ... denied attempt to escape CPU monitor` 表示缺少请求放宽监控所需的 entitlement，不足以证明它导致桌面停滞，因此未据此修改权限策略。

## 已核对的启动项

直接从 `artifacts/nabu-bootstrap-v3/NabuInit.apfs` 读取四个 plist，均与组装目录逐字节相同。SpringBoard、backboardd、runningboardd 都保留 `RunAtLoad=true`、`KeepAlive=true`，无 Disabled；普通 lsd 按 Mach 服务请求启动。三者均由 `jobs.json` 显式选中，`mkjobs.py` 没有将它们当作其余按需任务而移除启动触发。

SpringBoard 保留 diagnostics 排除条件和 Clarity 模式排除条件；冻结第十四轮 ADT 的 `osenvironment` 是 `main`，不匹配 diagnostics 排除条件。Clarity 运行时状态仍未知，不能将与 checkerboard／ClarityBoard 的同名 Mach 服务静态定义直接当成服务冲突。收据为 `log/host/desktop-v15/jobs-audit.json`。

## 第十五轮观测改动

内核最多保留 1.5 MiB 日志，而旧返回画面只渲染最后 64 KiB 中的最后 40 行，早期桌面错误可能被无关重复消息覆盖。新版回调在正常返回且出现 phase 7、没有 panic 标记时，对完整的已验证日志范围提取：

- SpringBoard、backboardd、runningboardd 各自的首条及最后两条匹配行；
- MiniIOMobileFramebuffer／MiniIOSurface 的首条及最后两条匹配行；
- dyld／依赖缺失／退出原因的首条及最后两条匹配行；
- 最后一次用户态阶段和存储读取汇总。

每条最多两行，超长部分以 `>` 标记截断。无匹配只显示 `NO MATCH IN CAPTURED LOG`，不声称进程未运行。异常、panic 和尚未到 phase 7 的情况继续使用原日志尾部报告。这仍是屏幕日志摘要，没有读取实时进程表、证明服务就绪或实现日志持久化。

5848 字节报告 blob（SHA-256 `1ca8232dc2a0c124d2a02a71627e4868024d43cbe8a79395fb3aee2b633753dc`）通过 11 个真实机器码仿真场景：旧异常／范围检查、超过 64 KiB 的早期服务消息、无匹配、不完整标记和长行截断；验证了日志读边界、framebuffer 保护区及预期文字像素。12 个实际 binder 的 ASan／UBSan 场景也通过。

本地 WSL／LLVM 18 已完整构建新 DarwinBoot.efi，为 35,840 bytes，SHA-256 `8e4ce35618a784b0853e31ceadcb4e43f1c03aa68442c7eeedbf8a08f49f8601`，内嵌 blob 与仿真版本逐字节一致。ABI 和 ADT／handoff 检查通过。UniXNU.efi 使用第十四轮的确切字节；内核、RAM 包、boot.img 和启动参数也保持第十四轮版本。实际报告和桌面状态待第十五轮照片确认。
