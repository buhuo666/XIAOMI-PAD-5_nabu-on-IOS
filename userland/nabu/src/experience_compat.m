/* Nabu's 800x1280 logical display has no entry in 20F66's iPad size table. */
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <string.h>
#include <stdlib.h>

static BOOL settingsKeyboardTrace;
static NSMutableArray *settingsKeyboardEvents;
static __weak UITextField *settingsEditingField;
static CGSize (*originalLayoutSize)(id, SEL, NSString *, id, NSInteger);

static void recordSettingsKeyboard(NSString *event, NSDictionary *details) {
    if (!settingsKeyboardTrace) return;
    if (!settingsKeyboardEvents) settingsKeyboardEvents = [NSMutableArray array];
    NSDictionary *entry = @{@"event": event, @"uptime": @(NSProcessInfo.processInfo.systemUptime),
        @"details": details};
    if (settingsKeyboardEvents.count == 256) [settingsKeyboardEvents removeObjectAtIndex:0];
    [settingsKeyboardEvents addObject:entry];
    NSDictionary *report = @{@"process": NSProcessInfo.processInfo.processName,
        @"pid": @(NSProcessInfo.processInfo.processIdentifier), @"events": settingsKeyboardEvents,
        @"scope": @"Settings layout/focus observations; no entered text collected; input behavior unchanged"};
    NSString *path = @"/private/var/mobile/Media/NabuServices/settings-keyboard.json";
    NSData *data = [NSJSONSerialization dataWithJSONObject:report options:0 error:NULL];
    NSError *error = nil;
    BOOL saved = [data writeToFile:path options:NSDataWritingAtomic error:&error];
    NSLog(@"NABU SETTINGS KEYBOARD: %@ saved=%d error=%@", entry, saved, error ?: @"");
}

static NSDictionary *settingsViewGeometry(UIView *view) {
    return @{@"class": NSStringFromClass(view.class), @"frame": NSStringFromCGRect(view.frame),
        @"bounds": NSStringFromCGRect(view.bounds), @"hidden": @(view.hidden), @"alpha": @(view.alpha)};
}

static void settingsKeyboardSnapshot(NSString *event) {
    UITextField *field = settingsEditingField;
    NSMutableDictionary *details = [NSMutableDictionary dictionary];
    if (field) {
        NSMutableArray *ancestors = [NSMutableArray array];
        for (UIView *view = field; view; view = view.superview) [ancestors addObject:settingsViewGeometry(view)];
        details[@"field"] = @{@"first_responder": @(field.isFirstResponder),
            @"keyboard_type": @(field.keyboardType), @"return_key_type": @(field.returnKeyType),
            @"input_view_class": field.inputView ? NSStringFromClass(field.inputView.class) : @"nil",
            @"ancestors": ancestors};
    }
    NSMutableArray *windows = [NSMutableArray array];
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class]) continue;
        UIWindowScene *windowScene = (UIWindowScene *)scene;
        for (UIWindow *window in windowScene.windows) {
            NSMutableDictionary *item = [settingsViewGeometry(window) mutableCopy];
            item[@"key"] = @(window.isKeyWindow);
            item[@"level"] = @(window.windowLevel);
            item[@"scene_bounds"] = NSStringFromCGRect(windowScene.coordinateSpace.bounds);
            item[@"orientation"] = @(windowScene.interfaceOrientation);
            item[@"screen_bounds"] = NSStringFromCGRect(window.screen.bounds);
            item[@"native_bounds"] = NSStringFromCGRect(window.screen.nativeBounds);
            [windows addObject:item];
        }
    }
    details[@"windows"] = windows;
    recordSettingsKeyboard(event, details);
}

static CGSize settingsLayoutSize(id object, SEL selector, NSString *mode, id traits, NSInteger type) {
    CGSize size = originalLayoutSize(object, selector, mode, traits, type);
    recordSettingsKeyboard(@"layout_size", @{@"mode": mode ?: @"", @"keyboard_type": @(type),
        @"traits": [traits description] ?: @"", @"size": NSStringFromCGSize(size)});
    return size;
}

