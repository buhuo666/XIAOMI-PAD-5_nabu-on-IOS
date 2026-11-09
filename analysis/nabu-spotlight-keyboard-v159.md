# 第159轮：Spotlight 键盘高度修复

2026-11-09，Asia/Shanghai。

用户最初描述为设置左侧搜索框，随后纠正：实际是桌面下拉的Spotlight系统搜索。
搜索框有光标，底部只有工具条，键盘按键不显示；其他位置输入正常。

第158轮先对Preferences加入只读布局观测。实机设置搜索返回800x258的按键布局，
最终UIKeyboardDidShow为800x320，显示正常。这轮观测已撤回，不加入最终修复。

同一轮原生syslog直接捕获Spotlight[166]：SPUITextField正常becomeFirstResponder，
输入视图进入OnScreen，但UIKeyboardAutomatic仅800x7，工具条800x55，最终
UIKeyboardWillShow/DidShow为800x62。证据：
`log/host/settings-search-v158/spotlight-size-evidence.txt`。

根因是键盘尺寸适配没有覆盖Spotlight进程。当前inject.conf只列SpringBoard、
Preferences、MobileNotes等程序，桌面搜索实际在独立Spotlight进程中运行。
原版20F66对800x1280没有匹配的iPad尺寸行，派生键盘提交0高度；已在第74/75轮
验证的修正把这个0替换为原版-1哨兵，保留已加载基础布局高度。该修正已经使设置
和备忘录正常，但此前没有注入Spotlight。

本轮只在生产打包器的既有体验适配进程列表加入Spotlight，复用已验收的适配库，
不改全局屏幕大小、输入焦点或输入法偏好。移除第158轮临时Preferences观测代码。
新bootstrap基于第154轮音频版本，内核沿用第157轮471c32d，保留用户验收的+16dB
和麦克风。仅修改inject.conf，运行结果仍需桌面搜索实测。

验收要求：桌面下拉显示完整键盘；中英文可输入、删除；退出搜索再进入仍正常；
原生日志确认Spotlight加载适配并取得非零按键布局高度。

后续第159/160轮黑屏由Windows打包把inject.conf写为CRLF引起，与新增Spotlight
选择器本身无关。第161轮保留Spotlight并修正字节写入，用户确认桌面、搜索键盘和输入
正常。详见[nabu-spotlight-black-screen-v161.md](nabu-spotlight-black-screen-v161.md)。
