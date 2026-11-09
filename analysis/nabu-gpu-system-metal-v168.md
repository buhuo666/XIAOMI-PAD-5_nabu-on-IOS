# 第168轮：标准Metal工厂内核薄层

本轮在第167轮独立Metal实机通过的后端上增加系统工厂发现服务。这里只完成内核
编译和离线检查，尚未证明`MTLCreateSystemDefaultDevice`实机返回设备，也未接入
IOSurface、显示提交或桌面GPU渲染。

## 实现

- `tools/build_nabu_gpu.py --system-metal`隐含`--userland`，增加
  `NABU_GPU_SYSTEM_METAL=1`和一个`NativeAdrenoAccelerator.cpp`编译单元。
  不设置`NABU_GPU_METAL`，不启用缓存页导入或scanout。
- `patches/nabu-gpu/NabuGpuAcceleratorABI.h`声明当前源码内核
  `MiniIOMobileFramebuffer.cpp`已经定义的具体`IOAcceleratorES`类，136字节。
  基类构造、析构和元类由现有符号名绑定，不加载原版IOGPUFamily。
- `AGXAccelerator`只发布`MetalPluginName=NativeAdrenoMetal`和
  `MetalPluginClassName=NativeAdrenoMetalDevice`，不添加sandbox授权或chip属性。
  `newUserClient`转发既有传输，其`0x4147`路径保持不变，原版type1仍被拒绝。
  进程准入由用户态bundle负责。
- 发布位置仍在GPU scratch/fence自检完成、NativeAdreno传输就绪之后。
  `native-adreno-metal=0`仍可关闭此服务发布。
- 两份类初始化在同一个`preModLoad`/`postModLoad`事务内显式调用。
  构造开始后保存注册结果；重复成功调用返回busy，注册失败不会再次构造。
  仅`preModLoad`本身失败且未运行构造时允许重试。

## 验证结果

构建命令：

```text
python tools/build_nabu_gpu.py --compile-command artifacts/nabu-device-objects-v162/compile-command.json --output artifacts/nabu-gpu-v168 --system-metal
```

- 37个ARM64 iOS16.5单元全部编译通过。
- 相比v165，GPU对象整体仅新增3个外部引用，均来自已有源码内核：

| 符号 | 当前内核解析结果 |
| --- | --- |
| `__ZN15IOAcceleratorES10gMetaClassE` | `0xfffffff007de1ed8` |
| `__ZN15IOAcceleratorESC2EPK11OSMetaClass` | `0xfffffff007a1d880` |
| `__ZN15IOAcceleratorESD2Ev` | `0xfffffff007a1d8c0` |

地址仅记录检查结果，实现按符号名引用。检查对象为
`artifacts/nabu-services-prelink-v164/kernel.native-apfs.macho`的实际导出表。
新shim全部184个引用均能由内核导出或本组GPU对象提供；不需要修改链接器。

- 37个对象中无自动`__mod_init_func`或section type9。
  Publish和Accelerator各有一个8字节`__nabu_init`，类型0，初始化函数为external。
  Publish文本段分别存在一次对两份初始化函数的直接分支重定位。
- GPU context没有`enableCachedCoherentImports`引用；service没有scanout引用。
- 单独按原有USERLAND配置重新编译Publish通过，产物无Accelerator符号。
- 提取实际初始化函数执行6个宿主场景：SYSTEM_METAL开/关下的重复成功、注册失败、
  首次preModLoad失败；每份启用的类构造均只执行一次。

证据：`artifacts/nabu-gpu-v168/build-report.json`、
`log/host/gpu-system-metal-v168/report.json`、
`log/host/gpu-system-metal-v168/shim-imports.json`。

父任务已完成62个对象的本地链接，无未解析引用；8,954个直接分支、2,693个远分支、
530个veneer的目标检查通过，48个原组件地址区间保留。return-trace及实际DarwinBoot
镜像解析/布局ASan、UBSan检查通过。候选为
`artifacts/nabu-gpu-trace-v168/kernel.native-apfs.macho`；证据位于
`log/host/gpu-v168/branch-decode-check.json`、`link.log`及`kernel-window/report.json`。

第167轮基线保留；第168轮设备日志槽14已准备，系统Metal实机结果待后续记录。
