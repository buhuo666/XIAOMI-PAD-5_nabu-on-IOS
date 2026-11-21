// The real macOS Objective-C runtime loads the complete production frontend.
// GPU entry points remain unbound and are never called by this test.
#import <Foundation/Foundation.h>
#import <objc/message.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <cstring>
#include <stdexcept>
#include <string>

static void skipQuoted(const char *&p) {
    if (*p != '"') return;
    ++p;
    while (*p && *p != '"') { if (*p == '\\' && p[1]) ++p; ++p; }
    if (*p != '"') throw std::runtime_error("unterminated quoted ABI name");
    ++p;
}

static std::string canonicalType(const char *&p) {
    while (*p && strchr("rnNoORVA", *p)) ++p;
    if (!*p) throw std::runtime_error("missing ABI type");
    const char kind = *p++;
    std::string out(1, kind);
    if (kind == '@') {
        if (*p == '?') { out += *p++; }
        else if (*p == '"') skipQuoted(p);
    } else if (kind == '^') {
        out += canonicalType(p);
    } else if (kind == '{' || kind == '(') {
        const char end = kind == '{' ? '}' : ')';
        while (*p && *p != '=' && *p != end) ++p; // Struct names are not ABI.
        if (*p == '=') {
            ++p;
            while (*p && *p != end) {
                if (*p == '"') skipQuoted(p); // Optional field names.
                else out += canonicalType(p);
            }
        }
        if (*p != end) throw std::runtime_error("unterminated aggregate ABI");
        out += *p++;
    } else if (kind == '[') {
        while (*p >= '0' && *p <= '9') out += *p++;
        out += canonicalType(p);
        if (*p != ']') throw std::runtime_error("unterminated array ABI");
        out += *p++;
    } else if (kind == 'b') {
        while (*p >= '0' && *p <= '9') out += *p++;
    } else if (!strchr("cislqCISLQfdDBv*#:?", kind)) {
        throw std::runtime_error("unsupported ABI token " + std::string(1, kind));
    }
    return out;
}

static NSDictionary *describeType(const char *type) {
    const char *cursor = type;
    const std::string canonical = canonicalType(cursor);
    if (*cursor) throw std::runtime_error("unconsumed ABI type text");
    NSUInteger size = 0, alignment = 0;
    if (canonical != "v") NSGetSizeAndAlignment(type, &size, &alignment);
    return @{@"raw": [NSString stringWithUTF8String:type],
        @"canonical": [NSString stringWithUTF8String:canonical.c_str()],
        @"bytes": @(size), @"alignment": @(alignment)};
}

static NSDictionary *describeSignature(const char *encoding) {
    NSMethodSignature *signature = [NSMethodSignature signatureWithObjCTypes:encoding];
    if (!signature) throw std::runtime_error("NSMethodSignature rejected encoding");
    NSMutableArray *arguments = [NSMutableArray array];
    for (NSUInteger i = 0; i < signature.numberOfArguments; ++i)
        [arguments addObject:describeType([signature getArgumentTypeAtIndex:i])];
    return @{@"return": describeType(signature.methodReturnType),
        @"return_bytes": @(signature.methodReturnLength), @"arguments": arguments};
}

static bool typesEqual(NSDictionary *a, NSDictionary *b) {
    return [a[@"canonical"] isEqual:b[@"canonical"]] &&
        [a[@"bytes"] isEqual:b[@"bytes"]] && [a[@"alignment"] isEqual:b[@"alignment"]];
}

static bool signaturesEqual(NSDictionary *a, NSDictionary *b) {
    if (!typesEqual(a[@"return"], b[@"return"]) || ![a[@"return_bytes"] isEqual:b[@"return_bytes"]]) return false;
    NSArray *aa = a[@"arguments"], *bb = b[@"arguments"];
    if (aa.count != bb.count) return false;
    for (NSUInteger i = 0; i < aa.count; ++i) if (!typesEqual(aa[i], bb[i])) return false;
    return true;
}

static void require(bool ok, const char *message) {
    if (!ok) throw std::runtime_error(message);
}

