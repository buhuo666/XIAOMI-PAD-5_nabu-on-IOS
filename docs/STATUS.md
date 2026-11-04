# 项目进展

更新：2026-11-04，Asia/Shanghai。

目标：小米平板 5（nabu），XNU 开源基线 8796.121.2，iPadOS 16.5／20F66，普通 arm64。

最新主线结果：第十二轮照片确认源构建 init 到达 phase 5（SystemOS 挂载完成），存储读取 121 次、失败 0 次，随后进入停机路径；尚未到达 launchd exec 阶段。返回 Android 后 30 份 GPT 元数据和 14 个受检引导分区哈希一致。主机复现了一个确定错误：20F66 iPad 镜像缺少 NanoLaunchDaemons，原复合绑定因此失败并跳过后续绑定。第十三轮改为独立绑定及可选目录检测，并保留首个 PID1 初始化失败到屏幕返回报告；macOS Actions `41784700433` 全部通过，产物／源码／APFS 回读均已核对。2026-11-04 14:27:35（Asia/Shanghai）执行第十三轮临时启动，发送和 Booting 成功，343 份冻结证据位于 `log/device/nabu-boot-20261104-13/`；正在等待屏幕结果，尚未确认 launchd 或桌面。详见 [用户态初始化](../userland/nabu/README.md)。

当前优先级（用户于 2026-11-04 调整）：先推进进入 iPadOS 桌面，暂缓主动 panic 日志和调用记录的细节。第九轮确认早晚参数一致、CPU 7 执行 requested-panic 回调、八核 signal 计数增长；缺少 panic 正文与混合结果行的状态保存在 [暂缓问题快照](DEFERRED-PANIC-DIAGNOSTICS.md)。本轮已恢复 Android，GPT 和 14 个受检引导分区回读一致。

桌面主线进展：原生只读 UFS、固定 OS／SystemOS 窗口、BSD 根选择及挂载后读取 launchd 的候选已由 macOS Actions `41772094078` 全部验收。设备端元数据只读复核一致；准备第十轮实机测试，尚未确认 XNU 挂载成功。用户要求跳过首次设置／激活引导，偏好种子已准备但尚未部署。详见 [存储接入](NABU-STORAGE-BRINGUP.md) 与 [用户态初始化策略](../userland/nabu/README.md)。

第十轮于 2026-11-04 12:25:43（Asia/Shanghai）执行 `fastboot boot`，发送与 Booting 成功。`log/device/nabu-boot-20261104-10/` 保留确切候选和验收证据；屏幕存储报告及恢复 Android 后回读待收集。此轮是 OS 挂载／完整 launchd 文件读取探针，不能作为桌面已经启动的证据。

第十轮后续证据：已执行到 BSD 根选择和 UFS 初始化，在 SMMU 规划阶段发现固件已有 stream `0x300` → bank 1 映射而拒绝接管，命令计数为 0；尚未读取系统卷。恢复 Android 后 GPT／14 个受检引导分区回读一致。下一候选增加仅针对精确 UFS stream、保留原 bank 和其他 stream 的有界路由接管，主机模拟已通过，等待 macOS 构建与后续实机验证。详见存储接入记录。

第十一轮候选：SMMU 固件路由接管修正已由 macOS Actions `41774440467` 全部通过，产物及生成源码哈希已核对，准备继续只读系统盘探针。日志回收工具已增加 pstore 文件保存；当前 XNU 运行期日志仍未持久化，不能以 ESP 交接日志替代。首轮存储挂载和 launchd 校验仍待实机确认。

第十一轮于 2026-11-04 12:46:22（Asia/Shanghai）执行 `fastboot boot`，发送与 Booting 成功；证据冻结在 `log/device/nabu-boot-20261104-11/`。修正的实机结果尚未确认，下一输入应为存储报告画面，之后回收 Android 下可取得的证据。

用户已将下一阶段定为八核启动与扩容内存调查，不再把单核作为独立里程碑。新增补丁和主机验证见 [八核与内存实验](SMP-MEMORY-EXPERIMENT.md)。

最新实机结果：第七轮照片显示 `GenericARMPE: 8 of 8 processors are running`，CPU 3–7 逐个 online／initCPU，以及 MiniIOMobileFramebuffer 初始化。返回报告 REASON=0、CODE=0，日志长度 `0x4B86`（19,334 bytes）。这已提供副核执行和八核计数的板上证据，但尚无各核 SGI／timer 增长、跨核调度或 TLB 验收结果。照片末尾没有可见的定时器到期／panic 标记，返回原因仍未单独确认。返回 Android 后 30 份 GPT 元数据和 14 个受检引导分区哈希一致。