static void installSettingsKeyboardTrace(void) {
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    [center addObserverForName:UIApplicationDidFinishLaunchingNotification object:nil queue:NSOperationQueue.mainQueue
        usingBlock:^(__unused NSNotification *note) { settingsKeyboardSnapshot(@"application_ready"); }];
    [center addObserverForName:UITextFieldTextDidBeginEditingNotification object:nil queue:NSOperationQueue.mainQueue
        usingBlock:^(NSNotification *note) {
            settingsEditingField = note.object;
            settingsKeyboardSnapshot(@"field_begin");
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), dispatch_get_main_queue(), ^{
                settingsKeyboardSnapshot(@"field_after_one_second");
            });
        }];
    [center addObserverForName:UITextFieldTextDidEndEditingNotification object:nil queue:NSOperationQueue.mainQueue
        usingBlock:^(__unused NSNotification *note) { settingsKeyboardSnapshot(@"field_end"); }];
    for (NSString *name in @[UIKeyboardWillShowNotification, UIKeyboardDidShowNotification,
        UIKeyboardWillHideNotification, UIKeyboardDidHideNotification, UIKeyboardWillChangeFrameNotification]) {
        [center addObserverForName:name object:nil queue:NSOperationQueue.mainQueue usingBlock:^(NSNotification *note) {
            recordSettingsKeyboard(note.name, @{
                @"begin": NSStringFromCGRect([note.userInfo[UIKeyboardFrameBeginUserInfoKey] CGRectValue]),
                @"end": NSStringFromCGRect([note.userInfo[UIKeyboardFrameEndUserInfoKey] CGRectValue]),
                @"local": note.userInfo[UIKeyboardIsLocalUserInfoKey] ?: @NO});
            settingsKeyboardSnapshot(@"keyboard_windows");
        }];
    }
    Method layout = class_getClassMethod(NSClassFromString(@"UIKeyboardLayoutStar"),
        NSSelectorFromString(@"keyboardSizeForInputMode:screenTraits:keyboardType:"));
    originalLayoutSize = (CGSize (*)(id, SEL, NSString *, id, NSInteger))method_setImplementation(layout, (IMP)settingsLayoutSize);
}

static void (*originalKeyboardSize)(id, SEL, CGSize);
static BOOL (*originalWallpaperLoad)(id, SEL, NSURL *);
static BOOL (*originalIgnoreScreenClass)(id, SEL);
static __thread BOOL loadingNabuStill;

static BOOL isNabuScreen(void) {
    UIScreen *screen = UIScreen.mainScreen;
    CGSize native = screen.nativeBounds.size;
    return screen.scale == 2 && MIN(native.width, native.height) == 1600 &&
        MAX(native.width, native.height) == 2560;
}

static void setNabuKeyboardSize(id object, SEL selector, CGSize size) {
    CGSize requested = size;
    // UIKit's generic-iPad branch submits CGSizeZero.height for this display.
    // -1 is the original caller's sentinel for retaining the loaded UIKBTree height.
    if (size.height == 0 && size.width > 0 && isNabuScreen()) {
        NSLog(@"NABU KEYBOARD: retain base layout height for %@", NSStringFromCGSize(size));
        size.height = -1;
    }
    originalKeyboardSize(object, selector, size);
    if (settingsKeyboardTrace) recordSettingsKeyboard(@"derived_size", @{
        @"requested": NSStringFromCGSize(requested), @"submitted": NSStringFromCGSize(size),
        @"class": NSStringFromClass([object class])});
}

static BOOL ignoreNabuStillScreenClass(id object, SEL selector) {
    return loadingNabuStill || originalIgnoreScreenClass(object, selector);
}

static BOOL loadNabuStill(id object, SEL selector, NSURL *url) {
    BOOL previous = loadingNabuStill;
    loadingNabuStill = isNabuScreen() &&
        [url.path hasPrefix:@"/Library/Wallpaper/Stills/iPad/"] &&
        [url.pathExtension isEqualToString:@"wallpaper"];
    BOOL accepted;
    @try { accepted = originalWallpaperLoad(object, selector, url); }
    @finally { loadingNabuStill = previous; }
    return accepted;
}

void nabuInstallExperienceCompatibility(void) {
    static BOOL installed;
    // Run72: asking mainScreen here, during dyld constructors, aborts SpringBoard
    // before display initialization. Check geometry only inside live layout calls.
    if (installed) return;
    installed = YES;
    Method keyboard = class_getInstanceMethod(NSClassFromString(@"UIKBDerivedKeyboard"),
        NSSelectorFromString(@"setKeyboardSize:"));
    originalKeyboardSize = (void (*)(id, SEL, CGSize))method_setImplementation(keyboard, (IMP)setNabuKeyboardSize);
    dlopen("/System/Library/PrivateFrameworks/WallpaperKit.framework/WallpaperKit", RTLD_NOW);
    Method filter = class_getClassMethod(NSClassFromString(@"WKWallpaperBundle"),
        NSSelectorFromString(@"shouldLoadWallpaperBundleAtURL:"));
    Method ignore = class_getInstanceMethod(NSUserDefaults.class,
        NSSelectorFromString(@"wk_ignoreLogicalScreenClassForWallpaperBundle"));
    originalIgnoreScreenClass = (BOOL (*)(id, SEL))method_setImplementation(ignore, (IMP)ignoreNabuStillScreenClass);
    originalWallpaperLoad = (BOOL (*)(id, SEL, NSURL *))method_setImplementation(filter, (IMP)loadNabuStill);
    settingsKeyboardTrace = strcmp(getprogname(), "Preferences") == 0;
    if (settingsKeyboardTrace) installSettingsKeyboardTrace();
    NSLog(@"NABU EXPERIENCE: hooks installed; screen check deferred to layout calls");
}

#ifdef NABU_EXPERIENCE_DYLIB
__attribute__((constructor)) static void installExperience(void) {
    @autoreleasepool { nabuInstallExperienceCompatibility(); }
}
#endif
