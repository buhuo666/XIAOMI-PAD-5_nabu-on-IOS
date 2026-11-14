# Nabu 越狱环境

2026-11-14 用户要求将内核构建成完整越狱。当前内核已有部分真实能力，但包管理、通用 tweak 环境和持久化验收尚未完成；不能以应用安装成功或 PC 的越狱标签代替这些验证。

## 2026-11-14 原生 APFS 验收

setup build 3（691eb7f / CI43581057720）已实机迁移 `/var/jb` 到 `/private/var/db/nabu-jailbreak/procursus`，原 6,527 个文件保留。`setup-03/result-01/filesystem.json` 的 64 项均通过，包括双路径普通 I/O、MAP_SHARED 与 msync、truncate 后已映射页、关闭 fd 后映射、chmod/chown、xattr、跨进程 fcntl/flock、硬链接、rename swap、删除后的已开 fd，以及独立只读 bindfs 拒写。

基础 shell、firmware（实际生成版本 16.5）、apt/dpkg、Sileo 2.5.1 和 ElleKit 0.4.5 已安装/配置。`installation_proxy` 查到 Sileo 的真实 Data 路径，证明此前不能把 ramfs 上的注册问题归因为 Data 路径被禁。但用户尚未看到桌面图标，包状态仍为 Sileo triggers-awaited、uikittools triggers-pending，需要处理并实测启动。

剩余失败为错误调用旧版 Sileo helper（exit 72）及 libkrw0-plugin 缺失（apt check exit 100）。iOS 13+ 的 Sileo 实际用 persona，旧 helper 保留父进程保护；后续以独立自有程序验收 setuid。SHSH/nonce 组件不适用于此非 Apple SoC 平台，计划通过真实 dpkg 卸载而非删除 Depends 或伪造状态。

可写 bindfs 两对象已经 CI43580198891 编译且零未解析符号，但独立审查发现 pager/code-sign、VLOCKLOCAL 和名称缓存问题；该候选未部署。原生 APFS 已解决实际写入目标。下一内核候选仅补 exec 注入通配与配置容量，保持板级内核和显式只读映射。

完整越狱尚未验收：还需 Sileo 界面、独立 setuid、自有包安装/卸载、ElleKit 实际 hook、通用进程注入和重启后恢复。

## 当前设备与日志

设备资料在 `D:/github-IOS/XIAOMI_PAD5-NABU`，源码提交使用独立的 `codex/nabu-app-store` 工作树。

- 内核：`artifacts/nabu-text-encryption-ready-i4-10/kernel.native-apfs.macho`。
- 启动包：`artifacts/nabu-bootstrap-i4-12/bootstrap.apfs`。
- 当前为 `jailbreak-02` 临时 iPadOS 启动，原生 USB 与 fresh GPUInventory 已通过。
- 槽 1 当前占用，不能覆盖。权威记录为 `log/host/jailbreak-20261114/continuation.json`。
- 前一轮 `store-01` 已回收 21,355,326 字节连续前缀和完整 64MiB 槽并清空读回；尾部 `no committed record header`，不能称已完整封口。

重启会结束当前 `fastboot boot` 临时会话并回到 Android。用户在开启开发者模式时遇到这个循环。验证 App build 1 带 `get-task-allow`；build 2 删除该权限，经 CI `43574230296` 编译、签名和一次下载审查后通过 USB 更新，用户确认无需再次操作开发者模式即可看到“验证已结束”。随后通过 Lockdown 只读查询 `com.apple.security.mac.amfi / DeveloperModeStatus` 得到 `false`，保存在 `probe-02/developer-mode-status.json`，确认该 App 在开发者模式关闭时运行成功。未更改默认启动系统，系统开发者模式持久化也未另行测试。

## 已实测能力

build 2 证据：`log/host/jailbreak-20261114/probe-02/result-02/`。

| 项目 | 实际结果 | 范围 |
| --- | --- | --- |
| persona root | UID/EUID 均 0 | 应用启动的专用子进程 |
| task_for_pid | 返回 0 | 自有 UID/EUID 501 子进程 |
| 内存读写 | 两次读回值匹配，读写返回 0 | 已知 64 位测试值 |
| task_threads | 返回 0，1 个线程 | 同一自有子进程 |
| JIT | RW 映射转 RX 成功，执行返回 42，子进程退出 0 | 自有 ARM64 测试代码 |
| DYLD 注入 | 导出符号存在，返回 0x4e414255，子进程退出 0 | 自有签名 dylib |
| 旧 ptrace attach | 返回 45 | 测试误用了 PT_ATTACH；尚不能作为能力缺失结论 |
| 包管理环境 | /var/jb、dpkg、apt-get、Sileo、TweakLoader 均 ENOENT | 尚未部署 |

