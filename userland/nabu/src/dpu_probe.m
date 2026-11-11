/* Paired-host post-desktop DPU diagnostics; the kernel owns all register access. */
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <stdio.h>
#include <sys/stat.h>
#include <unistd.h>

static NSString *const dpuDirectory = @"/private/var/run/nabu-dpu";

static NSDictionary *pairedDpuRequest(NSString *action, NSString *identifier, NSDictionary *parameters) {
    NSString *path = [dpuDirectory stringByAppendingPathComponent:@"requests/request.plist"];
    NSDictionary *request = @{@"Action": action, @"ID": identifier, @"TraceRequest": parameters ?: @{}};
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
    if (getuid() != 0) return pairedDpuRequest(action, identifier, nil);
    void *kit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW);
    if (!kit) return @{@"error": @"IOKit unavailable"};
    CFMutableDictionaryRef (*matching)(const char *) = dlsym(kit, "IOServiceMatching");
    uint32_t (*service)(uint32_t, CFDictionaryRef) = dlsym(kit, "IOServiceGetMatchingService");
    CFTypeRef (*property)(uint32_t, CFStringRef, CFAllocatorRef, uint32_t) = dlsym(kit, "IORegistryEntryCreateCFProperty");
    int (*setProperties)(uint32_t, CFTypeRef) = dlsym(kit, "IORegistryEntrySetCFProperties");
    int (*release)(uint32_t) = dlsym(kit, "IOObjectRelease");
    const BOOL gpuStats = [action isEqual:@"GpuPerformance"];
    uint32_t entry = service(0, matching(gpuStats ? "NativeAdrenoGpuPublished" : "IOMobileFramebuffer"));
    if (!entry && gpuStats) entry = service(0, matching("NativeAdrenoControl"));
    if (!entry) { dlclose(kit); return @{@"error": gpuStats ? @"GPU control unavailable" : @"framebuffer unavailable"}; }
    NSMutableDictionary *out = [@{@"request_id": identifier,
        @"post_desktop": @YES, @"uid": @(getuid())} mutableCopy];
    if (gpuStats) {
        NSDictionary *request = @{@"DumpStats": @YES, @"RequestID": identifier};
        int status = setProperties(entry, (__bridge CFTypeRef)request);
        out[@"submit_status"] = @((uint32_t)status);
        out[@"completed_request_id"] = CFBridgingRelease(property(entry, CFSTR("LastStatsRequestID"), NULL, 0)) ?: NSNull.null;
        out[@"scope"] = @"Statistics only; inspect matching kernel begin/end and submission_sample markers for snapshot completeness";
        release(entry); dlclose(kit); return out;
    }
    id available = CFBridgingRelease(property(entry, CFSTR("NabuDpuDiagnosticAvailable"), NULL, 0));
    out[@"available"] = available ?: @NO;
    if (![available isEqual:@YES]) {
        out[@"error"] = @"diagnostic boot option unavailable";
    } else {
        NSString *command = [action isEqual:@"DpuSnapshot"] ? @"Snapshot" :
            ([action isEqual:@"DpuActivateGopPolled"] ? @"ActivateGopPolled" :
             ([action isEqual:@"DpuResumeIrq"] ? @"ResumeIrq" :
              ([action isEqual:@"DpuActivateGop"] ? @"ActivateGop" :
               ([action isEqual:@"DpuFlipGop"] ? @"FlipGop" : @"HaltResume"))));
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

// Root collects stopped windows only. Host acknowledgement is a separate
// command after the paired host has durably saved and validated these bytes.
NSDictionary *nabuGpuTraceRequest(NSString *identifier, NSDictionary *parameters) {
    if (getuid() != 0) {
        NSMutableDictionary *result = [pairedDpuRequest(@"GpuTrace", identifier, parameters) mutableCopy];
        if (result[@"root_trace_path"]) {
            NSString *name = [NSString stringWithFormat:@"frame-trace-%u.bin", [result[@"result"][@"window"] unsignedIntValue]];
            NSString *path = [@"/private/var/mobile/Media/NabuServices" stringByAppendingPathComponent:name];
            NSData *data = [NSData dataWithContentsOfFile:result[@"root_trace_path"]];
            NSError *error = nil;
            if (!data || ![data writeToFile:path options:NSDataWritingAtomic error:&error])
                result[@"error"] = error.localizedDescription ?: @"Trace handoff read failed";
            else result[@"afc_trace_path"] = [@"/NabuServices" stringByAppendingPathComponent:name];
        }
        return result;
    }
    NSMutableDictionary *out = [@{@"request_id": identifier, @"uid": @(getuid())} mutableCopy];
    if (![parameters isKindOfClass:NSDictionary.class]) { out[@"error"] = @"Missing trace parameters"; return out; }
    NSString *command = parameters[@"TraceCommand"];
    if (![command isKindOfClass:NSString.class] ||
        ![@[@"Start", @"Stop", @"Snapshot", @"Export", @"Acknowledge"] containsObject:command]) {
        out[@"error"] = @"Invalid trace command"; return out;
    }
    void *kit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW);
    if (!kit) { out[@"error"] = @"IOKit unavailable"; return out; }
    CFMutableDictionaryRef (*matching)(const char *) = dlsym(kit, "IOServiceMatching");
    uint32_t (*service)(uint32_t, CFDictionaryRef) = dlsym(kit, "IOServiceGetMatchingService");
    CFTypeRef (*property)(uint32_t, CFStringRef, CFAllocatorRef, uint32_t) = dlsym(kit, "IORegistryEntryCreateCFProperty");
    int (*setProperties)(uint32_t, CFTypeRef) = dlsym(kit, "IORegistryEntrySetCFProperties");
    int (*release)(uint32_t) = dlsym(kit, "IOObjectRelease");
    uint32_t entry = service(0, matching("NativeAdrenoGpuPublished"));
    if (!entry) entry = service(0, matching("NativeAdrenoControl"));
    if (!entry) { dlclose(kit); out[@"error"] = @"GPU control unavailable"; return out; }
    NSDictionary *(^request)(NSDictionary *) = ^NSDictionary *(NSDictionary *fields) {
        NSMutableDictionary *values = [fields mutableCopy]; values[@"RequestID"] = identifier;
        int status = setProperties(entry, (__bridge CFTypeRef)values);
        NSDictionary *result = CFBridgingRelease(property(entry, CFSTR("LastTraceResult"), NULL, 0));
        if (status || ![result isKindOfClass:NSDictionary.class] || ![result[@"RequestID"] isEqual:identifier])
            return @{@"status": @((uint32_t)status), @"error": @"Trace command or matching result failed"};
        return result;
    };
    if (![command isEqual:@"Export"]) {
        out[@"result"] = request(parameters);
    } else {
        NSNumber *window = parameters[@"Window"];
        NSDictionary *metadata = request(@{@"TraceCommand": @"Snapshot"});
        if (![window isKindOfClass:NSNumber.class] || !window.unsignedIntValue ||
            [metadata[@"status"] unsignedIntValue] || metadata[@"error"] ||
            [metadata[@"active"] boolValue] || ![metadata[@"window"] isEqual:window]) {
            out[@"error"] = @"Export requires the requested stopped window"; out[@"result"] = metadata;
        } else {
            NSString *path = [dpuDirectory stringByAppendingPathComponent:
                [NSString stringWithFormat:@"trace-%u.bin", window.unsignedIntValue]];
            NSString *temporary = [path stringByAppendingString:@".tmp"];
            FILE *file = fopen(temporary.fileSystemRepresentation, "wb");
            uint32_t offset = 0, count = [metadata[@"count"] unsignedIntValue];
            BOOL good = file != NULL;
            while (good && offset < count) {
                NSDictionary *chunk = request(@{@"TraceCommand": @"Read", @"Window": window, @"Offset": @(offset)});
                NSData *data = chunk[@"records"];
                uint32_t copied = [chunk[@"copied"] unsignedIntValue];
                good = ![chunk[@"status"] unsignedIntValue] && !chunk[@"error"] &&
                    [chunk[@"window"] isEqual:window] && [chunk[@"count"] unsignedIntValue] == count &&
                    [chunk[@"offset"] unsignedIntValue] == offset && copied && copied <= count - offset &&
                    [chunk[@"record_bytes"] unsignedIntValue] == 48 && [data isKindOfClass:NSData.class] &&
                    data.length == (NSUInteger)copied * 48;
                if (good) good = fwrite(data.bytes, 1, data.length, file) == data.length;
                if (good) { offset += copied; metadata = chunk; }
            }
            if (file) {
                if (fflush(file) || fsync(fileno(file))) good = NO;
                if (fclose(file)) good = NO;
            }
            NSMutableDictionary *clean = [metadata mutableCopy]; [clean removeObjectForKey:@"records"];
            out[@"result"] = clean;
            if (!good || rename(temporary.fileSystemRepresentation, path.fileSystemRepresentation) ||
                chmod(path.fileSystemRepresentation, 0644)) out[@"error"] = @"Trace export incomplete; window retained";
            else { out[@"root_trace_path"] = path; out[@"exported_bytes"] = @((uint64_t)offset * 48); }
        }
    }
    release(entry); dlclose(kit); return out;
}

