# 第十五轮显示接口分析与第十六轮刷新路径候选

日期：2026-11-04，Asia/Shanghai。

第十五轮照片已确认 SpringBoard PID 5、backboardd PID 8、runningboardd PID 4 实际运行。backboardd 报告 SpringBoard shell overlay，并调用 MiniIOMobileFramebuffer；读取 15,533 次无失败，正常定时返回。照片 SHA-256 `a854088b669eeee7613059ed9d9d138168c3a3ce699057810347a9476ca1bd0b`。恢复 Android 后 GPT／14 个受检引导分区核验一致。仍没有实际桌面或首帧呈现证据。

## 排除直接误读

`HighPriorityIO` 未识别的 plist 键没有阻止上述任务启动。SpringBoard 的 wakeups 警告在没有 `FATAL` 位时不会由该超限函数主动终止任务；当前内核对应 384 字节函数已与冻结镜像匹配，SHA-256 `a21e77f9caa6041d7135785c87b0619f6e07a777f3b05231b2523d7c9de1640d`。该构建未包含此函数中的 EXC_RESOURCE 异常投递分支，但资源服务收到通知后的额外行为未观测。没有因此禁用 monitor 或提高阈值。

原版 20F66 共享缓存的 image 表、nlist 和独立 local-symbols 文件定位到：

| 接口 | 原版函数／地址 | 实际参数形式 |
|---|---|---|
| selector 50 | `_kern_SetBrightnessCorrection`，`0x1af12db78` | 两个 scalar，零输出 |
| selector 84 | `_kern_SetContrast`，`0x1af131854` | 4 字节结构输入，零输出 |

Mini framebuffer 的未知 selector 分支实际返回成功，故这里是设置被忽略，不是客户端收到 unsupported。目前没有证据说明这两项造成不绘制，未把空实现改成另一个仅返回成功的空实现。

## 有界原版代码证据

从已校验的缓存映射按原 VM 地址读取 IOMobileFramebuffer／QuartzCore 的文本和符号。LLVM 分析使用只包含相同原始 text 字节的派生 ELF 容器，不是重构可执行 dylib；输入缓存哈希、映射、符号和派生文件范围保存在 `log/host/display-v16/`。当前 Windows REA provider 对此类 ARM64 Mach-O 的深度分析不支持，沿用先前确认的 LLVM 离线方式，不声称取得 REA 反编译结果。

原版 `CADeviceUseVBL` block 位于 `0x1882e4614..0x1882e4698`，代码 SHA-256 `5ceaed6804e309acfb63a6b07bdb2f77e8768a550e52f876406c08dc6a59650c`。它读取 `CA_FORCE_TIMER`；值为非零时选择 VBL 路径，否则查询芯片标识并与原版列表匹配。四个原始机器码仿真场景覆盖环境开关 1／0、未知芯片及 0x8010；getenv、atoi、芯片查询为明确的模拟边界。该测试证明分支选择，不证明真机当前芯片查询返回值或刷新信号已经工作。

## 第十六轮候选

仅向 `com.apple.backboardd` 的启动环境增加 `CA_FORCE_TIMER="1"`，验证 CoreAnimation 使用已有 Mini framebuffer 的刷新通知路径。没有加载带私有地址的 HakiOS 注入库，也没有改动原版系统卷或内核代码。APFS 包内 402 个普通文件对比中，只有 backboardd plist 内容改变；除这个新增环境键，原 plist 的全部字段保持一致。stage0／init 逐字节不变，仍来自 Actions `41787286981`。

同时使用现有内核的 `ustacks=backboardd ustacks_at=90 ustacks_count=1 ustacks_threads=4 ustacks_tname=coreanimation`：启动约 90 秒时采样一次至多四个名称包含 coreanimation 的线程。返回报告在有样本时用 `RENDER THREAD STACKS` 取代 runningboardd 分组。运行中的线程 PC 是最近进入内核的位置，不能当作精确瞬时 PC；这里只显示样本的首尾行，也不是完整线程转储。没有样本不等于进程未运行。

`artifacts/nabu-bootstrap-v4/bootstrap.apfs` 为 8 MiB，SHA-256 `57d20658fc2db75e809d4314d31e1722ba2501e21dff2c6354a1e0572c51970a`；两个 APFS 容器检查、包内程序和 plist 回读均通过。新版 6080 字节回调 blob 的 SHA-256 为 `a999d1652a44eb2dfb5d221154be1c54557df8465057d0b0949b0ae94e726ba8`，通过 12 个仿真场景和 12 个 binder 场景。新 DarwinBoot.efi 为 35,840 bytes，SHA-256 `929ba7f8ab96f5e1a7b893707b9be4022d46d05c7b9e0b73ed44d962570d6d18`；内嵌报告与测试字节一致，ABI／handoff 检查通过。内核、UniXNU 和 boot.img 沿用第十五轮，120 秒观察窗口保留。实际刷新与桌面效果待设备验证。

第十六轮已于 2026-11-04 16:12:13 完成 ESP 六文件部署与哈希回读，收据为 `log/device/nabu-chain-20261104-161213/deployment.json`；16:15:23 执行 `fastboot boot`，发送与 Booting 成功（Asia/Shanghai）。源提交 `05884914919814966f5a3321db03629d9e4bbbca`，启动前 30 份 GPT 元数据和 14 个受检引导分区完成核验。374 份冻结输入／检查文件及 boot.img、run.json 保存于 `log/device/nabu-boot-20261104-16/`。等待约两分钟后的完整屏幕；如果期间出现桌面先保存照片。返回画面重点为 `RENDER THREAD STACKS` 和 `DISPLAY / SURFACES`；照片保存后恢复 Android，再对同一运行目录执行 `--collect`。
