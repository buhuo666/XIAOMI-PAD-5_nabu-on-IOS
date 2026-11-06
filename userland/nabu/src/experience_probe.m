/* Explicit, read-only queries for run70's About/keyboard/wallpaper failures. */
#import <UIKit/UIKit.h>
#import <objc/message.h>
#import <objc/runtime.h>
#include <dlfcn.h>

@interface NSObject (NabuExperienceQueries)
+ (id)sharedKeyboardFactory;
- (id)keyboardPrefixForWidth:(double)width andEdge:(BOOL)minor;
+ (id)traitsWithScreen:(UIScreen *)screen orientation:(NSInteger)orientation;
+ (CGSize)keyboardSizeForInputMode:(NSString *)mode screenTraits:(id)traits keyboardType:(NSInteger)type;
+ (BOOL)shouldLoadWallpaperBundleAtURL:(NSURL *)url;
@end

static id valueOrNull(id value) { return value ?: NSNull.null; }

NSDictionary *nabuExperienceSnapshot(void) {
    NSMutableDictionary *report = [@{@"read_only": @YES} mutableCopy];
    void *mg = dlopen("/usr/lib/libMobileGestalt.dylib", RTLD_NOW);
    CFTypeRef (*answer)(CFStringRef, void *, int32_t *) = dlsym(mg, "MGCopyAnswerWithError");
    NSMutableDictionary *identity = [NSMutableDictionary dictionary];
    for (NSString *key in @[@"ProductType", @"DeviceClass", @"ModelNumber", @"RegionInfo",
        @"RegulatoryModelNumber", @"marketing-name", @"ArtworkTraits", @"DeviceColor"] ) {
        int32_t error = 0;
        CFTypeRef value = answer((__bridge CFStringRef)key, NULL, &error);
        identity[key] = @{@"error": @(error), @"value": valueOrNull(CFBridgingRelease(value))};
    }
    report[@"identity"] = identity;
    UIScreen *screen = UIScreen.mainScreen;
    report[@"screen"] = @{@"bounds": NSStringFromCGRect(screen.bounds),
        @"native_bounds": NSStringFromCGRect(screen.nativeBounds), @"scale": @(screen.scale)};

    dlopen("/System/Library/PrivateFrameworks/TextInputUI.framework/TextInputUI", RTLD_NOW);
    Class factoryClass = NSClassFromString(@"TUIKeyboardLayoutFactory");
    id factory = [factoryClass sharedKeyboardFactory];
    NSMutableArray *prefixes = [NSMutableArray array];
    for (NSNumber *width in @[@768, @800, @810, @1024, @1080, @1280]) {
        for (NSNumber *minor in @[@YES, @NO])
            [prefixes addObject:@{@"width": width, @"minor_edge": minor,
                @"prefix": valueOrNull([factory keyboardPrefixForWidth:width.doubleValue andEdge:minor.boolValue])}];
    }
    report[@"keyboard_prefixes"] = prefixes;
    NSMutableArray *files = [NSMutableArray array];
    for (NSString *name in @[@"KBLayouts_iPad.dat", @"KBLayouts_Dynamic.dat", @"Assets.car"]) {
        NSString *path = [@"/System/Library/PrivateFrameworks/TextInputUI.framework" stringByAppendingPathComponent:name];
        NSError *error = nil;
        NSDictionary *attributes = [NSFileManager.defaultManager attributesOfItemAtPath:path error:&error];
        [files addObject:@{@"path": path, @"bytes": attributes[NSFileSize] ?: @0,
            @"error": error ? error.description : @""}];
    }
    report[@"keyboard_files"] = files;
    NSMutableArray *sizes = [NSMutableArray array];
    Class traitsClass = NSClassFromString(@"UIKBScreenTraits");
    Class layoutClass = NSClassFromString(@"UIKeyboardLayoutStar");
    for (NSNumber *orientation in @[@1, @3]) {
        id traits = [traitsClass traitsWithScreen:screen orientation:orientation.integerValue];
        for (NSString *mode in @[@"en_US@sw=QWERTY;hw=Automatic", @"zh_Hans-Pinyin@sw=Pinyin;hw=Automatic"]) {
            CGSize size = [layoutClass keyboardSizeForInputMode:mode screenTraits:traits keyboardType:0];
            [sizes addObject:@{@"orientation": orientation, @"mode": mode,
                @"size": NSStringFromCGSize(size), @"traits": valueOrNull([traits description])}];
        }
    }
    report[@"keyboard_sizes"] = sizes;

    void *wk = dlopen("/System/Library/PrivateFrameworks/WallpaperKit.framework/WallpaperKit", RTLD_NOW);
    NSString *(*screenClass)(void) = dlsym(wk, "WKLogicalScreenClassString");
    report[@"wallpaper_screen_class"] = screenClass ? valueOrNull(screenClass()) : @"symbol unavailable";
    Class bundleClass = NSClassFromString(@"WKWallpaperBundle");
    NSString *path = @"/Library/Wallpaper/Stills/iPad/7410.WWDC_2022-810w-1080h@2x~ipad.wallpaper";
    report[@"default_wallpaper_accepted"] = @([bundleClass shouldLoadWallpaperBundleAtURL:[NSURL fileURLWithPath:path]]);
    NSLog(@"NABU EXPERIENCE: %@", report);
    return report;
}
