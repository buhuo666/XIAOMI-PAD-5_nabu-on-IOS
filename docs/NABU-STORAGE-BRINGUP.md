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
