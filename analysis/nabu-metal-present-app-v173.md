# 第173轮 UIKit + CAMetalLayer App：复用、构建和回收

2026-11-09。第172轮默认IOSurface复制兼容已实机通过：Mach读取16KiB、32个epoch、
64个command buffer、双向各32768像素零错误，导入释放1/1、held0。下一步是一个实际
UIKit App中的单次CAMetalLayer呈现；本文件同时记录已有App链路证据和本次构建工具。
App源码由主任务持有，本子任务没有修改它，也没有安装、启动App或派发CI。

## 已验证且可复用的App链路

| 文件/证据 | 可复用内容 |
| --- | --- |
| `userland/nabu/apps/LocalTest/main.m` | UIApplicationMain、UIWindow/UIViewController、按钮、真实Documents和原子状态写入 |
| 同目录 `LaunchScreen.storyboard` | 标准启动屏，由ibtool编译；本次直接复用输入 |
| `tools/build_nabu_test_app.py`、`local-test-app.yml` | Xcode16.4、arm64/iOS16.5、自有ad-hoc IPA构建 |
| `tools/install_nabu_test_app.py` | 配对USB/TLS、AFC PublicStaging、原版installation_proxy Install/Uninstall/Lookup及暂存清理 |
| `tools/read_nabu_test_documents.py` | 原版house_arrest VendDocuments和AFC文件回收 |
| `tools/probe_nabu_system_services.py:afc_read` | 按真实文件长度读取指定文件并关闭句柄 |
| `docs/NABU-LOCAL-ACTIVATION.md:62–99` | 第62轮安装/桌面图标启动/写入；第63轮Documents数据回收；第64轮卸载、重装及新容器实测 |

安装工具的 `installed_verified` 来自原版代理Complete/Lookup，`launch_verified`仍为false。
项目已验证的正常launch是用户点SpringBoard图标；没有找到已经验证的自动launch入口。
本次继续正常图标启动，不以LaunchDaemon执行UIKit程序或另建私有启动通路。
LocalTest的keyboard_diagnostic和experience_compat是键盘/壁纸实验内容，本App只用普通
按钮，不编入这些额外hook。

## App身份、链接和签名

新增构建器 `tools/build_nabu_metal_present_app.py`，参数为 `--input` 合格runtime目录和
`--output`。输入固定为CI42615860281 / `nabu-gpu-iosurface-copy-read-2`，其前端是第172轮
实际使用的862987a源码产物。原生库仅作为已合格输入使用，不重建Rust、Turnip或前端。

| App项 | 值 |
| --- | --- |
| Bundle ID / 目录 | org.nabu.MetalPresent / Payload/MetalPresent.app |
| CFBundleExecutable | nabu-gpu-metal-probe |
| 显示名 | GPU呈现测试 |
| 平台 | arm64-apple-ios16.5，_MTLDevice实例大小528 |
| 方向 | Portrait、PortraitUpsideDown，iPad全屏 |
| 编译 | Xcode16.4，C++17、ARC、blocks、-Wno-deprecated-declarations |
| Frameworks | UIKit、Foundation、Metal、QuartzCore、IOSurface |
| 新IPA | NabuMetalPresent.ipa |

当前工厂检查的是完整libc basename，故App可执行文件继续使用 `nabu-gpu-metal-probe`，
无需修改或扩大其它进程准入。Bundle ID和App目录则独立于LocalTest及命令行probe。

链接器只给 `LC_RPATH=/redwood/sbin`，依赖为
`@rpath/libnabu-metal-frontend.dylib`。工厂随后固定
`dlopen("/redwood/sbin/libnabu-metal-frontend.dylib", RTLD_LOCAL)`，两者解析到同一个
实际路径，使用同一份进程内gDevice。前端和Turnip都不复制到App/Frameworks中。
原Turnip继续由前端在 `/redwood/sbin/libvulkan_freedreno.dylib` 加载。
`nabu-iosurface-smoke.metallib`原样复制到App根，供NSBundle获取。
构建后otool检查唯一rpath及前端依赖，不重签旧native库。

App仅带原probe已经使用的两项GPU entitlement：

```text
com.apple.security.iokit-user-client-class = [AGXDeviceUserClient]
com.apple.security.ts.opengl-or-metal = true
```

不携带daemon使用的 `com.apple.private.security.no-container`，不添加安装/启动/调试权限。
前述两项在旧probe的三项集合中已实测使用；保留容器的新App组合仍待本轮实测，不能说已
单独证明每个key必需。LocalTest本身以无额外entitlement的ad-hoc签名安装运行成功。
本构建对新App做4KiB页ad-hoc签名、strict verify和实际entitlements回读；无profile、证书
或网络/ATS放宽配置。

## 生命周期和测量边界

