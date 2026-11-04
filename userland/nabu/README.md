# nabu 用户态初始化策略

用户于 2026-11-04 要求跳过首次设置／激活引导，目标是直接进入 SpringBoard 桌面。

`var/mobile/Library/Preferences/com.apple.purplebuddy.plist` 是后续 Data 种子的偏好文件，包含 `SetupDone=true` 和 `ForceNoBuddy=true`。目的仅是初次设置界面的启动策略；它不是 Apple 激活记录，也不代表联网注册成功。

部署时将此文件置于 `/private/var/mobile/Library/Preferences/`，归属 mobile（UID/GID 501），权限 0644。已有 Data 中的其他偏好和用户状态应保留，只合并这两个键。第十二轮已把合并后的种子打包进 ESP 上的 RAM 启动镜像，实际用户态部署仍待设备结果；磁盘 Data 初始化／挂载路径尚未接通。

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

2026-11-04 13:36:26（Asia/Shanghai）完成六个 ESP 启动文件的部署和哈希回读，收据为 `log/device/nabu-chain-20261104-133626/deployment.json`。13:37:10 开始第十二轮临时启动，源提交 `4bceed619b56135435225abdca4ac59c689e66fb`，`fastboot boot` 的发送和 Booting 均返回 OKAY。启动前核对了 30 份 GPT 元数据并记录 14 个受检引导分区哈希；336 个启动链／构建／检查证据文件与 boot.img 保存在 `log/device/nabu-boot-20261104-12/`。

第十二轮照片现已保存为 `log/device/nabu-boot-20261104-12/screen-userland-phase5.jpg`，SHA-256 `8d7ecc4d987615f3978211ff2978f991a7545527a4a2e0e9265ddd156a42b941`。画面为 phase 5、errno 0、121 次存储读取、0 次失败，包含约 23 秒处的 `systemHalt`／卸载日志，随后定时返回。结合该轮准确源码，phase 5 表明 init 已经作为 PID1 完成根切换和 SystemOS 挂载；它不证明后续初始化全部通过。未见 phase 7，未确认原版 launchd 执行或桌面。Android 回收已完成，30 份 GPT 元数据和 14 个受检引导分区哈希一致。

## 第十三轮修正候选

本地 20F66 文件清单确认 `/System/Library/NanoLaunchDaemons` 不存在，`NanoLaunchDaemonsAltAccount`、`LaunchAngels` 和 `xpc` 存在。第十二轮源码使用短路 AND 连接四个 bindfs 操作，第二项必定失败，后面的 LaunchAngels／xpc 也不会执行；该失败被计入 `failures`，可触发 phase 5 之后的主动停机。照片本身未显示具体失败项，所以不能排除其他初始化失败。

修正为独立检查各个绑定，仅可选 Nano 目录的 ENOENT 被接受；权限错误、非目录和挂载错误仍失败。已有的 AltAccount 目录也被覆盖为空。新增 `kern.nabu_userland_failure` 只接受 PID1 的 1–191 字节可打印 ASCII，原子发布首个失败字符串，在最终返回报告追加 `NABU INIT FAILURE`。后续失败不覆盖首个失败；此信息仍只存在 RAM，依赖屏幕照片保存，未增加持久化写入。

`tools/check_nabu_userland.py` 执行实际抽取的 C，复现旧短路失败，再验证新绑定能继续到 xpc，并覆盖错误传播、诊断长度、PID1 限制、拷贝失败和发布状态。两组 ASan／UBSan 测试与完整生成程序的 arm64 语法检查已通过。当前仍使用 RAM Data，持久化与完整 12 GB 内存接管待后续完成。

macOS Actions `41784700433`（源码 `f785b223d2a3dc1df8ad2430b9f2a7f4bb730eb4`）完整编译和全部检查成功。前一轮 `41784486372` 已编译两个程序，但测试用的 `__unused` 宏与 macOS 头部重复，现以定义保护修正。候选内核为 17,126,384 bytes、SHA-256 `ddc90e74903baaeb041358e77b75c50986e852bb9a7c1bda935c9e5e5ccd6529`；下载后再次核对大小、哈希、11 个原生范围的 3,069 条指令、13 个生成存储文件、3 个用户态源码文件与首错处理源码。

`artifacts/nabu-bootstrap-v2/bootstrap.apfs` 为 8 MiB，SHA-256 `15b08f2febf2f12f24fe27acf3a9b5c7af4e5ae0462e262c8d597611dee5c212`。两个 APFS 容器检查通过，独立读取其中的 stage0、init 和初始设置偏好通过。该包先使用前一轮已编译的程序组装，现已逐字节确认与完整成功构建的两个程序相同。第十三轮准备沿用 120 秒窗口，设备执行结果待收集。

2026-11-04 14:26:40 完成六个 ESP 文件部署和哈希回读（`log/device/nabu-chain-20261104-142640/deployment.json`），14:27:35 执行第十三轮临时启动（Asia/Shanghai）。发送与 Booting 均返回 OKAY；启动源提交 `4c4ced37ccc416fe5afac19e3580d3aacc956761`，启动前 30 份 GPT 元数据和 14 个受检引导分区均完成核验。343 份冻结输入／检查文件及 boot.img、run.json 保存在 `log/device/nabu-boot-20261104-13/`。当前等待约两分钟后的完整屏幕，重点为 `NABU USERLAND`、`NABU INIT FAILURE` 及 launchd／dyld 日志；此轮运行和桌面尚未验证。拍照后恢复 Android，再对同一运行目录执行 `--collect`。