static void verifyComparator() {
    require(signaturesEqual(describeSignature("{Origin=QQQ}40@0:8{Range=QQ}16"),
        describeSignature("{?=QQQ}40@0:8{_NSRange=QQ}16")), "struct spelling must not change ABI");
    require(!signaturesEqual(describeSignature("Q16@0:8"), describeSignature("I16@0:8")), "64-bit return mismatch not detected");
    require(!signaturesEqual(describeSignature("v32@0:8{?=ff}16"), describeSignature("v32@0:8{?=QQ}16")), "struct field ABI mismatch not detected");
    require(!signaturesEqual(describeSignature("v24@0:8@?16"), describeSignature("v24@0:8@16")), "block/object mismatch not detected");
    require(!signaturesEqual(describeSignature("B16@0:8"), describeSignature("c16@0:8")), "bool/char ABI mismatch not detected");
    require(signaturesEqual(describeSignature("v24@0:8r^Q16"), describeSignature("v24@0:8^Q16")), "const qualifier changed ABI");
}

static unsigned endCalls;
static void testEndEncoding(id, SEL) { ++endCalls; }
static unsigned refusalCalls;
static void testRefuse(id, SEL, NSString *) { ++refusalCalls; }

static NSArray *verifySafeEncoderDispatch() {
    Class encoder = objc_getClass("NBEncoder");
    require(encoder != Nil, "NBEncoder was not registered");
    Class testClass = objc_allocateClassPair(encoder, "NBRuntimeABIEndDispatchProbe", 0);
    require(testClass != Nil, "cannot create endEncoding dispatch probe");
    require(class_addMethod(testClass, sel_registerName("endEncoding"), (IMP)testEndEncoding, "v16@0:8"),
        "cannot install test endEncoding override");
    objc_registerClassPair(testClass);
    id instance = class_createInstance(testClass, 0);
    require(instance != nil, "cannot create safe encoder probe");
    auto sendObject = (id (*)(id, SEL))objc_msgSend;
    auto sendVoid = (void (*)(id, SEL))objc_msgSend;
    auto sendString = (void (*)(id, SEL, NSString *))objc_msgSend;
    require(sendObject(instance, sel_registerName("endEncodingAndRetrieveProgramAddressTable")) == nil,
        "endEncodingAndRetrieveProgramAddressTable returned non-nil");
    require(endCalls == 1, "endEncodingAndRetrieveProgramAddressTable did not dispatch endEncoding exactly once");
    sendVoid(instance, sel_registerName("popDebugGroup")); // Empty stack must not throw/fail.
    NSMutableString *text = [NSMutableString stringWithString:@"before mutation"];
    sendString(instance, sel_registerName("pushDebugGroup:"), text);
    sendString(instance, sel_registerName("insertDebugSignpost:"), text);
    [text setString:@"after mutation"];
    NSArray *groups = sendObject(instance, sel_registerName("debugGroups"));
    NSArray *signposts = sendObject(instance, sel_registerName("debugSignposts"));
    require(groups.count == 1 && [groups[0] isEqual:@"before mutation"], "debug group was not copied/retained");
    require(signposts.count == 1 && [signposts[0] isEqual:@"before mutation"], "debug signpost was not copied/retained");
    sendVoid(instance, sel_registerName("popDebugGroup"));
    require([sendObject(instance, sel_registerName("debugGroups")) count] == 0, "debug group was not popped");
    Class refusalClass = objc_allocateClassPair([NSObject class], "NBRuntimeABIRefusalProbe", 0);
    require(refusalClass != Nil && class_addMethod(refusalClass, sel_registerName("refuse:"),
        (IMP)testRefuse, "v24@0:8@16"), "cannot create explicit test-only refusal receiver");
    objc_registerClassPair(refusalClass);
    id refusalReceiver = class_createInstance(refusalClass, 0);
    ((void (*)(id, SEL, id))objc_msgSend)(instance, sel_registerName("setCommandBuffer:"), refusalReceiver);
    sendString(instance, sel_registerName("pushDebugGroup:"), nil);
    sendString(instance, sel_registerName("insertDebugSignpost:"), nil);
    sendString(instance, sel_registerName("pushDebugGroup:"), (NSString *)(id)@7);
    sendString(instance, sel_registerName("insertDebugSignpost:"), (NSString *)(id)@7);
    require(refusalCalls == 4, "nil or non-NSString debug metadata was not refused");
    require([sendObject(instance, sel_registerName("debugGroups")) count] == 0,
        "invalid debug group changed group history");
    require([sendObject(instance, sel_registerName("debugSignposts")) count] == 1,
        "invalid debug signpost changed signpost history");
    ((void (*)(id, SEL, id))objc_msgSend)(instance, sel_registerName("setCommandBuffer:"), nil);
    const char *names[] = {"NBEncoder", "NBRenderEncoder", "NBComputeEncoder", "NBBlitEncoder", "NBResourceStateEncoder"};
    const uint64_t types[] = {0, 0, 1, 2, 6};
    for (unsigned i = 0; i < sizeof(types) / sizeof(types[0]); ++i) {
        Class cls = objc_getClass(names[i]);
        require(cls != Nil, "missing encoder class for getType dispatch");
        id object = class_createInstance(cls, 0);
        require(((uint64_t (*)(id, SEL))objc_msgSend)(object, sel_registerName("getType")) == types[i],
            "getType did not return the native encoder enum");
        // All instances have zero runtime handles. NBEncoder dealloc therefore
        // does not call nmb_encoder_discard; no runtime ownership was fabricated.
    }
    return @[@"real objc_msgSend: endEncodingAndRetrieveProgramAddressTable dispatches override once and returns nil",
        @"real objc_msgSend: getType render/base0 compute1 blit2 resource6",
        @"real objc_msgSend: empty debug pop, copied retained group/signpost and balanced pop",
        @"real objc_msgSend: nil/non-NSString debug values rejected via explicit test-only refusal receiver"];
}

