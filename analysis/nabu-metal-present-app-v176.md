# 第176轮候选：256×256纹理采样和连续呈现

第175轮启动就绪与64帧32×32光栅呈现通过后，用户要求继续GPU。设备已按其授权
交给“传感器4”实测，本轮先完成本地候选和原生编译，不操作平板。

## 工作负载

App升级1.3/build4，CAMetalLayer drawable为256×256 BGRA8、maximumDrawableCount2，
仍保持每次只提交一个App绘图命令并在Completed后核对GPU/IOSurface，再present。
连续64帧每路检查4,194,304像素、导出16MiB原始BGRA；双路共32MiB。

新增普通Shared、ShaderRead源纹理，每帧通过replaceRegion更新。CPU上传行距1280，
有效像素行1024字节，前后各256字节和每行256字节保护区，GPU完成后验证输入未被改写。
读回缓冲使用相同的填充行距，继续检查像素与保护区。CPU只写源纹理，不写drawable。

复用第172轮已合格metallib中的nabu_surface_vertex/nabu_surface_sample：按像素中心
以nearest采样源纹理并写drawable。源纹理和目标同尺寸，不重编着色库或前端。
底图包含x、y、x异或y及帧号的不同颜色变化；顶部六个色块编码帧号，紫色方块往返。
可检出横纵坐标互换、红蓝通道互换、错误行距和旧帧复用。

每帧记录上传序号、有效字节数和行距，保存实际目标GPU读回及IOSurface读回。
64个Completed计数只表示App显式绘图命令，replaceRegion内部工作不计入该字段。
清除时释放源纹理和上传内存，弱引用确认源纹理Objective-C包装对象已释放；该检查
与drawable的imports made/released、held0分别记录，不外推为全部底层GPU分配统计。

保留第175轮进入UIKit前的同boot挂载/AGX检查和主机先等GPU再安装的流程。内核和
启动包继续采用已实测基线，传感器与霍尔的整合另行协调。

## 验证

tools/check_nabu_metal_texture_pattern.py在宿主编译实际App图案头文件，并启用
ASan/UBSan。C++输出的64帧与Python独立计算的4,194,304像素一致。正常数据、双路
旧帧、转置、红蓝交换、单像素损坏、上传保护区错误、上传序号错误、源纹理未释放、
表面导入未释放和启动未就绪共10种场景符合预期。仅为合成宿主证据，未执行GPU。
第174、175轮真实旧数据的主机回归也通过。

本检查已加入App原生CI。Windows宿主证据在`log/host/gpu-v176/host-pattern-check/`，
动态记录在`log/host/gpu-v176/continuation.json`。原生编译与实机结果另行更新。

实机验收要求64帧双路各4,194,304像素全正确，输入/读回保护区0错，有实际surface复用，
清除后源纹理包装对象与表面导入释放通过，并由用户确认彩色纹理和方块动画正常。
125ms调度延迟是测试节奏，不作为硬件同步或帧率结论。本轮仍未验证全系统应用加速。
