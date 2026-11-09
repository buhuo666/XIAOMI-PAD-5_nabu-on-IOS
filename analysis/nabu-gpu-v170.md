# 第170轮：NC IOSurface真实共享读写通过

2026-11-09。用户确认桌面、触摸正常并恢复Android。遵照新要求，本轮没有额外
重启Android，直接部署后切bootloader执行临时fastboot boot。

标准MTLCreateSystemDefaultDevice返回真实AGX registry ID4294967770的A640设备。
独立0x4147连接分配并映射16384字节NC BO，以IOSurfaceAddress包装为32×32 BGRA8、
行距256字节的IOSurface。普通缓存导入仍关闭：params=63、device_flags=1、submit_flags=4。

| 实机项目 | 结果 |
| --- | --- |
| 重复读写 | 32轮、65个命令缓冲均Completed |
| GPU采样/CPU直接读取 | 各32768像素，错误0 |
| 行间/尾部保护 | 检查266240/532480字节，错误0 |
| GPU读回保护区 | 检查147456字节，错误0 |
| 提交前释放应用引用 | 命令保持资源，完成后1024像素正确 |
| 真实指针导入 | 1次，16384字节 |
| CPU副本/复制输入/合并回写 | 所有计数均0 |
| 图像选择 | in-place=1、shadow=0 |
| 最终释放 | surface made/released=1/1、held=0；CPU unmap和BoFree均成功 |

实际BGRA像素和同run_id元数据已从设备回收并转为PNG，位于
`artifacts/nabu-iosurface-render-v170/`。图案是第31个epoch的实际表面内容；最后一个
生命周期命令另行验证，不用期望图生成输出。`in_place_checks_run=0`表示runtime的自动
检查没有运行；本轮in-place资格来自已记录的真实双向像素、边界和重复使用实测。

## 输入与日志

- 源码`926fea73bdbb98bc34353a6365578094c5484e40`；IOSurface CI42607114009及完整
  内核检查CI42607113915均成功。实际仍复用v168内核，没有本轮内核或缓存策略改动。
- 新前端使用Rust1.98.1、LLVM21.1.8、Xcode16.4；原25项patch保留，追加只读统计patch。
  Turnip、标准发现bundle和bindfs挂载助手复用既有合格产物。
- `log/host/gpu-v170/iosurface-runtime/probe-result.json`为完整实测结果，另保留
  stdout/stderr、独立结果JSON和实际像素。mount检查通过。
- `log/device/nabu-boot-20261109-170/runtime-log/`保留3,364,841字节连续日志前缀和
  完整64MiB槽；槽14清空读回通过。APFS139→140、fullfsync=ok。
  无最终sealed记录，不把已捕获前缀写成完整关机日志。

本轮限定单进程、单一NC包装表面、32×32 BGRA8。普通系统IOSurface默认缓存路径、
跨进程及呈现尚未验证，当前系统工厂仍只准入测试程序，不能据此宣称桌面加速完成。
下一步测普通系统IOSurface的实际导入/复制路径与相同GPU像素，保持统计分类准确。