static NSString *definingClass(Class cls, SEL selector) {
    for (Class at = cls; at; at = class_getSuperclass(at)) {
        unsigned count = 0;
        Method *methods = class_copyMethodList(at, &count);
        bool found = false;
        for (unsigned i = 0; i < count; ++i) if (method_getName(methods[i]) == selector) found = true;
        free(methods);
        if (found) return [NSString stringWithUTF8String:class_getName(at)];
    }
    return @"unknown";
}

int main(int argc, const char **argv) {
    @autoreleasepool {
        if (argc != 4) { fprintf(stderr, "usage: runtime-abi frontend.bundle expected-methods.json runtime-report.json\n"); return 2; }
        NSMutableDictionary *report = [@{@"status": @"running", @"gpu_executed": @NO,
            @"global_trace_allocator_executed": @NO, @"host_target_os_iphone": @NO} mutableCopy];
        int exitCode = 1;
        @try {
            try {
                verifyComparator();
                NSError *error = nil;
                NSData *data = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[2]]];
                require(data != nil, "cannot read expected-methods.json");
                NSDictionary *manifest = [NSJSONSerialization JSONObjectWithData:data options:0 error:&error];
                require(manifest != nil && [manifest[@"schema"] intValue] == 1, "invalid manifest");
                report[@"limitations"] = manifest[@"limitations"];
                report[@"excluded_ios_unavailable"] = manifest[@"skipped"];
                void *bundle = dlopen(argv[1], RTLD_LAZY | RTLD_LOCAL);
                if (!bundle) throw std::runtime_error(std::string("dlopen: ") + dlerror());
                auto registerDevice = (Class (*)())dlsym(bundle, "nabu_test_register_device_methods");
                require(registerDevice != nullptr, "test-only device registration entry absent");
                Class deviceProbe = registerDevice();
                require(deviceProbe != Nil, "actual installAnswers device registration failed");
                report[@"device_registration"] = @"actual production installAnswers and donor IMPs with explicit test-only answer-value injection; GPU capabilities not tested";
                report[@"device_original_class"] = manifest[@"device_original_class"];
                report[@"device_coverage"] = manifest[@"device_coverage"];
                report[@"ownership_scope"] = manifest[@"ownership_scope"];
                NSMutableArray *checked = [NSMutableArray array], *failures = [NSMutableArray array];
                NSMutableArray *nativeDeviceUnverified = [NSMutableArray array], *inventory = [NSMutableArray array];
                for (NSString *name in manifest[@"classes"]) {
                    Class cls = objc_getClass(name.UTF8String);
                    if (!cls) { [failures addObject:@{@"class": name, @"reason": @"class not registered"}]; continue; }
                    unsigned count = 0;
                    Method *methods = class_copyMethodList(cls, &count);
                    NSMutableArray *rows = [NSMutableArray array];
                    for (unsigned i = 0; i < count; ++i) [rows addObject:@{
                        @"selector": NSStringFromSelector(method_getName(methods[i])),
                        @"encoding": [NSString stringWithUTF8String:method_getTypeEncoding(methods[i])]}];
                    free(methods);
                    Class parent = class_getSuperclass(cls);
                    [inventory addObject:@{@"class": name, @"parent": parent ? [NSString stringWithUTF8String:class_getName(parent)] : @"",
                        @"direct_runtime_methods_including_categories": rows}];
                }
                NSArray *expected = [[manifest[@"methods"] arrayByAddingObjectsFromArray:manifest[@"private_methods"]]
                    arrayByAddingObjectsFromArray:manifest[@"dynamic_private_methods"]];
                for (NSDictionary *item in expected) {
                    NSString *name = item[@"frontend_class"], *selectorName = item[@"selector"];
                    Class cls = [name isEqual:@"NBDeviceMethods"] ? deviceProbe : objc_getClass(name.UTF8String);
                    SEL selector = sel_registerName(selectorName.UTF8String);
                    Method method = cls ? class_getInstanceMethod(cls, selector) : nullptr;
                    NSMutableDictionary *row = [item mutableCopy];
                    if (!method) {
                        row[@"reason"] = @"selector absent from actual runtime class and inherited classes";
                        if ([item[@"required"] boolValue]) [failures addObject:row];
                        else [nativeDeviceUnverified addObject:row];
                        continue;
                    }
                    const char *actual = method_getTypeEncoding(method);
                    row[@"actual_encoding"] = [NSString stringWithUTF8String:actual];
                    row[@"defined_on"] = definingClass(cls, selector);
                    NSDictionary *a = describeSignature(actual), *b = describeSignature([item[@"encoding"] UTF8String]);
                    row[@"actual_signature"] = a;
                    row[@"expected_signature"] = b;
                    const bool equal = signaturesEqual(a, b);
                    row[@"abi_matches"] = @(equal);
                    [checked addObject:row];
                    if (!equal) { row[@"reason"] = @"return/argument canonical type, width or alignment differs"; [failures addObject:row]; }
                }
                report[@"checked"] = checked;
                report[@"failures"] = failures;
                report[@"native_device_inheritance_unverified"] = nativeDeviceUnverified;
                report[@"class_inventory"] = inventory;
                report[@"safe_dispatch_checks"] = verifySafeEncoderDispatch();
                report[@"status"] = failures.count ? @"failed" : @"passed_with_reported_scope";
                report[@"checked_count"] = @(checked.count);
                report[@"failure_count"] = @(failures.count);
                report[@"native_device_inheritance_unverified_count"] = @(nativeDeviceUnverified.count);
                exitCode = failures.count ? 1 : 0;
                // Do not dlclose: registered ObjC classes and method pointers
                // must remain mapped until process termination.
            } catch (const std::exception &failure) {
                report[@"status"] = @"failed";
                report[@"fatal"] = [NSString stringWithUTF8String:failure.what()];
            }
        } @catch (NSException *failure) {
            report[@"status"] = @"failed";
            report[@"fatal"] = [NSString stringWithFormat:@"%@: %@", failure.name, failure.reason];
        }
        NSData *json = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
        [json writeToFile:[NSString stringWithUTF8String:argv[3]] atomically:YES];
        printf("runtime ABI: %s; checked=%lu failures=%lu\n", [report[@"status"] UTF8String],
            (unsigned long)[report[@"checked_count"] unsignedIntegerValue],
            (unsigned long)[report[@"failure_count"] unsignedIntegerValue]);
        if (report[@"fatal"]) fprintf(stderr, "%s\n", [report[@"fatal"] UTF8String]);
        return exitCode;
    }
}