v7 的 3016 字节回调 blob 已通过 8 个仿真场景，覆盖有效／长日志、越界／溢出长度及无效显示参数；实际 binder 通过 12 个 ASan／UBSan 场景。第七轮冻结记录、照片及回读结果位于 `log/device/nabu-boot-20261104-07/`。第八轮候选加入 `return_cpu=7 return_panic=1`，利用已有定时回调在目标 CPU 主动生成带 CPU 编号的 panic 诊断；新版屏幕单列日志内的返回标记。`loader_return_after=30` 仍依赖初始化与定时任务能够运行，不能保证卡死时自动返回，也不表示自动恢复 Android。

用户再次确认设备物理配置为 12 GB 扩容 RAM。当前约 7.89 GiB 是 loader 在现有固件内存图中整段分配并交给 XNU 的连续窗口，不能当作整机容量；后续目标仍是核对并利用所有可安全管理的 RAM，区分物理容量、固定与固件动态预留、loader 所有权和 XNU 实际管理量。

第九轮已于 2026-11-04 11:22:09（Asia/Shanghai）执行，`fastboot boot` 的发送与 Booting 均成功。启动链采用 macOS Actions 验收的新内核，部署 SHA-256 回读一致；完整冻结证据位于 `log/device/nabu-boot-20261104-09/`。新诊断屏幕与恢复 Android 后回读待收集。

第八轮照片确认定时返回标记出现，但未见请求的 CPU 7 panic 或 panic buffer 标记；该目标诊断尚未通过。交接日志包含完整参数，实际内核指令也保留对应解析／调用分支，主机仿真可正确解析该输入。返回 Android 后 GPT 与 14 个受检引导分区一致。加入早晚参数、调用结果与每核计数观测的新内核已由 macOS Actions `41765915458` 完整构建及原生校验通过；下载产物哈希、6 个范围的 1,499 条指令已对照待启动内核。第九轮候选沿用 v8 EFI 和原 boot.img，以新内核继续定位。详见 [定时返回诊断](RETURN-DIAGNOSTIC.md)。

2026-11-04 本地启动链更新：WSL Ubuntu 22.04、LLVM 18.1.8、Python 3.12.16 已成功构建 nabu DEBUG／NoSb 固件和两个 EFI 程序。临时 `boot.img` 为 3,616,768 bytes，SHA-256 `bca20de2c74522394c1b0005ca82ae5b03daeefb22a2f1cb7b221a40eecf1adc`，独立解包校验通过。5 个启动文件已写入现有 ESP，SHA-256 回读通过。首次实机启动到达 DarwinBoot 的退出 Boot Services 前交接阶段，EL1、19.2 MHz counter、1600×2560 framebuffer，成功分配 7.88671875 GiB 连续内存。返回 Android 后六个 LUN 的 GPT 元数据及所检查的引导分区 SHA-256 均与启动前一致，槽位仍为 A。首次记录本身未证明内核执行；后续通过三色条与内核回调继续定位，最新结果见上文及 [启动入口](NABU-BOOT-ENTRY.md)。

2026-11-04 接手验收：提交 `f77e851c0e7d153cd9bf23b39f04fcccabbc78f4` 的内核 Actions `41671552454` 和 EFI Actions `41671552536` 均成功。已下载并逐个核对两个内核、UniXNU.efi 和 DarwinBoot.efi 的大小、SHA-256 与架构；完整内核 `build_exit_code=0`，构建日志没有缺失导出或编译错误。内核仍为参考配置，实机验证进展见上文。

用户进一步明确：允许在已有 64 GiB 区域重新初始化并写入 iPadOS，要求系统状态持久保存；启动仍只使用 `fastboot boot`。系统材料已经全部传入设备并核验哈希。磁盘布局与写入验收以 [设备安装记录](DEVICE-INSTALLATION-20F66.md) 为准；不能将传输、APFS 初始化或编译成功当成持久化功能已通过。

第二轮实机更新：用户观察到 `P3: EBS OK - ENTERING STUB` 和由上到下绿、蓝、橙三条色带，确认 loader 已走到关闭 MMU／cache 后的分支前标记。返回 Android 后，30 份 GPT 元数据和 14 个受检引导分区哈希均一致。已有内核的 `XNULDRST` 接口允许捕获早期异常或在检查点 5（启用 MMU 后）主动停下；新 EFI 的屏幕报告代码已在本地构建并通过主机验证，准备继续实机确认内核执行。

## 已完成

