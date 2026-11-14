# 应用键盘覆盖和布局查询

2026-11-14。用户曾报告输入法再次弹不出。主代理补齐旧 i4-12 的 `libnabu.experience.dylib` 精确名单后，用户已确认 Sileo 键盘可用；尚未验收其它应用。原静态缺口是名单只有 SpringBoard、Preferences、Spotlight、MobileNotes、Reminders、MobileSafari、PaperBoard、PosterBoard、LegacyPoster、LocalTest，未包含 Sileo、TrollStoreLite、TrollApps。

第159/161轮的历史实测已有相同漏进程案例：Spotlight 获得焦点但按键布局高度为0，仅工具条可见；补齐它的注入后用户确认恢复。现有生产修正只把 Nabu 的零派生高度替换为原版 `-1` 哨兵，让 UIKit 保留基础 UIKBTree 的高度。没有理由把其它屏幕尺寸或非零高度一并改掉。

## 键盘专用库

新增 `keyboard_compat.c`、`keyboard_compat.h` 和纯规则 `keyboard_geometry.h`。产物为 `libnabu.keyboard.dylib`。

- 只链接 libobjc 和 libSystem，不链接或显式加载 UIKit、Foundation、WallpaperKit。
- dyld image 回调只安排主队列检查；constructor和回调不发送 `UIScreen.mainScreen` 消息。
- `UIKBDerivedKeyboard` 及 `setKeyboardSize:` 都出现后才安装。方法不存在时保持未安装，后续 image 回调可重试。
- 实际 setter 遇到 `width>0,height==0` 时，才查询已有 UIScreen 的 nativeBounds 和 scale。只匹配 scale2、1600×2560或2560×1600，提交height=-1。
- 安装幂等；当前IMP已是本库时不再次接链。如果当前IMP来自既有 `libnabu.experience.dylib`，记录被已验收修正覆盖，不重复安装。
- 非零高度、原有-1哨兵、零或负宽度、其它屏幕和比例保持原值。

该库供新内核显式 wildcard 规则使用；当前旧内核精确列表的补齐由主代理处理。这里未操作设备或更改旧经验库。

## 进程内布局查询

`BOOL nabuKeyboardLayoutAudit(NSString *outputPath)` 位于 `keyboard_layout_audit.m/.h`。UIKit应用或链接UIKit的独立命令程序均可在进程主线程调用一次；不要求 `UIApplicationMain`。YES仅表示JSON写成功。

查询使用既有诊断中实际调用过的私有API：`UIKBScreenTraits traitsWithScreen:orientation:`、`UIKeyboardLayoutStar keyboardSizeForInputMode:screenTraits:keyboardType:`，以及 `TUIKeyboardLayoutFactory keyboardWithName:inCache:`。不替换 UIScreen 方法，也不改用户输入法偏好。

当前阶段和候选零高度规则阶段，各查询英语QWERTY、中文拼音的竖屏1/横屏3及0至11键盘类型，共96条。每条记录返回尺寸、类型、派生setter的请求/提交尺寸、图布局名称、异常或缺失API。候选阶段没有正高度的项目单独列出。

临时观测方法在同步查询结束后恢复。候选规则与生产库使用同一纯函数；已有修正已生效的当前阶段被明确标记，不能称为未修正基线。

缓存及覆盖限制：

- `has_positive_height` 仅表示此次尺寸查询返回正宽高。
- `candidate_rule_exercised` 只有观察到真实setter的0→-1提交才为true。
- 查询结果为正但没有此转换，会计入 `positive_candidate_queries_without_rule_exercise`，不能据此宣称修正规则已经实测。
- 不调用未知私有缓存清除接口；没有setter事件可以是缓存或其它路径，报告不把它确定命名为缓存命中。
- 查询使用当前屏幕生成的标准traits，不是所有浮动/拆分/硬件或第三方输入法变体，更不等同键盘视觉显示与输入验证。

## App5旧画布和独立探针

App5实机报告 `log/host/jailbreak-20261114/setup-05/result-01/keyboard-layouts.json` 共有96项正尺寸，但屏幕bounds为768×1024、nativeBounds为1536×2048、scale为2，派生setter事件和候选规则触发数均为0。它验证了旧画布尺寸查询可运行，不能验证Nabu的800宽零高度问题。

同轮Sileo日志有真实 `{800,0}` 保留基础高度记录，且用户确认可输入。已有 `libnabu.experience.dylib` 源码与挂载产物都只读取UIScreen几何，没有覆写UIScreen方法，因此不能把“给Setup加入experience”当作纠正应用画布的办法。

历史 `services-v71/continuation.json` 已记录：带编译LaunchScreen.storyboard的LocalTest仍是旧画布，而同一轮非.app的system-service-probe在UID501下得到bounds800×1280、native1600×2560及原始零高度。此次不重复增加启动画面，沿用该独立主线程UIKit查询上下文。

