# nabu 原生只读系统盘与挂载探针

更新：2026-11-04。当前目标是让已运行的 8796 内核读取 `nabu_system`，挂载 OS，并读取完整 `/sbin/launchd`。这一步还不执行 launchd，不代表进入桌面。

用户态目标补充：按用户要求跳过首次设置／激活引导，直接进入 SpringBoard。后续 Data 种子与启动项策略见 [`userland/nabu/README.md`](../userland/nabu/README.md)，该配置当前尚未部署。

## 路线与范围

当前 HakiOS `ufs_shared_pa` 存储入口依赖另一个核心上的驻留 UEFI 服务，与当前八核、ExitBootServices 启动方式不相容。本次复用固定 ShengUfs 提交 `af785c1777161a62931425c2faaa536ce0bebd5b` 的命令、队列、SMMU 与 GPT/SHNGROOT 解析代码，并应用 nabu 固定板级补丁。参考源码保持不变，在生成树中提取原生只读传输层。

底层接入当前 8796 内核的 BSD block-device 接口，继续使用已经编入的 HakiOS APFS 读取实现。当前阶段没有引入 21H16 的 IOStorageFamily 地址或私有类布局，也没有同时注册第二套 APFS 服务。后续执行 20F66 用户态所需的服务、缓存、Data 与签名策略仍需分别验证。

控制器为本机 `0x01D84000`，SMMU 为 `0x15000000`、UFS stream `0x300`，逻辑块为 4096 bytes。启动时先检查 GCC 电源／时钟状态，拒绝尚有 UFS 请求的固件队列，再建立有界 DMA 与专用 stream 路由；不重置 PHY，不写 GCC。遇到超时或协议异常就隔离传输，保留 DMA 分配直到本次停机，不继续重试使用不明所有权的缓冲区。

## 磁盘边界与验收

- 从 LUN0 的 GPT 查找唯一的 `nabu_system`，核对 GPT CRC、分区边界与互不重叠，目标大小固定为 60 GiB。
- 验证已有 SHNGROOT 元数据哈希，OS／SystemOS 的名称、偏移、大小和记录的镜像哈希必须与 `configs/nabu-storage-probe.json` 一致。
- 两个 APFS 首块均须匹配已安装来源的 SHA-256、NXSB 标记及容器大小，之后才发布 `nabu_os`、`nabu_systemos` 两个只读块设备。
- 所有读取按窗口相对字节偏移验证，正确处理 512/4096-byte 单位、末尾短读和整数溢出。写打开、写 strategy 和设备可写查询均明确拒绝；传输生成代码不含 WRITE(10) 或 Data 写入接口。
- `nabu-root-probe=1` 在实际 `vfs_mountroot` 与 `VFS_ROOT` 成功后读取完整 `/sbin/launchd`。期望大小 525,088 bytes，SHA-256 `4c61512d19b9a55a6ddad27e23b88fc5008fbf77d0c0b5e6bdd7c7d90cef3e06`。
- 探针在根认证／用户态执行之前主动结束并显示存储结果。因此即使成功，也只能确认 OS 挂载与该文件读取；不能宣称根认证、Data 持久化、SystemOS 挂载或用户态已通过。

保留已安装的 OS／SystemOS／49 GiB Data 内容；本次代码没有格式化、GPT 修改或磁盘写入路径。启动仍使用 `fastboot boot`。

## 代码与检查

`tools/prepare_nabu_storage.py` 在生成的 XNU 树中装配驱动、固定窗口合同、BSD 根选择及挂载后探针，并记录来源提交和生成文件摘要。`patches/nabu-storage/` 保存本项目接口、范围策略和 BSD／传输胶合代码。

`tools/check_nabu_storage.py` 对实际生成的队列、命令、SMMU、GPT/manifest 和字节范围策略执行 ASan/UBSan 检查，覆盖错误 DMA 响应、超时隔离、写方向拒绝、LUN 容量限界及 2048 个元数据变异输入。MMIO/DMA 由主机测试替代，不是硬件证据。macOS Actions 完整编译后，再由原生 LLDB 对关键入口解码并记录指令哈希。

macOS Actions `41772094078`（提交 `9b7b0b5f888642a57ed8e61ffbc7245533500928`）已全部成功：完整内核构建退出 0，5 组存储主机检查、导出合同、原生接口、SMP／页表及原生存储检查通过。主机测试覆盖了上述 2048 个变异输入，实际板上行为仍待验证。

| 内核 | bytes | SHA-256 |
|---|---:|---|
| `mach.development.bcm2837` | 17,125,696 | `fc3151a3b255f2e4942e88f649e03199765c125cfc722f396724dc02fce8b2be` |
| `mach.development.bcm2837.unstripped` | 22,928,016 | `a0a1aca234ee85c0ca8d1658e85463415b7aa0881a379eaddeb14c560c3c3fbc` |

下载后核对内核、项目补丁和存储合同哈希，并将 5 个存储入口范围的 1,548 条 LLDB 指令与实际 stripped 启动内核逐字节对照；另有 6 个返回路径范围的 1,500 条指令一致。验收记录为 `log/host/nabu-storage/ci-verification.json`。

Android 下的只读预检 `log/device/nabu-storage-preflight/report.json` 确认设备仍为同一台 nabu、目标仍为 60 GiB 的 `sda36`，已安装 SHNGROOT 元数据哈希和两个 APFS 首块哈希均与配置一致。这属于 ADB 读取证据，不算 XNU 原生存储测试。

