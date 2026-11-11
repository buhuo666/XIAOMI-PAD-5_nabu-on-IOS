/* Paired-host post-desktop DPU diagnostics; the kernel owns all register access. */
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <unistd.h>

static NSString *const dpuDirectory = @"/private/var/run/nabu-dpu";

static NSDictionary *pairedDpuRequest(NSString *action, NSString *identifier) {
    NSString *path = [dpuDirectory stringByAppendingPathComponent:@"requests/request.plist"];
    NSDictionary *request = @{@"Action": action, @"ID": identifier};
    if (![request writeToFile:path atomically:YES])
        return @{@"request_id": identifier, @"error": @"root diagnostic request could not be written"};
    path = [dpuDirectory stringByAppendingPathComponent:@"result.json"];
    const unsigned waits = [action isEqual:@"DpuFlipGop"] ? 750 : 200;
    for (unsigned i = 0; i < waits; ++i) {
        NSData *bytes = [NSData dataWithContentsOfFile:path];
        NSDictionary *result = bytes ? [NSJSONSerialization JSONObjectWithData:bytes options:0 error:NULL] : nil;
        if ([result[@"request_id"] isEqual:identifier]) return result;
        usleep(100000);
    }
    return @{@"request_id": identifier, @"timeout": @YES, @"error": @"root diagnostic result timeout"};
}

NSDictionary *nabuDpuRequest(NSString *action, NSString *identifier) {
    if (getuid() != 0) return pairedDpuRequest(action, identifier);
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
        NSString *command = [action isEqual:@"DpuSnapshot"] ? @"Snapshot" :
            ([action isEqual:@"DpuActivateGop"] ? @"ActivateGop" :
             ([action isEqual:@"DpuFlipGop"] ? @"FlipGop" : @"HaltResume"));
        NSDictionary *request = @{@"NabuDpuDiagnostic": command, @"RequestID": identifier};
        int status = setProperties(entry, (__bridge CFTypeRef)request);
        out[@"submit_status"] = @((uint32_t)status);
        if (!status) {
            const unsigned waits = [action isEqual:@"DpuFlipGop"] ? 600 : 100;
            for (unsigned i = 0; i < waits; ++i) {
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

// A dedicated root launch job selects this entry point. The regular services
// probe remains mobile; the root process accepts only the named DPU commands.
int nabuDpuServiceMain(void) {
    if (getuid() != 0) return 1;
    @autoreleasepool {
        NSFileManager *fm = NSFileManager.defaultManager;
        if (![fm createDirectoryAtPath:dpuDirectory withIntermediateDirectories:YES
                            attributes:@{NSFilePosixPermissions: @0755} error:NULL])
            return 1;
        // Only the request child is mobile-writable. The root-owned parent
        // keeps the result and directory ownership operations outside it.
        NSString *requests = [dpuDirectory stringByAppendingPathComponent:@"requests"];
        NSDictionary *attributes = @{NSFileOwnerAccountID: @501, NSFileGroupOwnerAccountID: @501,
                                     NSFilePosixPermissions: @0700};
        if (![fm createDirectoryAtPath:requests withIntermediateDirectories:NO attributes:attributes error:NULL]) return 1;
        if (![fm setAttributes:attributes ofItemAtPath:requests error:NULL]) return 1;
        NSString *requestPath = [requests stringByAppendingPathComponent:@"request.plist"];
        NSString *resultPath = [dpuDirectory stringByAppendingPathComponent:@"result.json"];
        [fm removeItemAtPath:requestPath error:NULL]; // Never replay a previous boot's request.
        [fm removeItemAtPath:resultPath error:NULL];
        for (unsigned i = 0; i < 2400; ++i) {
            @autoreleasepool {
                NSDictionary *request = [NSDictionary dictionaryWithContentsOfFile:requestPath];
                if (request) {
                    [fm removeItemAtPath:requestPath error:NULL];
                    NSString *action = request[@"Action"], *identifier = request[@"ID"];
                    if (([action isEqual:@"DpuSnapshot"] || [action isEqual:@"DpuHaltResume"] ||
                         [action isEqual:@"DpuActivateGop"] || [action isEqual:@"DpuFlipGop"]) &&
                        [identifier isKindOfClass:NSString.class] && identifier.length && identifier.length <= 64) {
                        NSDictionary *result = nabuDpuRequest(action, identifier);
                        NSData *bytes = [NSJSONSerialization dataWithJSONObject:result options:0 error:NULL];
                        [bytes writeToFile:resultPath options:NSDataWritingAtomic error:NULL];
                        [fm setAttributes:@{NSFilePosixPermissions: @0644} ofItemAtPath:resultPath error:NULL];
                    }
                }
            }
            usleep(500000);
        }
    }
    return 0;
}
