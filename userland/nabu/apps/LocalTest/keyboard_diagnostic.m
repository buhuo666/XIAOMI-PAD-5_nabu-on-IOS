#import <UIKit/UIKit.h>
#import <objc/runtime.h>

@interface NSObject (NabuKeyboardDiagnostic)
+ (id)traitsWithScreen:(UIScreen *)screen orientation:(NSInteger)orientation;
+ (CGSize)keyboardSizeForInputMode:(NSString *)mode screenTraits:(id)traits keyboardType:(NSInteger)type;
@end

static NSMutableArray *events;
static BOOL useBaseHeight;
static void (*originalSize)(id, SEL, CGSize);
static id (*originalGraph)(id, SEL, NSString *, id);

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
    for (NSNumber *compat in @[@NO, @YES]) {
        useBaseHeight = compat.boolValue;
        for (NSNumber *orientation in @[@1, @3]) {
            id traits = [NSClassFromString(@"UIKBScreenTraits") traitsWithScreen:UIScreen.mainScreen orientation:orientation.integerValue];
            for (NSString *mode in @[@"en_US@sw=QWERTY;hw=Automatic", @"zh_Hans-Pinyin@sw=Pinyin;hw=Automatic"]) {
                [events removeAllObjects];
                CGSize size = [NSClassFromString(@"UIKeyboardLayoutStar") keyboardSizeForInputMode:mode screenTraits:traits keyboardType:0];
                [rows addObject:@{@"base_height_trial": compat, @"orientation": orientation,
                    @"mode": mode, @"size": NSStringFromCGSize(size), @"events": [events copy]}];
            }
        }
    }
    useBaseHeight = NO;
    method_setImplementation(sizeMethod, (IMP)originalSize);
    method_setImplementation(graphMethod, (IMP)originalGraph);
    NSURL *documents = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    NSDictionary *report = @{@"screen": NSStringFromCGRect(UIScreen.mainScreen.bounds), @"queries": rows,
        @"scope": @"Temporary method instrumentation in this app; original implementations restored before text input"};
    [[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:NULL]
        writeToURL:[documents URLByAppendingPathComponent:@"keyboard-diagnostic.json"] atomically:YES];
    NSLog(@"NABU KEYBOARD APP: %@", report);
    return @"键盘诊断已保存。点下方输入框测试键盘。";
}