第十轮候选沿用 v8 EFI 与原临时 boot.img，启用 `nabu-storage=1 nabu-root-probe=1`。检查点仍为 0，未启用主动 panic 或定时返回。成功或明确失败时直接显示存储报告；挂载成功后探针会有意停止，尚不执行用户态。

2026-11-04 12:24:32（Asia/Shanghai）完成 ESP 五个文件部署与哈希回读，收据 `log/device/nabu-chain-20261104-122432/deployment.json`。12:25:43 执行第十次临时启动，发送与 Booting 均为 OKAY，源提交 `5852715f1b0f26c273447a2b4ea64dcced5a189a`。运行目录 `log/device/nabu-boot-20261104-10/` 已冻结启动链、macOS 检查、生成存储源码、合同和 Android 只读预检。当前仅确认命令成功；原生读取、挂载及 launchd 校验结果等待屏幕证据，恢复 Android 后还需回读分区哈希。

## 第十轮结果与 SMMU 接管调整

用户照片已确认到达 BSD `setconf` 和原生存储初始化。控制器 CAP=`0x1587031f`、VER=`0x300`、HCS=`0x10f`、HCE=1，DMA=`0x183524000`、连续长度 `0x22000`。在 `SMMU planning` 阶段返回 `0xe00002d8`：已有 slot 2 的 SMR=`0x80000300`、S2CR=`0x1`，即精确 UFS stream 被固件路由到 context bank 1。原策略仅复用自己选择的高位 bypass bank，因此拒绝该现有路由。命令计数为 0，尚未发出 NOP／SCSI／GPT 读取，不能称作文件系统错误。

照片及 `screen-observation.json` 保存在第十轮运行目录，照片 SHA-256 `c531cd9eba52a86f0b81c94a800844681161f827658c4839d50e0745def33099`。未走到采样点的字段保留默认值，不能把它们解释成真实寄存器读数。恢复 Android 后 30 份 GPT 元数据和 14 个受检引导分区哈希一致。

`smmu-firmware-route.patch` 增加显式、默认关闭的固件路由接管选项，只有本机原生 UFS 在证明队列停止后启用。只接受唯一、无 mask、属性已知的精确 stream；选择未被其他 stream 引用且未启用翻译的 context bank，完整检查最多 128 个硬件 stream 槽，超过可完整检查范围则拒绝。配置前再次检查旧路由、目标 bank 与其他 stream 的归属是否变化。先设置并回读新 context，最后只改该 UFS slot 的 S2CR；不改旧 context-bank 寄存器、不改其他 stream，也不重写已有 SMR。

新主机测试使用照片中的 IDR1／IDR2、SID、slot 与 S2CR，IDR0 是明确标注的合成值。验证旧 bank 被其他设备共享时仍保持原状，目标被占用时改选空 bank，并覆盖重叠／mask、未知属性、过期计划和写入被硬件拒绝的情况。原有严格模式测试保持通过。以上是实际生成策略的模拟检查，接管效果仍需实机验证。

修正候选已由 macOS Actions `41774440467`、提交 `721e8250395294bceec245cdc63d674e3bc7d383` 完整编译并通过全部检查，包括新旧 SMMU 测试。下载后的 generated headers／transport 与本地规范化源码哈希一致，5 个存储入口范围的 1,555 条原生指令及 6 个返回范围的 1,500 条指令与 stripped 内核一致。启动内核为 17,125,752 bytes，SHA-256 `d3a382e33c44f43836170c5a8278ab501ef55d619ea472bb81dd6a4d53a8e2fc`；未剥离内核为 22,928,120 bytes，SHA-256 `2661c39336efdd456c087c1c36785d7588f43ce4237e79df9523c119ad43bbe8`。收据为 `log/host/nabu-storage/ci-verification-retarget.json`，第十一轮拟使用此候选继续同一只读挂载探针。

2026-11-04 12:45:38（Asia/Shanghai）完成第十一轮 ESP 文件部署及 SHA-256 回读，收据 `log/device/nabu-chain-20261104-124538/deployment.json`。12:46:22 执行临时 `fastboot boot`，发送及 Booting 成功，源提交 `3ccda8f1dd1ee49618339a9711722410d93dfc51`。确切启动链、生成策略、macOS 检查和 boot.img 已冻结到 `log/device/nabu-boot-20261104-11/`；是否越过 SMMU、读取 GPT／系统卷及完成挂载仍待屏幕证据，恢复 Android 后回读也待完成。

## 日志回收边界

ESP 的 `handoff-*.txt` 由 loader 在 ExitBootServices 之前写入，恢复 Android 后可以自动取回。屏幕上的 XNU 日志目前保存在内核 RAM，返回报告器只绘屏，没有写入存储；重启后不能保证保留。因此 ESP 交接日志不能替代运行期日志或照片。

回收工具现会额外保存 Android 暴露的 pstore 普通文件，每个最多 8 MiB，并记录原始字节、大小和哈希；文件的出现不自动归因于 XNU。第十轮取回了 719,040 bytes 的 `console-ramoops-0`，原始字节未匹配 `NABU STORAGE`、`loader_return`、`XNU CALLBACK`，未取得可替代照片的 XNU 运行日志。完整内核日志持久化仍待存储通道稳定后设计，不应宣称已实现。

第十轮恢复后的 Android 同时未暴露 `/dev/mem` 和 `/proc/kcore`，检查记录保存在该轮 `ram-log-access.txt`。本次没有可用的这些接口去读取旧 XNU 物理地址；不能把屏幕上的 LOG PA 当作重启后可直接读取的文件地址。