主任务App源码为 `userland/nabu/apps/MetalPresent/main.mm`：普通UIView中放约320pt方形
CAMetalLayer，drawableSize32×32、BGRA8Unorm、framebufferOnly=NO；用已通过metallib的
vertex/color函数做一次绘图。读回1024个真实像素并确认command完成后才调用drawable的
present，保持图案供用户确认，不启动持续刷新或全屏桌面替换。

UIKit/CA可能在主动测试前查询进程级Metal设备，因为App的basename已经准入。因此记录
从 `main`、`ui_application_main`、`did_finish_launching`、window/view开始的阶段；
main先建立Documents记录并设置前端problem observer。随后独立记录工厂、layer配置、
nextDrawable进出、GPU提交/读回、present_request、awaiting_user及remove_layer。
若dyld在main前失败，则需结合原生系统日志，不能把缺少结果文件直接归因为GPU绘图失败。

GPU完成、读回匹配、present调用返回、presentation callback和用户实际看到图案是不同
证据。`presentedTime`/回调不代替用户视觉确认；独立IOSurface通过也不证明CA已经显示。
只在本App内观察真实调用，不修补或伪造其它消费者的能力。

移除图层操作先停止后续工作；已有GPU工作完成后移除superlayer引用，释放drawable和
layer/device引用、flush CA，再trim并记录导入释放情况。若正在执行，源码记录
`removal_waiting_for_gpu`，不强制归还仍在用的资源。进入后台也请求同一移除流程，
普通UIKit界面和返回桌面操作保留。统计是整个App进程的累计值，UIKit提前发生的Metal
活动也可能计入，应结合阶段与基线解释，不能只凭一次计数就推导实际显示完成。

## App容器与现有缓存路径

RunningBoard为普通App设置 `CFFIXED_USER_HOME`，Foundation据此选择Data容器；
`kern_minimac.c:126–145`明确实现该容器查询。LocalTest的实际安装、Documents写入及
house_arrest回读证明了这条链路。本App结果放真实Documents，不转放Media替代容器。

工厂当前仍创建 `/var/mobile/Media/NabuMetalCache`。当前Sandbox stand-in没有真实profile
约束，但这不是新容器App已经成功访问该目录的实机证据。新App应记录工厂失败及错误；
本次builder不改工厂、不搬入no-container。如果确认是该路径的实际权限拒绝，再单独修改
工厂按App的NSCachesDirectory选择缓存；不预先给宽泛权限。

bootstrap复用第172轮native文件及标准bundle，只保留root mount helper；不同时运行
同basename的旧daemon GPU probe。装载ready门槛与helper的bindfs专用权限保持原样。

## 安装、启动、回收与移除

现有安装工具新增明确参数，默认值仍为LocalTest，协议栈不复制：

```text
python tools/install_nabu_test_app.py --ipa <产物目录>/NabuMetalPresent.ipa \
  --bundle-id org.nabu.MetalPresent --app-name MetalPresent --output <安装日志目录>
```

工具读取 `Payload/MetalPresent.app/Info.plist`，要求identifier与参数一致；通过原版
installation_proxy安装，保存Complete/Lookup及容器结果。随后由用户从桌面图标启动，
确认图案、普通按钮与移除后回到普通UI。不是从PC直接执行App二进制。

reader新增 `--bundle-id` 和三个明确文件名，旧默认ID及两项原文件选择保持：

```text
python tools/read_nabu_test_documents.py --bundle-id org.nabu.MetalPresent \
  --output <回收目录> metal-present-result.json metal-present-readback.bgra metal-present-readback.json
```

这仍是house_arrest的VendDocuments，不读取其它App或全盘数据。JSON记录run_id，实际BGRA
和metadata同轮对应。`--output`由主任务指定新的轮次目录。
App不再需要时，可用同一安装工具 `--uninstall --bundle-id org.nabu.MetalPresent
--app-name MetalPresent`；应先回收结果，卸载会移除该App的数据容器。

用户已禁止额外Android reset；构建/安装/文档回收不要求额外Android重启。设备操作仍由
主任务按当前状态安排，必要的临时启动只切bootloader。

## CI和本地检查

新workflow `.github/workflows/gpu-metal-present-app.yml` 只下载上述合格runtime、获取nabu
ABI头并编译App；artifact为 `nabu-metal-present-app-<run_number>`，内容
`nabu-metal-present-app/`。主任务统一提交后可派发：

```text
gh workflow run gpu-metal-present-app.yml --ref nabu16-bootstrap
```

本地Python、YAML、Info.plist/签名权限配置、单一rpath/不内嵌native库的构建命令，以及
installer/reader的新旧参数解析检查通过，没有连接设备服务。记录为
`log/host/metal-present-app-v173/source-check.json`。原生编译、签名、安装和CAMetalLayer
呈现仍需新CI及实机，源码/主机检查不替代这些验收。
