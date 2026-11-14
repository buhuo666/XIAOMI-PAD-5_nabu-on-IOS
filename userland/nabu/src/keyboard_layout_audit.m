#import "keyboard_layout_audit.h"
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include "keyboard_geometry.h"

@interface NSObject (NabuKeyboardLayoutQueries)
+ (id)traitsWithScreen:(UIScreen *)screen orientation:(NSInteger)orientation;
+ (CGSize)keyboardSizeForInputMode:(NSString *)mode screenTraits:(id)traits keyboardType:(NSInteger)type;
@end

typedef struct {
    __unsafe_unretained NSMutableArray *events;
    BOOL candidate;
    BOOL truncated;
    double scale,nativeWidth,nativeHeight;
} NabuAuditContext;

static __thread NabuAuditContext *activeContext;
static void (*savedSize)(id,SEL,CGSize);
static id (*savedGraph)(id,SEL,id,id);

static NSDictionary *sizeValue(CGSize value) {
    return @{ @"width":@(value.width), @"height":@(value.height) };
}

static void recordEvent(NSDictionary *event) {
    NabuAuditContext *context=activeContext;
    if (!context) return;
    if (context->events.count<160) [context->events addObject:event];
    else context->truncated=YES;
}

static void observeSize(id object,SEL selector,CGSize requested) {
    NabuAuditContext *context=activeContext;
    CGSize submitted=requested;
    if (context && context->candidate)
        submitted.height=nabu_keyboard_layout_height(requested.width,requested.height,
            context->scale,context->nativeWidth,context->nativeHeight);
    recordEvent(@{ @"event":@"derived_size", @"requested":sizeValue(requested), @"submitted":sizeValue(submitted) });
    savedSize(object,selector,submitted);
}

static id observeGraph(id object,SEL selector,id name,id cache) {
    id result=savedGraph(object,selector,name,cache);
    if (activeContext) recordEvent(@{ @"event":@"graph", @"name":[name isKindOfClass:NSString.class]?name:@"",
        @"class":result?NSStringFromClass([result class]):@"nil" });
    return result;
}

static NSString *implementationImage(IMP implementation) {
    Dl_info image;
    if (implementation && dladdr((const void *)implementation,&image) && image.dli_fname)
        return @(image.dli_fname);
    return @"unknown";
}

