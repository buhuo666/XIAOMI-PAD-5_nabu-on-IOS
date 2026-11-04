# 小米平板 5（nabu）工作目录

当前目标：XNU 8796.121.2 + iPadOS 16.5（20F66），普通 arm64，iPad7,11／J171AP 供体。

当前进展：实机已报告八核在线及 framebuffer 初始化；第九轮记录了八个核心的 signal SGI 计数增长，以及 CPU 7 的定时工作与目标回调执行。完整跨核调度、全核定时器负载和 TLB 测试仍未验收。设备为 12 GB 扩容机，当前 loader 交接的连续窗口约 7.89 GiB。用户要求优先进入 iPadOS 桌面；主动 panic 日志问题已[单独记录并暂缓](docs/DEFERRED-PANIC-DIAGNOSTICS.md)，工作区后续配置已取消主动 panic 和定时返回，尚未重新部署。原生存储、用户态启动及 Data 持久化挂载仍待接通。见 [启动入口记录](docs/NABU-BOOT-ENTRY.md) 与 [项目进展](docs/STATUS.md)。

用户提供的弃用内核已解包，并从可核对的旧补丁链恢复 85 个硬件参考文件；仅作为调查线索，不用于当前构建，也不作为硬件正确性证据。见 [历史硬件参考](docs/ABANDONED-KERNEL-REFERENCE.md)。

推荐主目录名：`XIAOMI_PAD5-NABU`。目录名用英文、数字、连字符或下划线，文件夹名称保持简短；研究文档可以使用中文文件名。主目录已在开工时去掉空格：HakiOS 的 [构建说明](D:/github-IOS/research-sources/hakios-xnu-kernel/xnu/README.md) 明确要求仓库路径没有空格。

项目进展见 [STATUS](docs/STATUS.md)，开工命令和 CI 说明见 [BOOTSTRAP](docs/BOOTSTRAP.md)。

## 目录用途

```text
XIAOMI_PAD5-NABU/
├── README.md       工作目录入口和命名规则
├── docs/           路线、设计、阶段结论、研究资料入口
├── device/         这台设备的实测信息与资源图
├── OS/             下载的系统包、原始提取材料和校验信息
├── firmware/       UEFI、GPU、DSP、触摸等硬件固件
├── src/            实际开发与构建使用的完整源码仓库
├── patches/        需要重复应用或交付的补丁与应用顺序
├── configs/        本机配置、OS profile、构建与启动配置
├── tools/          提取、构建、打包、校验、日志处理脚本
├── build/          可重新生成的编译中间文件
├── artifacts/      每次构建的完整可测试、可安装产物
├── log/            每次设备测试的记录与原始日志
└── backup/         设备恢复备份和重要数据副本
```

| 目录 | 具体放什么 | 容易混淆的地方 |
|---|---|---|
| `docs` | 工作路线、接口说明、问题结论、阶段验收报告 | 某次测试的原始输出放 `log`；长期有效的结论写入这里 |
| `device` | 设备型号、固件版本、CPU 信息、RAM bank、reserved-memory、UFS 几何、GPT 区间表 | 分区清单属于设备资料；分区的完整镜像属于 `backup` |
| `OS` | 原始 IPSW／Android 包、未经修改的提取成员、BuildManifest、下载来源与哈希 | 修改后供启动使用的系统镜像放 `artifacts` |
| `firmware` | 已取得的 UEFI 固件、Qualcomm GPU／DSP 固件、触摸固件及来源记录 | 系统软件放 `OS`；UEFI 的源码放 `src`，自行编译的 UEFI 候选放 `artifacts` |
| `src` | XNU、UniXNU、nabu、SoC、loader、图形组件等完整源码仓库 | 研究快照不能直接当成完整开发树；各仓库保留自身 Git 记录 |
| `patches` | 针对固定源码版本导出的补丁、补丁来源、应用顺序和用途 | 日常修改仍在源码仓库管理；这里保存明确版本的可重复应用补丁 |
| `configs` | 设备／OS 配置、内核参数、启动菜单模板、组件锁定与内存／存储参数 | 示例配置明确标注；未经实测的 LBA、UUID、内存窗口不得当成可用配置 |
| `tools` | 自己维护的 PowerShell、Python、Shell 辅助脚本 | 上游自带的脚本继续跟随对应源码仓库 |
| `build` | 对象文件、生成的头文件、临时解包、链接中间文件、编译缓存 | 清理后应能重新构建；唯一的固件、日志或备份不能放这里 |
| `artifacts` | kernel、ADT、EFI、插件、系统候选镜像、配置副本、输入收据和校验值 | 一个构建一个目录；已经用于测试的构建不覆盖修改 |
| `log` | 启动日志、panic、串口／USB 输出、截图、录像、测试动作和结果 | 一次构建可以对应多次测试；每次测试单独记录 |
| `backup` | GPT、ESP、引导／恢复相关分区镜像、Data 备份及恢复说明 | 此处是恢复材料；不能作为日常编译输出目录 |

