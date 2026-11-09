# 第174轮GPU候选：连续CAMetalLayer呈现和表面复用

第173轮已验证单帧图案与清除。本轮将同一普通容器App升级到1.1/build2，
只编译UIKit App，复用CI42615860281及第172轮实测的前端、Turnip和metallib。
保持标准Metal工厂、32×32 BGRA、framebufferOnly=NO、maximumDrawableCount=2。

## 实现与证据

- 同一CAMetalLayer、流水线、命令队列和读回缓冲连续执行64帧，一次只有一个GPU命令。
  每帧Completed后核对GPU读回、真实IOSurface像素和缓冲保护区，再调用drawable present。
- 紫色方块水平往返，红黄条纹定期交换；顶部六个色块编码0..63帧号，所有帧像素均不同，
  可检出复用后读到旧帧。图案仍使用第172轮已验证的顶点/颜色着色器。
- 呈现后释放App持有的drawable，再由主队列延迟125ms安排下一次获取。未使用presented
  回调阻塞下一帧，也不把该延迟或CPU计时表述为硬件vsync或目标帧率。
- 逐帧记录IOSurface ID、drawable ID、GPU完成、像素/保护区、获取耗时、呈现回调、
  累计导入和复制计数。用实际表面ID分布判断是否发生复用，不预先假定池大小。
- 完成或退出时保存所有已获得的GPU和IOSurface原始BGRA。主机可再次按帧号验证；
  清除图层/退后台时停止后续帧，等待当前GPU任务完成后清除，检查导入made/released及held。

App Documents为`metal-present-result.json`、`metal-present-frames.bgra`、
`metal-present-surfaces.bgra`和`metal-present-frames.json`。旧单帧文件可能由安装升级
保留在容器中，不能作为本轮证据；新元数据必须与结果JSON的run_id相同。

## 验收范围

实机需确认方块来回移动、条纹变化、64帧完成及清除后桌面/触摸正常。回收后要求64个
命令完成，GPU和IOSurface各65536像素与保护区正确，并分别记录复用、回调和释放结果。
原生GPU路径仍使用普通IOSurface复制兼容，不是零复制或全系统应用加速验收。

传感器全部由用户指定的“传感器3”处理。本轮不修改传感器，也不启动SLPI诊断。
设备进入GPU实测前需确认没有其他窗口正在使用；不额外重启Android。

## 构建和交接状态

App源码834ef75a642822d7cc4d3d65e5aff3685bbc989d，原生CI42631914466成功。
产物为`artifacts/ci/42631914466-attempt-1/nabu-metal-present-app-2/nabu-metal-present-app/NabuMetalPresent.ipa`，
103,679字节；签名/依赖/rpath/容器检查通过，下载审查记录为
`log/host/gpu-v174/app-download-review.json`。未重新审查第172轮前端。
配套CI42631914559仍在编译8796参考内核，另两个作业已成功；不能提前称全套通过。

主机检查器`tools/check_nabu_metal_present_frames.py`会检查双路实际像素、run_id、
逐帧完成/保护区、表面复用计数和清除后的资源平衡。合成正确数据及旧帧、像素损坏、
run_id错误、资源未释放、命令未完成、保护区损坏共7种检查结果符合预期；这只是主机
检查器验证，不是真机GPU结果。记录为`log/host/gpu-v174/host-verifier-check.json`。

用户明确选择：“等其他窗口测试结束，我再通知你”。当前未操作设备，未准备日志槽、
部署、安装或启动第174轮。预备沿用display01已实测内核和第173轮mount-only启动包，
配置不启用SLPI。收到用户通知后再建立绑定该内核的新日志清单，不能复用旧清单。
后续状态写入`log/host/gpu-v174/continuation.json`。
