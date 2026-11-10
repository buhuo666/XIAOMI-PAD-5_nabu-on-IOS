/* Paired-host post-desktop DPU diagnostics; the kernel owns all register access. */
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <unistd.h>

NSDictionary *nabuDpuRequest(NSString *action, NSString *identifier) {
    void *kit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW);
    if (!kit) return @{@"error": @"IOKit unavailable"};
    CFMutableDictionaryRef (*matching)(const char *) = dlsym(kit, "IOServiceMatching");
    uint32_t (*service)(uint32_t, CFDictionaryRef) = dlsym(kit, "IOServiceGetMatchingService");
    CFTypeRef (*property)(uint32_t, CFStringRef, CFAllocatorRef, uint32_t) = dlsym(kit, "IORegistryEntryCreateCFProperty");
    int (*setProperties)(uint32_t, CFTypeRef) = dlsym(kit, "IORegistryEntrySetCFProperties");
    int (*release)(uint32_t) = dlsym(kit, "IOObjectRelease");
    uint32_t entry = service(0, matching("IOMobileFramebuffer"));
    if (!entry) { dlclose(kit); return @{@"error": @"framebuffer unavailable"}; }
    NSMutableDictionary *out = [@{@"request_id": identifier,
        @"post_desktop": @YES, @"uid": @(getuid())} mutableCopy];
    id available = CFBridgingRelease(property(entry, CFSTR("NabuDpuDiagnosticAvailable"), NULL, 0));
    out[@"available"] = available ?: @NO;
    if (![available isEqual:@YES]) {
        out[@"error"] = @"diagnostic boot option unavailable";
    } else {
        NSString *command = [action isEqual:@"DpuSnapshot"] ? @"Snapshot" : @"HaltResume";
        NSDictionary *request = @{@"NabuDpuDiagnostic": command, @"RequestID": identifier};
        int status = setProperties(entry, (__bridge CFTypeRef)request);
        out[@"submit_status"] = @((uint32_t)status);
        if (!status) {
            for (unsigned i = 0; i < 100; ++i) {
                id result = CFBridgingRelease(property(entry, CFSTR("NabuDpuDiagnosticResult"), NULL, 0));
                if ([result isKindOfClass:NSDictionary.class] && [result[@"request_id"] isEqual:identifier]) {
                    out[@"result"] = result;
                    break;
                }
                usleep(100000);
            }
            if (!out[@"result"]) out[@"timeout"] = @YES;
        }
        out[@"state"] = CFBridgingRelease(property(entry, CFSTR("NabuDpuDiagnosticState"), NULL, 0)) ?: NSNull.null;
    }
    release(entry); dlclose(kit); return out;
}