- 建立独立工作目录和 Git 工程，下载 23 个固定提交的源码仓库；清单在 `configs/sources.lock.json`。另记录 21 条 UniXNU gitlink 与 19 个图形补丁的哈希，见 `docs/SOURCE-BASELINE.md`。
- 经已授权 root ADB 读取设备信息。设备报告 nabu／SM8150，当前 Android 15，活动槽位 A，bootloader unlocked。
- 保存六个 UFS LUN 的主备 GPT，校验头部和分区数组 CRC，并确认主备一致。原始备份保存在本地 `backup/gpt`。
- 确认旧项目区域为 `nabu_esp` 4 GiB + `nabu_system` 60 GiB，共 64 GiB；用户已授权回收。2026-11-04 保留 GPT 边界，在系统区写入 20F66 OS／SystemOS 和空 49 GiB APFS Data，完整回读哈希通过，详见设备安装记录。
- 从 Apple CDN 的 20F66 IPSW 提取 KernelCache、DeviceTree、StaticTrustCache，记录 ZIP CRC 和文件 SHA-256。
- 编译 Apple LZFSE 解码器，取得原版 arm64 内核与 229 条 prelink 组件记录。
- HakiOS 8796 补丁在固定 Apple 8796.121.2 源码上通过 `git apply --check`。
- 完成 FDT 与 Linux 内存资源交叉核对：扣除固定 no-map 预留后，两者逐字节一致。高地址连续 11 GiB 尚未选作 XNU 管理窗口，见 `docs/DEVICE-MEMORY.md`。
- 保存本机七个 Adreno 固件文件，设备端与主机 SHA-256 一致，四个必需文件匹配 nabu 参考记录。
- 首轮 macOS／Xcode 16.4 的 GitHub Actions 参考内核构建取得两个 arm64 Mach-O，完整构建因 131 个缺失导出符号失败；见 `docs/FIRST-BUILD.md`。
- 计算原版 20F66 的三阶段声明依赖闭包：23／36／37 项，记录与 HakiOS Mini 服务的归属冲突，见 `docs/KEXT-COMPOSITION.md`。
- 完成 5,602,053,020 bytes IPSW 的完整 ZIP CRC 和 SHA-256 校验，提取 OS、Cryptex SystemOS 与对应 trust cache。
- 还原 3 个 ZBM 压缩文件，保存 50 个用户态分析文件。44 个缓存文件齐全，2,619 个镜像头为普通 arm64；47 个代码文件的原始 CodeDirectory 分块哈希和 trust-cache 成员关系通过检查。见 `docs/USERLAND-20F66.md`。
- 完成 131 个缺失导出的逐项归因：94 个 DriverKit 生成层、17 个 UAT、18 个 Apple 平台接口、2 个缺 ARM 实现的 pmap 查询。见 `docs/EXPORTS-8796.md`。
- 从原版 kext 显式 KASLR 指针表定位到 8 个 GOT 引用位置、5 个参考内核缺项：基础存储涉及 3 个，显示触摸再增加 2 个。此检查不覆盖完整指令重定位及 ABI；见 `docs/KEXT-INTERFACES-20F66.md`。
- 新 Actions `41646722684` 实测找到了 Xcode 16.4 的真实 IIG（DriverKit-427.100.5），17 份实现文件均已生成。默认生成代码引用旧版 IORPC 没有的 `kernelContent`，导致编译失败，未产生新内核。
- Actions `41648024252` 完成 8 组 IIG deployment-target 测量，生成文件全部相同。随后 `41649343964` 的消息布局兼容层编译通过全部 17 份实现，生成两个新内核，94 个生成层缺项全部消失；剩余 37 项仍使完整构建失败。下载后的产物哈希、34 份生成记录和变换输出已复核；见 `docs/IIG-COMPATIBILITY.md`。
- 新内核与原版同名外部定义从 5,731 增至 5,825；原版独有从 137 降至 43。选定原版 kext 的显式指针复测中，三阶段均为 0 个缺同名候选、0 个地址歧义；尚不代表重定位和 ABI 兼容。
- 完成 29 个原版 kext 的有限 B/BL 与标准 stub 检查：17 处 BL 经 8 个 GOT 连接上述 5 个接口；独立 LLVM 核对全部 99,926 个编码候选及关键 stub 的地址计算。35 个常量编码单列、2 个 Libm 位置仍未决，见 `docs/KEXT-BRANCHES-20F66.md`。
- 已将 Windows 当前 provider 不支持的 ARM64 原生分析转至 macOS Actions。`41657999493` 验证了三个 IIG 空 reply 错误分支和共享 pmap 配置；`41659076371` 再加入 11 个仅限 BCM2837 参考配置的查询汇编入口，逐项与原版字节相同。原生分析成功，完整构建仍因 24 个缺失导出失败，见 `docs/NATIVE-ANALYSIS-20F66.md`。
- 最新候选与原版共有 5,838 个同名外部定义，原版独有 30 个（24 个构建导出缺项 + 6 个额外接口）。存储／显示触摸／GPU 三阶段显式指针复测均为 0 个缺同名目标、0 个歧义。全量 211 个原版 kext 检查中，剩余差集有 7 个符号连接 7 个 GOT、17 条分支，消费者均在当前闭包之外；其余 23 个符号仅能称本次覆盖形式未命中。见 `docs/PLATFORM-CONSUMERS-20F66.md`。
- 用户提供的弃用项目内核已独立解包并核对清单，从匹配哈希的历史补丁链恢复 85 个硬件相关文件。包内目标 16.6.1／20G81 仅为线索，不能确认用户记忆中的系统；旧代码不进入当前构建，也不作为硬件正确性证据。触摸问题的排查线索见 `docs/ABANDONED-KERNEL-REFERENCE.md`。
- 完成八核参考审计与本机定时器 INTID 19 核对，新增逐核 SGI／timer 调试记录、32 页有界早期页表和 8796 专用 loader ABI。Actions `41666598049` 生成两个新内核，原生接口和 SMP／容量检查成功；完整构建仍因相同的 24 个导出缺项失败。下载哈希、1,088 条原生指令和本机 38 位根表配置的补充测试均已核对。见 `docs/SMP-MEMORY-EXPERIMENT.md` 与 `docs/NABU-MEMORY-CAPACITY.md`。

