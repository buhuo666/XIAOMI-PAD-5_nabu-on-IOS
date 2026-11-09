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
