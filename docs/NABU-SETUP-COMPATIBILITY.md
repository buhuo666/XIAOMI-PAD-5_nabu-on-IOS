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

候选只在 SpringBoard 中且完整、唯一的 `nabu-setup-compat=1` 参数存在时启用：

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

实现来自本项目 C 源码，单独编译普通 arm64 动态库。运行时先验证两项方法的类型编码、
实际 IMP 对应的共享缓存位置、所属镜像及完整函数 SHA-256，再保存原方法和安装包装。
共同的原子开关在两项替换和回读均成功后才启用；安装过程中包装转调原方法。
失败时关闭策略，仅在当前 IMP 仍为自己的包装时恢复。ObjC 的公开 API 没有跨方法事务
或 compare-and-swap；构造期检查及回滚不等于任意并发替换下的原子事务保证。

打包必须显式选择经过源哈希、架构及主机检查验证的库，只为 SpringBoard 配置加载。
启动链同时检查该配置与 boot argument 一致。原始 OS、SystemOS 和磁盘 Data 不改动；
库放入 RAM bootstrap 的 `/redwood/lib/`。

主机模拟、原生编译及真机执行是分别验收的阶段。下一轮需观察库加载／双方法验证日志、
Setup 和 Logo 的后续生命周期、实际桌面，以及定时返回后的完整日志 END。没有这些
记录之前，只称候选兼容策略，不声称桌面成功、Apple 激活成功或联网服务可用。

实际 C 在 WSL 的 Clang ASan/UBSan 下通过 120 个主机测试，覆盖进程与参数门槛、
方法归属／类型／镜像／地址／完整哈希、安装时重入、部分替换失败、第三方替换、
回滚，以及 64 位原因和 BOOL 返回值。测试使用模拟运行时和合成函数，不执行 Apple
原版代码。构造时类若尚未注册，本实现只记录一次拒绝，不重试；时序仍须上机确认。
源构建产物还需核对最终构造函数入口和未定义导入，再进入部署资格检查。