## 固件实测结果

| 项目 | 结果 |
|---|---|
| 产品／build | iPad7,11／j171ap，16.5／20F66 |
| Mach-O 架构 | CPU type `0x100000c`，subtype `0`，普通 arm64 |
| 原版内核版本 | Darwin 22.5.0，`xnu-8796.122.4~1/RELEASE_ARM64_T8010` |
| 原版内核 UUID | `45734ead-3ab7-330d-bacf-9c48ef9a9358` |
| arm64 slice SHA-256 | `600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2` |
| APFS | 2142.122.2 |
| IOSurface | 336.50.1 |
| IOGPUFamily | 65.40.15 |
| IOHIDFamily | 2.0.0 |

开源内核继续使用选定的 `8796.121.2`。原版固件实际为 `8796.122.4~1`，这项差异需要通过接口分析处理，不能按同系列版本直接判定兼容。

格式与版本结论来自本地解包和 Mach-O／OSUnserialize 解析。REA 确认了 thin Mach-O 格式；Windows 当前原生分析 provider 不支持该 ARM64 Mach-O，后续已使用 macOS Actions 的原生 LLDB 取得反汇编。最新记录核对了原版 47 个代码范围和候选 21 个代码范围；没有运行内核，也没有取得完整反编译或 ABI 等价证明。

## 正在推进

1. 当前选定组件合同已将 17 个 UAT 类符号与 7 个 IOMMU 操作从非 Apple 构建清单排除，两遍原生导出检查均成功。扩大组件闭包之前仍需补齐这些操作的真实契约，不能将排除导出理解为实现了接口。
2. 扩展 IIG 回调、类布局、生命周期、原版组件重定位和初始化入口的证据。已有消息常量与有限分支检查不能替代这些工作。
3. 按服务归属建立 nabu 八核配置，使用已核实的 affinity、PSCI SMC、虚拟定时器 INTID 19；逐核核验启动、SGI、timer 和调度。旧项目仅提供待查方向。
4. 在已通过主机／编译检查的 32 页早期页表、8796 loader ABI 和最大 12 GiB 解析能力之上，取得最终 UEFI 所有权后再选择实际窗口。补齐 nabu ADT、CPU／UFS 和内存交接，实现实际板级构建。
5. 将已选择的 OS／SystemOS／磁盘 Data 窗口接入 20F66 存储 ABI、nabu UFS 有界写入及 `/private/var` 挂载。参考 nabu 补丁当前禁用 UFS 写入，不能直接使用其 RAM Data 路径实现用户要求的状态保存。

当前启动链已接通只读原生 UFS、OS／SystemOS 挂载和静态 RAM bootstrap；磁盘 Data 挂载、状态持久化与桌面仍未完成，不能称为可用 iPadOS 系统。设备写入包括另文记录的 `nabu_system` 安装和 ESP 文件部署，启动只允许 `fastboot boot`，不得修改 GPT、Android 引导分区或活动槽。