`bsd/kern/mach_process.c` 对非 macOS 的旧 `PT_ATTACH` 明确返回 ENOTSUP；`PT_ATTACHEXC=14` 才会进入实际附加检查。build 3 改用该请求，记录请求名称、停止及分离结果。它还将专用结果目录交给 mobile，以便主程序在 root 子进程结束后写入 `root-launch.json`；build 2 的三份 root 结果已回收，但此回执缺失。

build 3 提交 `53c60e3` / CI `43575012169` 构建签名成功，完成一次下载审查和 USB 更新，独立 Lookup 确认 build 3。用户确认“验证已结束，结果已保存”。`probe-03/result-01/` 四份结果齐全，`results.json` 自报 build 3：root、task_for_pid、内存读写、线程查询、JIT、注入继续通过；`PT_ATTACHEXC` 附加 errno 0，观察到停止，分离 errno 0；目录 chown errno 0，主回执退出 0。逐项机器核对在 `assessment.json`。本次修复只更新验证程序，没有更改内核或重启设备。

测试的 cleanup SIGKILL=9 是终止自有等待子进程的预期动作。`rootTests` 退出 0 和 UI“验证已结束”只表示执行结束，每项是否通过必须查看 JSON。无 `get-task-allow` 也不等于所有普通应用都具有这些权限：当前测试程序仍有 task_for_pid、persona、JIT 等明确的签名权限。

本轮采集用于能力结果和启动 syslog，没有启用画面路径的性能测点。不能从 App 打开或上述返回值推出呈现延迟。本轮画面路径记录如下：

| 阶段 | 最小耗时 | 最大耗时 | 平均耗时 | 原因、合理性和优化判断 |
| --- | --- | --- | --- | --- |
| 画面请求到 UIKit 提交 | 未测 | 未测 | 未测 | 未采样该区间，无法判断 |
| UIKit/CoreAnimation 处理 | 未测 | 未测 | 未测 | 未采样该区间，无法判断 |
| 合成/GPU 执行 | 未测 | 未测 | 未测 | 未采样该区间，无法判断 |
| DPU 接受画面 | 未测 | 未测 | 未测 | 未采样该区间，无法判断 |
| 面板扫描结束、实际显示完毕 | 未测 | 未测 | 未测 | 无面板完成测点，无法判断；不能以 DPU 接受代替 |

## 构建与回收

macOS / Xcode 完整构建由 `.github/workflows/jailbreak-probe.yml` 执行：

```sh
python3 tools/build_nabu_jailbreak_probe.py --output artifacts/nabu-jailbreak-probe
```

已配对 USB 回收：

```powershell
python tools/read_nabu_jailbreak_probe.py --output log/host/jailbreak-20261114/probe-03/result-01
```

四份结果位于 AFC 的 `/NabuJailbreak/`：`root-launch.json`、`results.json`、`jit.json`、`injection.json`。回收脚本同时独立查询安装版本，不启动 App、不重启设备。

## 后续完整环境

Procursus rootless 1800、Sileo 2.5.1 和 ElleKit 0.4.5 是已下载的固定参考输入，来源在 `artifacts/nabu-jailbreak-inputs/download-requests.json`。三项输入已完成一次审查，Sileo 与下载的 Packages 索引一致，Unix 权限在重打包中保留。记录为 `artifacts/nabu-jailbreak-seed-02/input-review.json` 与 `seed-metadata-check.json`。没有执行原始 prep_bootstrap.sh，也没有修改包依赖声明。

原生安装 App 提交 `81b2377` / CI `43576184745` 编译签名通过，经审查后安装到设备（`org.nabu.JailbreakSetup` build 1）。用户打开后，root 已将 6,527 个基础文件解包到持久化 Data，三个输入通过新 USB 会话确认传输成功。配置在创建 `/var/jb/var/mobile` 时返回 EROFS；Sileo/ElleKit 尚未通过 dpkg 安装，也没有运行包脚本。当前 bindfs 强制只读/NOSUID，且没有写操作，因此下一步是补齐真实的可写映射。详情见 [bindfs 诊断](../analysis/nabu-jailbreak-bindfs-rw-20261114.md)。

部署应沿用现有持久化 APFS。上游 `src/hakios-8796/tools/mk-jb.sh` 和 `userland/src/init.c` 的每次重建 `/var/jb`、RAMFS 前缀和删除依赖方案不能直接用于本项目。必须保留文件 UID/GID/mode、Sileo helper 的 setuid，验证 LaunchServices 的真实应用路径，并按实际依赖处理固件包与 libkrw 等组件。

当前 `etc/inject.conf` 已为桌面、输入、蓝牙等配置兼容库；接入 ElleKit 时必须保留这些条目。不默认启动 root 网络服务。完整验收还需要 apt/dpkg/Sileo、安装卸载、tweak 加载及重启持久化。爱思仍显示“未越狱”，其检查规则尚未确定；爱思安装/FairPlay 支线继续暂停。

商店 root 和 IPA 安装实测见 [NABU-APP-STORE.md](NABU-APP-STORE.md)。tapgame 的 Unity Metal 方法修复已构建并审查，尚未部署，可在下一轮启动包中合入。
