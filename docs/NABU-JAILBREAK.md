# Nabu 越狱环境

2026-11-14 用户要求将内核构建成完整越狱。当前内核已有部分真实能力，但包管理、通用 tweak 环境和持久化验收尚未完成；不能以应用安装成功或 PC 的越狱标签代替这些验证。

## 当前设备与日志

设备资料在 `D:/github-IOS/XIAOMI_PAD5-NABU`，源码提交使用独立的 `codex/nabu-app-store` 工作树。

- 内核：`artifacts/nabu-text-encryption-ready-i4-10/kernel.native-apfs.macho`。
- 启动包：`artifacts/nabu-bootstrap-i4-12/bootstrap.apfs`。
- 当前为 `jailbreak-02` 临时 iPadOS 启动，原生 USB 与 fresh GPUInventory 已通过。
- 槽 1 当前占用，不能覆盖。权威记录为 `log/host/jailbreak-20261114/continuation.json`。
- 前一轮 `store-01` 已回收 21,355,326 字节连续前缀和完整 64MiB 槽并清空读回；尾部 `no committed record header`，不能称已完整封口。

重启会结束当前 `fastboot boot` 临时会话并回到 Android。用户在开启开发者模式时遇到这个循环。验证 App build 1 带 `get-task-allow`；build 2 删除该权限，经 CI `43574230296` 编译、签名和一次下载审查后通过 USB 更新，用户确认无需再次操作开发者模式即可看到“验证已结束”。该结果解决了验证 App 的启动阻碍，不代表已经更改默认启动系统或查明系统开发者模式的持久化状态。

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

`bsd/kern/mach_process.c` 对非 macOS 的旧 `PT_ATTACH` 明确返回 ENOTSUP；`PT_ATTACHEXC=14` 才会进入实际附加检查。build 3 改用该请求，记录请求名称、停止及分离结果。它还将专用结果目录交给 mobile，以便主程序在 root 子进程结束后写入 `root-launch.json`；build 2 的三份 root 结果已回收，但此回执缺失。新的结果仍须真机验证。

测试的 cleanup SIGKILL=9 是终止自有等待子进程的预期动作。`rootTests` 退出 0 和 UI“验证已结束”只表示执行结束，每项是否通过必须查看 JSON。无 `get-task-allow` 也不等于所有普通应用都具有这些权限：当前测试程序仍有 task_for_pid、persona、JIT 等明确的签名权限。

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

Procursus rootless 1800、Sileo 2.5.1 和 ElleKit 0.4.5 是已下载的固定参考输入，来源在 `artifacts/nabu-jailbreak-inputs/download-requests.json`。尚未完成审查、安装、真实包安装卸载或 tweak 测试。

部署应沿用现有持久化 APFS。上游 `src/hakios-8796/tools/mk-jb.sh` 和 `userland/src/init.c` 的每次重建 `/var/jb`、RAMFS 前缀和删除依赖方案不能直接用于本项目。必须保留文件 UID/GID/mode、Sileo helper 的 setuid，验证 LaunchServices 的真实应用路径，并按实际依赖处理固件包与 libkrw 等组件。

当前 `etc/inject.conf` 已为桌面、输入、蓝牙等配置兼容库；接入 ElleKit 时必须保留这些条目。不默认启动 root 网络服务。完整验收还需要 apt/dpkg/Sileo、安装卸载、tweak 加载及重启持久化。爱思仍显示“未越狱”，其检查规则尚未确定；爱思安装/FairPlay 支线继续暂停。

商店 root 和 IPA 安装实测见 [NABU-APP-STORE.md](NABU-APP-STORE.md)。tapgame 的 Unity Metal 方法修复已构建并审查，尚未部署，可在下一轮启动包中合入。
