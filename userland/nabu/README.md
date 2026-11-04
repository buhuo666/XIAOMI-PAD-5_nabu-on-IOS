# nabu 用户态初始化策略

用户于 2026-11-04 要求跳过首次设置／激活引导，目标是直接进入 SpringBoard 桌面。

`var/mobile/Library/Preferences/com.apple.purplebuddy.plist` 是后续 Data 种子的偏好文件，包含 `SetupDone=true` 和 `ForceNoBuddy=true`。目的仅是初次设置界面的启动策略；它不是 Apple 激活记录，也不代表联网注册成功。

部署时将此文件置于 `/private/var/mobile/Library/Preferences/`，归属 mobile（UID/GID 501），权限 0644。已有 Data 中的其他偏好和用户状态应保留，只合并这两个键。当前没有向设备写入该文件，Data 初始化／挂载路径也尚未接通。

现有固定 HakiOS 源码在 `userland/mkjobs.py` 中排除 purplebuddy 相关启动项，并在 `userland/src/inject_sb.c` 中另有 SpringBoard 的 setup/activation 兼容逻辑。后者包含特定二进制地址和对象布局，不能直接复制为本机 20F66 已验证实现。待 launchd 和桌面服务启动后，根据实际 20F66 组件确认是否还存在额外的界面阻塞。

验收为不进入首次设置助手、出现实际 SpringBoard 桌面。偏好文件能被解析或已生成，不算该验收通过。

## 初始用户态候选

原生 UFS 已在第十一轮实际挂载 OS，并读取完整 launchd、核对 SHA-256 一致。下一候选使用小型 RAM 启动包：第一个 APFS 容器存放静态 stage0，作为初始 `/sbin/launchd`；stage0 从同一个 md0 的第二个容器挂载 `/redwood`，运行源构建的 init。init 通过已存在的 PID1 根切换接口转到 `/dev/nabu_os`，把 `/dev/nabu_systemos` 挂载到 OS cryptex 位置，再建立临时 RAM Data 和选择过的启动项，最后尝试执行原版 `/sbin/launchd`。

原始 OS／SystemOS 保持原样。当前内建 APFS 挂载实现为只读，先用 RAM Data 验证用户态；49 GiB 磁盘 Data 不修改，跨重启保存状态仍未实现。第一轮用户态测试计划保留 120 秒日志观察窗口，且不设置 `return_cpu` 或 `return_panic`。

`tools/build_nabu_userland.py` 在 macOS Actions 编译静态程序，验证普通 arm64、可执行入口和无 dyld／动态库依赖。Apple 启动 plist 在本地从已有 20F66 镜像提取，`tools/package_nabu_userland.py` 在本地组装小镜像并执行 APFS 检查；它们不进入 Git 或 CI 产物。RAM 包的所有系统文件仍只是来自用户已有镜像的本地输入。

`jobs.json` 选择启动任务；其余允许的 Mach 服务只在请求时启动。首次设置／mobileactivation 任务排除。暂不启用带 iPhone10,3 私有地址的注入库；需要显示兼容时，应先对本机 iPad7,11 的实际组件确认。

内核提供仅 PID1 可写的原子进度字段，终止报告会显示 `NABU USERLAND: phase=N errno=E`：

| phase | 含义 |
|---:|---|
| 0 | 未收到用户态进度 |
| 1 | stage0 已开始执行 |
| 2 | init 已作为 PID1 运行 |
| 3 | init 已挂载磁盘 OS |
| 4 | 根切换完成 |
| 5 | SystemOS 挂载完成 |
| 6 | 必要初始化检查通过 |
| 7 | 正在尝试 exec 原版 launchd，单独出现此值不证明 exec 成功 |
| 8 | exec 返回失败，errno 是对应错误 |

当前仍沿用参考内核的 Mini AMFI／安全接口，其 trust-cache API 不是原版实现；此次不加载未接通消费路径的 trust-cache sidecar，不能称作原版安全栈或完整认证链验证。

## 第十二轮候选与已完成的主机验证

macOS Actions `41778561798`（attempt 1，源码提交 `f613199a1f32640e10b6b24868f9aeec45fa2499`）完整构建及检查成功。启动内核为 17,126,048 bytes，SHA-256 `0905569c42a60f4418d712f720eb5f734d7ac63da4e5c3bfdc2df4718aaf8b17`。下载后核对了内核哈希、导出合同和原生指令：6 个返回路径范围的 1,500 条指令、5 个存储入口范围的 1,569 条指令与实际启动内核一致。本地生成的 13 个存储文件规范化换行后也与该次 CI 一致。

静态 stage0 为 34,496 bytes、init 为 51,768 bytes，均已核对普通 arm64、可执行入口、LC_UNIXTHREAD 和无 dyld／动态库依赖。8 MiB 的 `artifacts/nabu-bootstrap-v1/bootstrap.apfs` 包含两个各 4 MiB 的 APFS 容器，SHA-256 `daf73f92e2831ffc771742e46c89e1dd25ea8e81bc7217b805f2f93d1d6518e6`。两个容器分别通过 `apfsck -c -u -w`；独立提取其中的程序后，字节与下载的 CI 程序完全相同。包内共有 387 个任务，其中明确选择启动的为 21 个。

本地补充的实际 EFI ADT 解析器测试通过 13,644 个截断输入、5 个分配场景、46 个检查点和 3 个 bootstrap 场景；这 3 个新增场景在上述 CI 完成后运行，不能计入该次 CI。主机记录为 `log/host/nabu-userland-verification.json`、`log/host/nabu-bootstrap-adt/report.json` 和 `log/host/nabu-storage/ci-userland-source-verification.json`。

当前启动配置使用 `nabu-storage=1 nabu-bootstrap=1 rd=md0 root_apfs=nabu_os loader_return_after=120`，加载本地 bootstrap.apfs，已移除原挂载探针。第十二轮将验证这条用户态路径；截至准备阶段，未确认 stage0、init、原版 launchd 或桌面在设备上执行。RAM Data 不具备跨重启持久性，12 GB 全容量接管也仍待完成。
