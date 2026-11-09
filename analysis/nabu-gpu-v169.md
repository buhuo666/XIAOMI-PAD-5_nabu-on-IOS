# 第169轮：标准Metal设备发现与真实GPU测试通过

2026-11-09，用户确认桌面、触摸正常并恢复Android。系统标准
`MTLCreateSystemDefaultDevice()`首次调用返回`NativeBridgeMetalDevice`，
设备名为Turnip Adreno (TM) 640，registry ID4294967767与AGX服务一致；
薄插件入口仅调用一次。运行时`_MTLDevice`为528字节。

| 实际测试 | 结果 |
| --- | --- |
| MTLBlit填充及未写区域 | 4096字节正确 |
| MTLCompute输出与保护区 | 1024字、128保护字正确 |
| MTLRender像素 | 1024正确，红256，其他颜色0 |
| 行间保护 | 4096字节正确 |
| 命令完成 | 3个Completed，进程结果pass |
| 实际读回 | 4096字节RGBA、JSON及PNG已保存 |

只读bindfs union挂载、原AGXMetalA10.bundle节点保留及新bundle字节读回均通过。
本轮仅给挂载助手签入`com.apple.private.bindfs-allow=true`，修复第168轮EPERM。
当前工厂仅准入测试进程，此结果不表示桌面或普通应用已经使用GPU。

## 输入与证据

- 用户态源码`f6176d09d893916ee3de027700fadc6e069d94b6`，CI42603179764成功；
  同提交的完整内核检查CI42603180039成功。
- 实际内核复用`artifacts/nabu-gpu-trace-v168/kernel.native-apfs.macho`，GPU源码
  `6ffb65ce137eaeabbfd0997165d9fcfe6854bbde`，没有本轮内核改动。
- 前端、Turnip及metallib复用CI42590211952的已验证字节；挂载助手签名回读仅有
  所需bindfs键。bootstrap为`artifacts/nabu-bootstrap-gpu-v169/bootstrap.apfs`。
- `log/host/gpu-v169/metal-runtime/probe-result.json`记录真实测试计数；
  `mount-result.json`记录挂载结果。`artifacts/nabu-metal-render-v169/`包含实际像素。
- `log/device/nabu-boot-20261109-169/runtime-log/`保存3,074,483字节连续日志及
  完整64MiB槽；槽14清空读回通过，APFS138→139、fullfsync=ok。
  日志没有最终sealed记录，按已捕获连续前缀保存，不声称包含关机后的内容。

初始化期间仍记录六个未回答能力：gpuCoreCount、maxVertexAmplificationCount、
maxComputeThreadgroupMemory、isLargeMRTSupported、supportsComputeCompressedTextureWrite、
supportsConditionalLoadStore。本轮实际测试没有缺失selector或错误，不凭本轮结果
为这些能力填入未经验证的值。

下一步按`nabu-iosurface-validation-plan-v168.md`验证NC wrapped IOSurface真实导入、
双向像素、重复修改和释放，记录import/copy/shadow计数；普通WB、跨进程及呈现后置。
用户在本轮后明确取消后续额外Android重启，后续部署遵循该新约束。
