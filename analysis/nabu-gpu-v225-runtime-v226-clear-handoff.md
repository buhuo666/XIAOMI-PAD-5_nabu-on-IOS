# GPU225 失败实测与 GPU226 空层清理交接

2026-11-12，Asia/Shanghai。两项用户目标仍未达标，不把主机测试或原生分支执行写成性能通过。

## GPU225 实测

提交 `32f32b8`，专项CI `43158743390` 成功，保留GPU223内核。持久化日志4500–4501行证实observer `install=63 capabilities=63`，timer `install=1 active=1 single-free-page=1 slots=6`。

默认15秒run `1794460266799983-scene0-repeat1`，正式测量区间234.064961–249.064961秒，完整落在trace窗口142.080808–262.080808秒内；474,288条记录、零丢失。1200提交/完成、0 nil drawable、0命令失败、0 admission skip；用户确认动画和触摸正常。1200/1200正式帧完整关联，无关联诊断错误。

| 指标 | 平均 ms | P95 ms | P99 ms |
|---|---:|---:|---:|
| present → CA begin | 5.131092 | 5.334 | 5.388 |
| CA begin → finish | 0.205316 | 0.235 | 0.287 |
| finish → DPU入口 | 0.147090 | 0.176 | 0.216 |
| present → DPU入口总计 | 5.483498 | 5.711 | 5.762 |
| DPU入口 → scan submit | 8.044876 | 8.191 | 8.215 |
| scan submit → 接受观察 | 7.580373 | 7.655 | 7.684 |
| App submit → 接受观察总计 | 23.602394 | 23.733 | 23.758 |

CA总区间1194/1200帧超过5ms；整链1200/1200超过8.32ms。App提交80/s；1200个成功can的flags均为1，证明候选准入分支已执行，但未消除首次等待。相邻新画面接受平均12.503645ms，1199对中600对双INTF计数增加2。

来源：`log/host/gpu-v225/default-ca-path.json`、`default-gpu-chain.json`、`bench-default/`、`trace-default/`。

## 重复硬件扫描的直接证据

首个到末个正式App帧的硬件接受区间内，event37共1800次，其中1200次新画面、600次属于event55标记的空层继承事务。详情 `log/host/gpu-v225/clear-replay-evidence.json`。

例：swap703接受后，set=clear=2且四个surface_id均零的swap704继承相同surface21；它仍重新映射并发event36/37，占下一刷新。其后像素swap705/706才能依次接受。swap707再次执行相同无像素变化清理。driver的`ClearInheritedLayer0`保证资源安全，却为本来已空的layer1额外重扫layer0。

## GPU226 边界与验收

候选保留单FIFO与原生CA准入/调度。只有已确认第二层为空的精确清理请求才能使用原位交接：先检查此前事务失败，再将已接受的current Held及ledger所有权交给新清理ID。mapping token/slot、surface引用/displayUse、producer read lease、scan current_sequence/current_iova保持不变，下一次真实像素替换才释放资源。

不发scan-submit/accepted/physical-retired，不增加新画面计数，不改lastDisplayTime，不提前允许GPU写仍在扫描的页。新event56只报告逻辑事务所有权交接，载荷为new_swap/old_swap/mapping_token/scan_sequence；原event38仍只表示真实资源退休。分析器将两者分开统计，event56不得替代任一真实硬件接受时间。

实机仍需复测正式帧CA<5ms和整链<8.32ms、完整帧覆盖、零失败、画面触摸、场景结束清理；主机模型不能证明真实CA复用与硬件行为。GPU225表现不作为合格性能基线。

## 日志保全

已回收7,590,365字节连续日志及完整64MiB槽1，清空读回通过；日志未封口。首个回收尝试发生在ADB尚未ready时，于任何设备读写前退出；Android设备就绪后正常完成。设备当前Android/USB，GPU226尚未部署。