新增 `userland/nabu/src/keyboard_layout_probe.m`，产物 `nabu-keyboard-layout-probe`。调用固定为：

```text
nabu-keyboard-layout-probe --output <json> [--keyboard-library <path>]
```

`tools/build_nabu_keyboard_compat.py --output artifacts/nabu-keyboard-compat` 同时产出轻量库、audit对象和已adhoc签名的probe。probe单独链接Foundation/UIKit，不含experience实现，不加entitlement；audit对象不进入通用注入库。原始编译调用为：

```text
xcrun --sdk iphoneos clang -target arm64-apple-ios16.5 -isysroot <sdk> -Os -g -Wall -Wextra -Werror -fobjc-arc -fblocks -Wno-deprecated-declarations userland/nabu/src/keyboard_layout_probe.m <output>/keyboard_layout_audit.o -framework Foundation -framework UIKit -o <output>/nabu-keyboard-layout-probe
codesign --force --sign - --timestamp=none <output>/nabu-keyboard-layout-probe
```

主代理负责复制到可执行的原生APFS前缀、probe权限0755及库权限0644；必须在任何.app目录之外运行。保留库的basename `libnabu.keyboard.dylib`，使报告中的映像身份与当前IMP身份可直接比较。输出目录预先允许UID501写入。

1. UID501全新进程，不传library：保存 `keyboard-native-layouts.json`，记录真实当前阶段和候选规则阶段。
2. UID501另一个全新进程，传 `--keyboard-library <原生前缀>/libnabu.keyboard.dylib`：保存 `keyboard-native-library.json`，验证真实轻量库的安装与当前阶段修正计数。
3. 安装器自身报告可另存 `keyboard-app-layouts.json`，作为旧画布对照。

独立入口不调用UIApplicationMain，按历史探针顺序先读取真实UIScreen，再dlopen TextInputUI。library模式随后只加载指定轻量库，并在主线程显式调用 `nabu_keyboard_install_now`。这验证真实库代码的键盘修正，不等同通用注入时constructor/main-queue调度已验证。两个模式结束后主代理可删除临时可执行文件与库；保留JSON和退出码。退出0只表示JSON成功写出，64为CLI参数错误，69为框架/库载入或显式安装失败，74为JSON写入失败。

报告version2新增：

- `nabu_screen_geometry_observed` 仅在实际scale2及native1600×2560（任一方向）时为true；默认false，异常或缺失API不能产生伪阳性。
- `all_nabu_query_dimensions_positive` 要求该geometry gate且全部96项返回正宽高；包含当前及候选两个阶段。
- `all_nabu_candidate_query_dimensions_positive` 要求同一gate且候选48项全部正宽高，便于区分“基线零高度、候选成功”的情况。
- 原 `all_candidate_queries_positive_height` 保留为不限定Nabu的候选尺寸观察；不能单独作为Nabu修复通过依据。
- `candidate_rule_exercised_query_count` 继续单独统计审查候选setter实际0→-1转换。
- `lightweight_rule_corrections` / `lightweight_rule_exercised` 从真实轻量库计数器逐查询前后读回；当前阶段累计为 `current_lightweight_rule_exercised_query_count` 与 `current_lightweight_rule_exercised_positive_query_count`。候选观测器自身做的转换不会被计入轻量库计数。
- `experience_library_loaded`、`lightweight_library_loaded`、`loaded_adapter_images`、`lightweight_adapter_before/after` 与当前setter的IMP映像共同说明本进程实际载入和安装情况。
- `uid` / `euid`、`main_bundle_path`、`main_bundle_is_app` 记录实际执行上下文；数值bounds/native_size同时保留，UIScreen和用户输入偏好不被修改。

两次非.app实机结果仍待App6。只有原生几何、正尺寸和对应真实规则触发证据同时成立，才可称相应查询验证了修正；仍不能声称全部应用、全部布局或实际文本输入均已通过。

## 检查

`tools/check_nabu_keyboard_compat.py` 已在主机通过300组几何边界和NaN保留测试，ASan/UBSan通过。证据为设备资料目录的 `log/host/jailbreak-20261114/keyboard-01/geometry-host/host-check.json`。这仅验证生产纯函数。

App5的CI43586744462/源码574a04a已完成轻量库和原audit对象的iOS SDK编译签名。构建读取真实 `otool -L`，确认通用库依赖仅自身install_name、libobjc、libSystem。

本轮新probe、geometry gate和真实库计数报告仍待App6的ARM64 SDK编译及设备运行；本地Python AST解析和改动空白检查通过，未重复已通过的300项纯规则测试或产物哈希审计。