BOOL nabuKeyboardLayoutAudit(NSString *outputPath) {
    static BOOL attempted;
    if (!NSThread.isMainThread || attempted) return NO;
    attempted=YES;
    NSMutableDictionary *report=[@{ @"version":@1, @"process":NSProcessInfo.processInfo.processName,
        @"on_main_thread":@YES, @"input_preferences_changed":@NO, @"screen_methods_changed":@NO,
        @"scope":@"Private layout queries in this process; not visual keyboard or text-input validation" } mutableCopy];
    NSMutableArray *rows=[NSMutableArray new],*withoutHeight=[NSMutableArray new];
    report[@"queries"]=rows;
    report[@"candidate_queries_without_positive_height"]=withoutHeight;
    Method sizeMethod=NULL,graphMethod=NULL;
    BOOL sizeHooked=NO,graphHooked=NO;
    @try {
        /* This audit runs inside an already launched UIKit application. The
         * production lightweight library does not perform this framework load.
         */
        BOOL loaded=[[NSBundle bundleWithPath:@"/System/Library/PrivateFrameworks/TextInputUI.framework"] load];
        report[@"text_input_ui_loaded"]=@(loaded);
        Class derived=NSClassFromString(@"UIKBDerivedKeyboard");
        Class traitsClass=NSClassFromString(@"UIKBScreenTraits");
        Class layoutClass=NSClassFromString(@"UIKeyboardLayoutStar");
        Class factory=NSClassFromString(@"TUIKeyboardLayoutFactory");
        sizeMethod=class_getInstanceMethod(derived,NSSelectorFromString(@"setKeyboardSize:"));
        graphMethod=class_getInstanceMethod(factory,NSSelectorFromString(@"keyboardWithName:inCache:"));
        BOOL traitsAPI=class_getClassMethod(traitsClass,@selector(traitsWithScreen:orientation:))!=NULL;
        BOOL sizeAPI=class_getClassMethod(layoutClass,@selector(keyboardSizeForInputMode:screenTraits:keyboardType:))!=NULL;
        report[@"apis"]=@{ @"derived_size":@(sizeMethod!=NULL), @"traits":@(traitsAPI),
            @"layout_size":@(sizeAPI), @"graph_name":@(graphMethod!=NULL) };
        if (!sizeMethod || !traitsAPI || !sizeAPI) {
            report[@"query_error"]=@"Required observed 20F66 keyboard API is unavailable";
        } else {
            UIScreen *screen=UIScreen.mainScreen;
            CGRect native=screen.nativeBounds;
            report[@"screen"]=@{ @"bounds":NSStringFromCGRect(screen.bounds),
                @"native_bounds":NSStringFromCGRect(native), @"scale":@(screen.scale) };
            IMP previous=method_getImplementation(sizeMethod);
            NSString *image=implementationImage(previous);
            report[@"initial_size_implementation_image"]=image;
            report[@"current_phase_already_has_known_adapter"]=@([image.lastPathComponent isEqualToString:@"libnabu.experience.dylib"] ||
                [image.lastPathComponent isEqualToString:@"libnabu.keyboard.dylib"]);
            report[@"size_method_encoding"]=@(method_getTypeEncoding(sizeMethod));
            savedSize=(void (*)(id,SEL,CGSize))previous;
            method_setImplementation(sizeMethod,(IMP)observeSize); sizeHooked=YES;
            if (graphMethod) {
                savedGraph=(id (*)(id,SEL,id,id))method_getImplementation(graphMethod);
                method_setImplementation(graphMethod,(IMP)observeGraph); graphHooked=YES;
            }
            NSArray *types=@[@"Default",@"ASCIICapable",@"NumbersAndPunctuation",@"URL",@"NumberPad",@"PhonePad",
                @"NamePhonePad",@"EmailAddress",@"DecimalPad",@"Twitter",@"WebSearch",@"ASCIICapableNumberPad"];
            for (NSNumber *candidate in @[@NO,@YES]) for (NSNumber *orientation in @[@1,@3]) {
                id traits=[traitsClass traitsWithScreen:screen orientation:orientation.integerValue];
                for (NSString *mode in @[@"en_US@sw=QWERTY;hw=Automatic",@"zh_Hans-Pinyin@sw=Pinyin;hw=Automatic"])
                    for (NSInteger type=0;type<12;type++) {
                        NSMutableArray *events=[NSMutableArray new];
                        NabuAuditContext context={events,candidate.boolValue,NO,screen.scale,native.size.width,native.size.height};
                        NSMutableDictionary *row=[@{ @"phase":candidate.boolValue?@"candidate_zero_height_rule":@"current",
                            @"orientation":orientation, @"mode":mode, @"keyboard_type":@(type), @"keyboard_type_name":types[type] } mutableCopy];
                        activeContext=&context;
                        @try {
                            if (!traits) {
                                row[@"query_error"]=@"UIKBScreenTraits returned nil";
                                row[@"has_positive_height"]=@NO;
                            } else {
                                CGSize size=[layoutClass keyboardSizeForInputMode:mode screenTraits:traits keyboardType:type];
                                row[@"returned_size"]=sizeValue(size);
                                row[@"has_positive_height"]=@(size.width>0 && size.height>0);
                            }
                        } @catch (NSException *exception) {
                            row[@"query_error"]=[NSString stringWithFormat:@"%@: %@",exception.name,exception.reason];
                            row[@"has_positive_height"]=@NO;
                        } @finally { activeContext=NULL; }
                        row[@"events"]=events;
                        row[@"events_truncated"]=@(context.truncated);
                        BOOL calledSetter=NO,exercisedRule=NO;
                        for (NSDictionary *event in events) if ([event[@"event"] isEqual:@"derived_size"]) {
                            calledSetter=YES;
                            if (candidate.boolValue && [event[@"requested"][@"height"] doubleValue]==0 &&
                                [event[@"submitted"][@"height"] doubleValue]==-1) exercisedRule=YES;
                        }
                        row[@"derived_setter_observed"]=@(calledSetter);
                        row[@"candidate_rule_exercised"]=@(exercisedRule);
                        if (candidate.boolValue) {
                            BOOL positive=[row[@"has_positive_height"] boolValue];
                            row[@"positive_height_without_rule_exercise"]=@(positive && !exercisedRule);
                            row[@"candidate_rule_evidence"]=exercisedRule?
                                (positive?@"0_to_minus1_observed_with_positive_result":@"0_to_minus1_observed_without_positive_result"):
                                @"not_exercised_by_this_query";
                        }
                        [rows addObject:row];
                        if (candidate.boolValue && ![row[@"has_positive_height"] boolValue]) [withoutHeight addObject:row];
                    }
            }
        }
    } @catch (NSException *exception) {
        report[@"audit_error"]=[NSString stringWithFormat:@"%@: %@",exception.name,exception.reason];
    } @finally {
        activeContext=NULL;
        BOOL restored=YES;
        if (sizeHooked) {
            if (method_getImplementation(sizeMethod)==(IMP)observeSize) method_setImplementation(sizeMethod,(IMP)savedSize);
            else restored=NO;
        }
        if (graphHooked) {
            if (method_getImplementation(graphMethod)==(IMP)observeGraph) method_setImplementation(graphMethod,(IMP)savedGraph);
            else restored=NO;
        }
        report[@"temporary_observers_restored"]=@(restored);
    }
    report[@"expected_query_count"]=@96;
    report[@"query_count"]=@(rows.count);
    report[@"all_candidate_queries_positive_height"]=@(rows.count==96 && withoutHeight.count==0);
    NSUInteger exercised=0,exercisedPositive=0,positiveWithoutExercise=0;
    for (NSDictionary *row in rows) if ([row[@"phase"] isEqual:@"candidate_zero_height_rule"]) {
        BOOL positive=[row[@"has_positive_height"] boolValue];
        if ([row[@"candidate_rule_exercised"] boolValue]) { exercised++; if (positive) exercisedPositive++; }
        else if (positive) positiveWithoutExercise++;
    }
    report[@"candidate_rule_exercised_query_count"]=@(exercised);
    report[@"candidate_rule_exercised_positive_query_count"]=@(exercisedPositive);
    report[@"positive_candidate_queries_without_rule_exercise"]=@(positiveWithoutExercise);
    report[@"cache_and_coverage_limit"]=@"A positive size without an observed 0-to-minus1 setter transition does not validate the repair; no private layout cache was cleared.";
    report[@"visual_input_verified"]=@NO;
    NSError *error=nil;
    NSData *data=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:&error];
    return data && [data writeToFile:outputPath options:NSDataWritingAtomic error:&error];
}