// A dedicated root launch job selects this entry point. The regular services
// probe remains mobile; the root process accepts only the named diagnostics.
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
        // Requests can arrive after a long visual inspection in the same boot.
        // Keep the explicitly requested diagnostic service alive until shutdown.
        for (;;) {
            @autoreleasepool {
                NSDictionary *request = [NSDictionary dictionaryWithContentsOfFile:requestPath];
                if (request) {
                    [fm removeItemAtPath:requestPath error:NULL];
                    NSString *action = request[@"Action"], *identifier = request[@"ID"];
                    if (([action isEqual:@"DpuSnapshot"] || [action isEqual:@"DpuHaltResume"] ||
                         [action isEqual:@"DpuActivateGop"] || [action isEqual:@"DpuFlipGop"] ||
                         [action isEqual:@"DpuActivateGopPolled"] || [action isEqual:@"DpuResumeIrq"] ||
                         [action isEqual:@"GpuPerformance"] || [action isEqual:@"GpuTrace"]) &&
                        [identifier isKindOfClass:NSString.class] && identifier.length && identifier.length <= 64) {
                        NSDictionary *result = [action isEqual:@"GpuTrace"] ?
                            nabuGpuTraceRequest(identifier, request[@"TraceRequest"]) : nabuDpuRequest(action, identifier);
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
