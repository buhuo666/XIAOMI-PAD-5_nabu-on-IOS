# 20F66 SpringBoard 初始设置兼容

第二十四轮恢复的日志显示 SpringBoard 主动保留启动 Logo，初始设置进程的场景创建和更新
随后超时。保存前缀内 SpringBoard 和 backboardd 仍存活，不能仅凭重复线程栈判断死锁。
用户在 Logo 仍显示时手动重启；该轮没有 END，不作为正常收尾验收。

## 原版路径与候选策略

分析对象是用户已有的 iPad7,11 / 20F66 普通 arm64 系统缓存。原始字节、反汇编和
验证记录仅保存在 `log/host/display-v25/run24-analysis-*`。

已有种子包含 `ForceNoBuddy=true`、`SetupDone=true`，但原版还读取 POSIX 信号量
`purplebuddy.sentinel`；它不是同名普通文件。`ForceNoBuddy` 存在内部版本条件。
`SetupFinishedAllSteps` 属于另一条初次运行完成检查，缺少该键尚不能解释本次阻塞。

独立的 `SBLockdownManager` 状态初值为 0。保存日志内的 MobileActivation IPC 失败
与该状态未完成更新一致，补入序列号字段不能单独实现这个服务。原版 `brickedDevice`
在状态不是 2 时返回 YES；这里不修改状态字段或制造激活记录。

候选只在 SpringBoard 中且存在完整的 `nabu-setup-compat=1` 参数时启用：

| 方法 | 实际 ABI | 本地 UI 行为 |
| --- | --- | --- |
| `-[SBLockdownManager brickedDevice]` | `B16@0:8` | 返回 BOOL NO |
| `-[SBSetupManager _setSetupRequiredReason:]` | `B24@0:8Q16` | 原因传 0，调用并返回原方法的 BOOL |

上游同名 setter 的 void/long 声明不适用于这份镜像。保留原方法调用可保留其状态转移、
清理和通知；直接返回 NO 不等价。仅改 setter 也不够：锁屏管理器另有 `brickedDevice`
分支，会锁定 UI 并断开通话。

这个进程范围的 selector 替换还有其他调用方：原版 SBTelephonyManager 初始化在
`brickedDevice=false` 时请求开启网络注册。因此它的影响不局限于 Setup；本次没有
观察到 nabu 的蜂窝注册或可用蜂窝硬件。直接读取 lockdownState 的启动分支在状态不为
2 时还会隐藏时间显示，两个替换不改变这条独立路径；实机状态字段尚未直接测量。
不能据此承诺已足够进入桌面。

## 安装与验收边界

实现来自本项目 C 源码，单独编译普通 arm64 动态库。按用户要求，2026-11-05
简化了运行时流程，移除方法地址、镜像、完整函数哈希和回滚检查。构造函数确认进程、
启动参数和两个方法存在后，保存原方法并安装包装；两项安装结束后启用共同开关。
安装过程中包装仍调用原方法。

打包必须显式选择经过源哈希、架构及主机检查验证的库，只为 SpringBoard 配置加载。
启动链同时检查该配置与 boot argument 一致。原始 OS、SystemOS 和磁盘 Data 不改动；
库放入 RAM bootstrap 的 `/redwood/lib/`。

主机模拟、原生编译及真机执行是分别验收的阶段。下一轮需观察 `NABU SETUP` 安装日志、
Setup 和 Logo 的后续生命周期、实际桌面，以及定时返回后的完整日志 END。没有这些
记录之前，只称候选兼容策略，不声称桌面成功、Apple 激活成功或联网服务可用。

简化后的实际 C 在 WSL 的 Clang ASan/UBSan 下通过 8 个行为检查，覆盖开关前后
两个包装函数的调用次数、64 位原因传递和 BOOL 返回值。检查使用桩原方法，不执行
Apple 原版代码。构造时类若尚未注册，会记录方法不可用；实际加载时序待真机确认。
原生构建保留 arm64 动态库格式、源码和产物哈希记录，打包沿用这些记录。

2026-11-05 原生构建已通过：Actions `41949431958`，源码提交 `28d5253`。
68,944 bytes arm64 动态库已装入 bootstrap v5，并经 APFS 独立回读确认。
主机检查、构建与打包已完成，运行时安装日志及桌面效果留待第二十五轮真机日志。
