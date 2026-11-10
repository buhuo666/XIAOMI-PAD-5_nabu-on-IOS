# 第178轮：20F66系统着色器兼容

第177轮已经证明系统消费者实际加载GPU前端，但桌面合成和媒体服务分别因uchar3
常量拒绝、缺失Metal方法退出。本轮直接修复这两个运行中出现的错误。

## 原版证据

本机20F66 Metal UUID 88922408-fd68-3396-8465-3775ce66ff60的类方法元数据确认，
_MTLLibrary确实存在newFunctionWithName:constantValues:pipelineLibrary:error:，
编码为@48@0:8@16@24@32^@40。0x181a3df8c处的原版方法向pipelineLibrary发送
functionCache，再转入包含缓存参数的函数创建入口；普通三参数入口传入空缓存。

_MTLConstantDataSize在0x181a33650查表，type51对应0x181b558d8的值是3。
单值setter先以此大小分配内存再memmove；indexed/named data getter返回存储指针。
范围setter对三分量输入使用四分量步长，但每个已储存常量仍只复制紧密的3字节。
现有前端读取的是原版已储存对象，必须向Rust传入3字节，不能把它改成uchar4或传padding。

函数边界、原版字节位置、方法编码和限定反汇编在analysis/metal-library-20f66-v178。
REA报告本地macOS工具不可用、Ghidra缺失，本次复用既有Capstone/共享缓存解析器读取
原始指令；这是本地静态证据，不是REA反编译或运行时参数跟踪。

## 修改与构建

tools/build_nabu_gpu_metal_probe.py的显式--system-shaders模式在派生前端中只增加
type51的3字节支持，并增加原版pipelineLibrary重载。后者保持原始函数名与常量，使用
已有真实特化/编译路径和运行库缓存；不返回假的函数或伪造Apple GPU缓存命中。
原25项runtime补丁、IOSurface统计与iOS复制读取补丁继续保留，不改内核、Turnip或shader语义。

现有Rust canon/fc.rs已将UChar3识别为三个8位分量，要求3字节并拒绝4字节，故无需
修改Rust源码。CI172没有保留静态链接库，本轮需重新生成一次；新构建将保留.a及派生
前端源码，供后续前端修复直接重链。

构建源码638cbd2，专项CI42653980143；构建、产物与后续真机结果以
log/host/gpu-v178/continuation.json为准。尚未将修复候选当作实机通过。

## 2026-11-10构建与部署准备

专项CI42653980143 attempt1完整成功，产物源码与638cbd2一致。新前端18,109,936字节，
普通ARM64、iOS16.5目标、4KiB段及签名页验证通过，依赖均存在于本机20F66系统。
220,101,904字节Rust静态库和派生前端源码已保留，后续前端修改可直接重链。

与CI42650459047已合格的系统工厂/启动等待器组合，生成
artifacts/nabu-bootstrap-gpu-v178/bootstrap.apfs（67,956,736字节）。APFS检查与12项
文件读回通过，保留display01内核和原版桌面可执行文件。新日志槽1已准备并读回；
根据前文设备释放及继续测试授权，开始部署和临时启动，不额外重启Android。
运行中结果另记，不把构建成功作为系统着色器或桌面加速通过。

## 第178轮实机结果

2026-11-10部署及临时启动完成，用户确认黑屏、进不了桌面。原版消费者通过系统工厂
取得前端；完整日志内没有再次出现type51拒绝或pipelineLibrary selector异常。媒体进程
9次因NBTexture makeAliasable缺失abort；backboardd 14/167/187/197/207各发生一次
SIGSEGV，由异常处理器发送，5次均在QuartzCore fence超时后退出。该fence值是
(PID << 32) | 2，尚不能归为硬件GPU fence，也不能断言媒体错误造成桌面崩溃。
原生崩溃通知EXC_CORPSE_NOTIFY返回error5，现有日志没有故障PC/LR或用户栈。
后续媒体进程165另有Vulkan设备创建失败，原因未闭合。

设备恢复Android后，8,972,301字节连续有效日志前缀和完整64MiB槽1均已回收；捕获未写入
结束标记，不能将前缀称为完整运行时日志。槽已清空并读回，APFS150→151 fullfsync=ok，
Android引导分区未变。原生syslog共21,830,199字节；普通测试App未安装或执行。
证据见log/host/gpu-v178/backboard-crash-review.json、runtime-evidence.json和设备原始日志。

下一轮将资源API接入已有真实Rust实现，同时仅在backboardd设置一次SIGSEGV诊断：
记录原故障地址、ARM64寄存器和事先枚举的镜像地址，随后保留默认信号终止。此诊断
不是桌面修复；资源修复与桌面故障分别验证。