## 系统包与硬件固件

已为当前目标创建：

```text
OS/
├── ipados/
│   └── 16.5-20F66-iPad7_11/
│       ├── original/      Apple 原始 IPSW
│       ├── extracted/     原样提取的 kernelcache、DMG、DeviceTree 等
│       └── manifests/     BuildManifest、来源与哈希清单
└── android/               以后按实际版本再建子目录

firmware/
├── uefi/
├── qualcomm/
└── touch/
```

原始文件保留厂商文件名；用外层目录区分版本和产品。不同系统 build 的材料分开放，例如 `16.5-20F66-iPad7_11` 与另一个 build 使用不同目录。`iPad7_11` 是便于命名的写法，配置内的真实产品标识仍是 `iPad7,11`。

下载完成后记录来源、获取时间、大小和 SHA-256。解包后分别记录成员哈希；修改后的系统材料要有单独产物目录，不能直接覆盖原始提取结果。

## 构建与测试命名

构建编号建议：`YYYYMMDD-NNN-用途`。例如 `20261103-001-m2-boot`，其中 `001` 为当天递增编号。时间按 Asia/Shanghai 记录。

测试编号建议：`run-NNN-用途`，放在当天日期目录下。下面只表示布局示例，没有对应已执行的测试：

```text
build/
└── 20261103-001-m2-boot/            本次编译的中间文件

artifacts/
└── 20261103-001-m2-boot/            本次构建的完整测试产物
    ├── kernel.macho
    ├── nabu.adt
    ├── build-manifest.json         输入版本、配置与产物哈希
    └── checksums.sha256

log/
├── _template/
│   └── test-report.md              测试记录模板
└── 2026-11-03/
    └── run-001-m2-boot/
        ├── test-report.md          目标、步骤、观察、结论、构建编号
        ├── boot.txt                原始启动日志
        ├── panic.txt               出现异常时保存
        ├── commands.txt            实际执行的命令
        └── media/                  实际取得的截图或录像
```

每次测试开始时复制模板到新测试目录，填写 `build_id` 和产物路径；同一个候选复测也使用新的测试编号。原始日志保留原样，分析写进 `test-report.md`。

通过的构建继续保留原编号，在构建清单或阶段结论中标注“已验证稳定”。启动配置指向该编号，避免出现多个内容不明的 `final`、`final2`、`最新版` 文件夹。

## 设备资料与备份

设备采集快照和 `memory-map.json` 已保存到 `device`，GPT 备份位于 `backup/gpt`。以下是资料的用途：

- `inventory.md`：实际设备和当前固件信息。
- `memory-map.json`：物理内存、保留区、装载窗口和内核管理窗口。
- `storage-layout.json`：UFS 几何、LUN、GPT 区间和明确的单位。
- `boot-chain.md`：本机可用引导入口和恢复路径。

`backup` 已分为 `gpt`、`esp`、`partitions`、`data`。每次备份再建 `YYYYMMDD-HHMMSS-用途` 目录，保存镜像、SHA-256 和备份说明；说明必须记录源分区或卷、大小、设备固件状态、采集命令以及恢复方法。可以恢复到哪个状态，以实际验证记录为准。

## 文档入口

已有工作路线、基线草案和研究来源见 [资料索引](docs/README.md)。后续新增设计说明和阶段总结直接写入 `docs`。
