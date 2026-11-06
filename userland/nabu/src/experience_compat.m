/* Nabu's 800x1280 logical display has no entry in 20F66's iPad size table. */
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#include <dlfcn.h>

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
    // UIKit's generic-iPad branch submits CGSizeZero.height for this display.
    // -1 is the original caller's sentinel for retaining the loaded UIKBTree height.
    if (size.height == 0 && size.width > 0 && isNabuScreen()) {
        NSLog(@"NABU KEYBOARD: retain base layout height for %@", NSStringFromCGSize(size));
        size.height = -1;
    }
    originalKeyboardSize(object, selector, size);
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
    NSLog(@"NABU EXPERIENCE: hooks installed; screen check deferred to layout calls");
}

#ifdef NABU_EXPERIENCE_DYLIB
__attribute__((constructor)) static void installExperience(void) {
    @autoreleasepool { nabuInstallExperienceCompatibility(); }
}
#endif
