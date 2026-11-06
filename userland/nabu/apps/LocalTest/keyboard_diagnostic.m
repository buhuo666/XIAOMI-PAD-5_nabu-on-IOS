#import <UIKit/UIKit.h>
#import <objc/runtime.h>
extern void nabuInstallExperienceCompatibility(void);

@interface NSObject (NabuKeyboardDiagnostic)
+ (id)traitsWithScreen:(UIScreen *)screen orientation:(NSInteger)orientation;
+ (CGSize)keyboardSizeForInputMode:(NSString *)mode screenTraits:(id)traits keyboardType:(NSInteger)type;
+ (BOOL)shouldLoadWallpaperBundleAtURL:(NSURL *)url;
@end

static NSMutableArray *events;
static BOOL useBaseHeight;
static void (*originalSize)(id, SEL, CGSize);
static id (*originalGraph)(id, SEL, NSString *, id);
static CGRect physicalBounds;
static CGRect physicalReference(id object, SEL selector) {
    (void)object; (void)selector;
    return physicalBounds;
}
static CGRect physicalOriented(id object, SEL selector, NSInteger orientation) {
    (void)object; (void)selector;
    CGRect result = physicalBounds;
    if (orientation == 3 || orientation == 4)
        result.size = CGSizeMake(physicalBounds.size.height, physicalBounds.size.width);
    return result;
}

static void recordSize(id object, SEL selector, CGSize size) {
    CGSize submitted = size;
    if (useBaseHeight && size.width > 0 && size.height == 0) submitted.height = -1;
    if (events.count < 160) [events addObject:@{@"event": @"derived_size",
        @"requested": NSStringFromCGSize(size), @"submitted": NSStringFromCGSize(submitted)}];
    originalSize(object, selector, submitted);
}

static id recordGraph(id object, SEL selector, NSString *name, id cache) {
    id result = originalGraph(object, selector, name, cache);
    if (events.count < 160) [events addObject:@{@"event": @"graph", @"name": name ?: @"",
        @"class": result ? NSStringFromClass([result class]) : @"nil"}];
    return result;
}

NSString *nabuKeyboardDiagnostic(void) {
    events = [NSMutableArray array];
    Method sizeMethod = class_getInstanceMethod(NSClassFromString(@"UIKBDerivedKeyboard"), NSSelectorFromString(@"setKeyboardSize:"));
    originalSize = (void (*)(id, SEL, CGSize))method_setImplementation(sizeMethod, (IMP)recordSize);
    // UIKit loads TextInputUI while computing the first layout.
    [[NSBundle bundleWithPath:@"/System/Library/PrivateFrameworks/TextInputUI.framework"] load];
    Method graphMethod = class_getInstanceMethod(NSClassFromString(@"TUIKeyboardLayoutFactory"), NSSelectorFromString(@"keyboardWithName:inCache:"));
    originalGraph = (id (*)(id, SEL, NSString *, id))method_setImplementation(graphMethod, (IMP)recordGraph);
    NSMutableArray *rows = [NSMutableArray array];
    UIScreen *screen = UIScreen.mainScreen;
    CGRect naturalBounds = screen.bounds;
    physicalBounds = screen.nativeBounds;
    physicalBounds.size.width /= screen.scale;
    physicalBounds.size.height /= screen.scale;
    Method referenceMethod = class_getInstanceMethod(screen.class, NSSelectorFromString(@"_referenceBounds"));
    Method orientedMethod = class_getInstanceMethod(screen.class, NSSelectorFromString(@"_boundsForInterfaceOrientation:"));
    IMP originalReference = method_getImplementation(referenceMethod);
    IMP originalOriented = method_getImplementation(orientedMethod);
    for (NSNumber *physical in @[@NO, @YES]) {
      if (physical.boolValue) {
        method_setImplementation(referenceMethod, (IMP)physicalReference);
        method_setImplementation(orientedMethod, (IMP)physicalOriented);
      }
      for (NSNumber *compat in @[@NO, @YES]) {
        useBaseHeight = compat.boolValue;
        for (NSNumber *orientation in @[@1, @3]) {
            id traits = [NSClassFromString(@"UIKBScreenTraits") traitsWithScreen:UIScreen.mainScreen orientation:orientation.integerValue];
            for (NSString *mode in @[@"en_US@sw=QWERTY;hw=Automatic", @"zh_Hans-Pinyin@sw=Pinyin;hw=Automatic"]) {
                [events removeAllObjects];
                CGSize size = [NSClassFromString(@"UIKeyboardLayoutStar") keyboardSizeForInputMode:mode screenTraits:traits keyboardType:0];
                [rows addObject:@{@"physical_screen_trial": physical, @"base_height_trial": compat, @"orientation": orientation,
                    @"mode": mode, @"size": NSStringFromCGSize(size), @"events": [events copy]}];
            }
        }
      }
    }
    method_setImplementation(referenceMethod, originalReference);
    method_setImplementation(orientedMethod, originalOriented);
    useBaseHeight = NO;
    method_setImplementation(sizeMethod, (IMP)originalSize);
    method_setImplementation(graphMethod, (IMP)originalGraph);
    nabuInstallExperienceCompatibility();
    NSMutableArray *candidate = [NSMutableArray array];
    for (NSNumber *orientation in @[@1, @3]) {
        id traits = [NSClassFromString(@"UIKBScreenTraits") traitsWithScreen:screen orientation:orientation.integerValue];
        CGSize size = [NSClassFromString(@"UIKeyboardLayoutStar") keyboardSizeForInputMode:@"zh_Hans-Pinyin@sw=Pinyin;hw=Automatic" screenTraits:traits keyboardType:0];
        [candidate addObject:@{@"orientation": orientation, @"size": NSStringFromCGSize(size)}];
    }
    NSURL *wallpaper = [NSURL fileURLWithPath:@"/Library/Wallpaper/Stills/iPad/7410.WWDC_2022-810w-1080h@2x~ipad.wallpaper"];
    BOOL wallpaperAccepted = [NSClassFromString(@"WKWallpaperBundle") shouldLoadWallpaperBundleAtURL:wallpaper];
    NSURL *documents = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    NSDictionary *report = @{@"screen": NSStringFromCGRect(naturalBounds),
        @"physical_screen": NSStringFromCGRect(physicalBounds), @"queries": rows,
        @"compatibility_queries": candidate, @"wallpaper_accepted_with_compatibility": @(wallpaperAccepted),
        @"scope": @"Baseline instrumentation restored; candidate display compatibility active only in this app"};
    [[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:NULL]
        writeToURL:[documents URLByAppendingPathComponent:@"keyboard-diagnostic.json"] atomically:YES];
    NSLog(@"NABU KEYBOARD APP: %@", report);
    return @"键盘诊断已保存。点下方输入框测试键盘。";
}
