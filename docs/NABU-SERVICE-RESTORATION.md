# 本地系统服务恢复

日期：2026-11-06。按既定iPadOS移植路线，以v66内核/bootstrap v68为已验证基线。

## 第七十轮候选

本轮处理13项：新增duetexpertd、photoanalysisd的按需入口，以及passcodenagd原版条件任务；
恢复另外10项已运行服务的原版保活或选定本地通知。保留原值、进程身份、Mach端点及
原版禁用/硬件条件；没有制造触发文件。其余差异已分类，未声明全部系统服务恢复。

| 服务 | 本轮变更 |
|---|---|
| com.apple.duetexpertd | 恢复实际缺失的本地建议、应用目录与FaceSuggestions IPC；首启只按需，暂不恢复云备份、IDS、资源更新和周期活动。 |
| com.apple.photoanalysisd | 恢复本机照片分析的原版Mach服务，先由本机照片操作触发；暂不恢复backgroundanalysis/music/turboanalysis活动。 |
| com.apple.managedconfiguration.passcodenagd | 补回无MachServices的本地密码策略提示任务，保留原版PasscodeDoesNotComply文件条件，不创建该文件或强制启动。 |
| com.apple.chronod | 恢复已运行的小组件进程崩溃恢复与本机安装、时间、语言和辅助功能通知。 |
| com.apple.assetsd | 恢复本机照片资产服务崩溃重启与本地照片权限变化事件；不恢复cloudphoto、SharedWithYou或周期处理。 |
| com.apple.aggregated | 恢复已验证运行的本机能耗日志服务原版保活，便于设置电量/本地使用统计。 |
| com.apple.mediaserverd | 恢复已验证运行的媒体解码服务原版保活；这是软件服务策略恢复，不宣称音频/摄像头驱动可用。 |
| com.apple.dmd | 恢复已验证dmd的本机应用登记、类别、有效设置、时间及首次解锁通知；排除iCloudAccount.didChange。 |
| com.apple.calaccessd | 恢复本地日历时间、数据库、提醒和显示偏好通知；不恢复conferencerenewal网络活动、分析上报、位置及同步相关入口。 |
| com.apple.contactsd | 恢复本机联系人数据库和收藏展示通知；不恢复定期清理、备份配置和迁移活动。 |
| com.apple.mobiletimerd | 恢复原版时钟启动、alarm事件及本机时间/解锁/启动/电源通知；剔除Watch配对、测试诊断入口。 |
| com.apple.remindd | 恢复本机提醒事项启动、alarm与本地偏好/时间通知；不恢复ICCloud控制器、nano同步或location事件。 |
| com.apple.searchd | 恢复本机搜索偏好及卸载通知；不恢复sendmlfeedback、加密备份或周期活动。 |

打包策略：userland/nabu/jobs.json逐项选择源字段；tools/nabu_service_policy.py从原版plist复制。
配置主机检查log/host/services-v70/policy-check.json通过；原生诊断构建与签名检查
Actions42193358350通过。设备运行与功能结果仍待实机。

## 同轮诊断

- 显式WallpaperInventory：读原版7410默认HEIC并经ImageIO解码及复制像素，查询壁纸扩展与配置文件存在性；不修改选中壁纸。
- SpringBoard启用CG_CONTEXT_SHOW_BACKTRACE，定位已出现的无效绘制上下文。
- 启动初期只读观察既有RMAdminStore数据库及sidecar的vnode事件，记录inode与路径；不读取内容、不删除数据库或关闭SQLite guard。

原版SQLite的6922已定位为SQLITE_IOERR_VNODE：文件描述符被失效通知作废；
具体事件尚未捕获，不能直接解释为UFS故障。详见log/host/services-v70/sqlite-analysis。

## 其余差异的处置

完整308项处置见log/host/services-v70/restoration-plan.json：首批13、后续验证201、
硬件依赖49、Apple服务范围40、原版默认禁用3、程序供给待证2。后续验证并非已经排除，
按本地通知、后台维护和具体启动场景分批推进。

mobileassetd尚无已证实的全局仅本地模式；ASAssetQuery的客户端仅本地属性不证明
守护进程不会下载。当前未将它纳入首批，也没有伪造资源目录或返回成功。

当前日志槽为14，第69轮已回收清空，APFS计数40；第70轮将保留独立源码/产物及日志。
