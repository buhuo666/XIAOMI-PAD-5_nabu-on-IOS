# 20F66 Metal 基类布局

2026-11-09。为第166轮Vulkan通过后的独立Metal移植，直接读取现有原版20F66共享缓存
中的Objective-C类元数据。没有再次下载或做原文件哈希审计，也没有执行目标代码。

`/System/Library/Frameworks/Metal.framework/Metal`的UUID为
`88922408-fd68-3396-8465-3775ce66ff60`，Mach-O位于`0x181a0a000`。
遍历其313个`__objc_classlist`条目，按每个映射的dyld v2 slide mask解码指针，
再读取`class_t`→`class_ro_t`的名称、instanceStart和instanceSize。

| 类 | instanceStart | instanceSize |
| --- | ---: | ---: |
| `_MTLDevice` | 8 | 528 |
| `MTLSharedEventHandle` | 8 | 16 |
| `MTLSharedEventListener`公共基类 | 8 | 8 |

`_MTLDevice`类地址为`0x1e1b2dc98`，只读元数据地址`0x1d56991a8`，
对应`dyld_shared_cache_arm64.27.dylddata`文件偏移889256。原始元数据的instanceSize
为528，与17.7参考前端硬编码536不一致。派生前端应以528为明确的20F66目标，
独立probe仍须在运行时输出并核对`class_getInstanceSize`。

`NativeBridgeMetalFrontend.mm`通过动态子类继承原版`_MTLDevice`，不增加实例变量。
此布局证据仅解决其已存在的基类尺寸门槛，不能代替Metal方法、协议或GPU结果实测。
`OfflineMetalFrontend`的24字节shared-listener门槛属于另一实现；本次公共基类的
静态尺寸不能当作其具体运行时子类尺寸。

完整地址/文件范围见[nabu-metal-base-20f66.json](nabu-metal-base-20f66.json)，
解析脚本为`log/host/metal-20f66/read-classes.py`。Metal实际buffer、compute和render
测试尚待构建及实机运行。
