/* Local software bring-up: inspect actual files and LaunchServices records.
 * The default action is read-only. A paired host may request registration of
 * named missing staged apps through AFC; no arbitrary commands are accepted.
 */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <ifaddrs.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <limits.h>
#include <stdlib.h>
#include <sys/attr.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <sys/sysctl.h>
#include <time.h>
#include <unistd.h>

@interface LSApplicationWorkspace : NSObject
+ (instancetype)defaultWorkspace;
- (NSArray *)allApplications;
- (BOOL)registerApplication:(NSURL *)url;
- (BOOL)registerApplicationDictionary:(NSDictionary *)info;
@end

@interface MIExecutableBundle : NSObject
+ (instancetype)bundleForURL:(NSURL *)url error:(NSError **)error;
@end

@interface MILaunchServicesDatabaseGatherer : NSObject
+ (NSArray *)fetchInfoForBundle:(MIExecutableBundle *)bundle inContainer:(id)container withError:(NSError **)error;
@end

@interface ICLBundleRecord : NSObject
+ (NSArray<NSDictionary *> *)bundleRecordArrayToInfoDictionaryArray:(NSArray *)records;
@end

static NSString *const reportDirectory = @"/private/var/mobile/Media/NabuServices";
extern NSDictionary *nabuWallpaperSnapshot(void);
extern void nabuStartSQLiteVnodeWatch(void);
extern NSDictionary *nabuExperienceSnapshot(void);
extern void nabuInstallExperienceCompatibility(void);
extern NSDictionary *nabuBluetoothSnapshot(void);
extern NSDictionary *nabuBluetoothUseSingleAdvertising(void);
extern NSDictionary *nabuBluetoothTransportTrial(void);
extern NSDictionary *nabuBluetoothSocketTrial(void);
extern NSDictionary *nabuWiFiControlTrial(NSString *action);
extern NSDictionary *nabuAudioRequest(NSString *action, NSString *identifier);
extern NSDictionary *nabuDpuRequest(NSString *action, NSString *identifier);

static void saveReport(NSDictionary *report, NSString *name);

static NSDictionary *systemConfigurationInventory(void) {
    static BOOL started;
    NSString *path = [reportDirectory stringByAppendingPathComponent:@"wireless-system-configuration.json"];
    if (!started) {
        started = YES;
        saveReport(@{@"stage": @"queued", @"pid": @(getpid())}, @"wireless-system-configuration.json");
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_UTILITY, 0), ^{
            @autoreleasepool {
                NSMutableDictionary *out = [@{@"pid": @(getpid()), @"read_only": @YES,
                    @"started_time": @((long long)time(NULL))} mutableCopy];
                void (^checkpoint)(NSString *) = ^(NSString *stage) {
                    out[@"stage"] = stage;
                    out[@"updated_time"] = @((long long)time(NULL));
                    saveReport(out, @"wireless-system-configuration.json");
                };
                checkpoint(@"load-framework");
                void *sc = dlopen("/System/Library/Frameworks/SystemConfiguration.framework/SystemConfiguration", RTLD_NOW);
                if (!sc) { checkpoint(@"framework-unavailable"); return; }
                CFTypeRef (*create)(CFAllocatorRef, CFStringRef, void *, void *) = dlsym(sc, "SCDynamicStoreCreate");
                CFTypeRef (*copyValue)(CFTypeRef, CFStringRef) = dlsym(sc, "SCDynamicStoreCopyValue");
                int (*scError)(void) = dlsym(sc, "SCError");
                checkpoint(@"create-session");
                CFTypeRef store = create(NULL, CFSTR("Nabu wireless inventory"), NULL, NULL);
                out[@"session_created"] = @(store != NULL);
                if (store) {
                    for (NSString *key in @[@"State:/Network/Interface", @"Plugin:InterfaceNamer"]) {
                        checkpoint([@"read:" stringByAppendingString:key]);
                        id value = CFBridgingRelease(copyValue(store, (__bridge CFStringRef)key));
                        out[key] = value ?: NSNull.null;
                        out[[key stringByAppendingString:@":error"]] = @(value ? 0 : scError());
                    }
                    CFRelease(store);
                } else out[@"session_error"] = @(scError());
                CFArrayRef (*copyAll)(void) = dlsym(sc, "SCNetworkInterfaceCopyAll");
                CFStringRef (*bsdName)(CFTypeRef) = dlsym(sc, "SCNetworkInterfaceGetBSDName");
                CFStringRef (*interfaceType)(CFTypeRef) = dlsym(sc, "SCNetworkInterfaceGetInterfaceType");
                checkpoint(@"SCNetworkInterfaceCopyAll-enter");
                CFArrayRef all = copyAll();
                checkpoint(@"SCNetworkInterfaceCopyAll-return");
                NSMutableArray *interfaces = [NSMutableArray array];
                if (all) {
                    for (CFIndex i = 0; i < CFArrayGetCount(all); ++i) {
                        CFTypeRef entry = CFArrayGetValueAtIndex(all, i);
                        [interfaces addObject:@{@"bsd_name": (__bridge id)bsdName(entry) ?: NSNull.null,
                            @"type": (__bridge id)interfaceType(entry) ?: NSNull.null}];
                    }
                    CFRelease(all);
                }
                out[@"interfaces"] = interfaces;
                dlclose(sc);
                checkpoint(@"complete");
            }
        });
    }
    NSData *data = [NSData dataWithContentsOfFile:path];
    return data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : @{@"stage": @"queued"};
}

static NSDictionary *wirelessSnapshot(void) {
    NSMutableDictionary *software = [NSMutableDictionary dictionary];
    NSMutableArray *jobs = [NSMutableArray array];
    for (NSString *path in @[@"/redwood/LaunchDaemons/com.apple.wifid.plist",
                            @"/System/Library/LaunchDaemons/com.apple.wifid.plist"]) {
        NSDictionary *job = [NSDictionary dictionaryWithContentsOfFile:path];
        [jobs addObject:@{@"path": path,
            @"exists": @([[NSFileManager defaultManager] fileExistsAtPath:path]),
            @"plist_readable": @(job != nil),
            @"device_tree_requirement": job[@"_LimitLoadToDeviceTree"] ?: NSNull.null,
            @"mach_services": [job[@"MachServices"] allKeys] ?: @[]}];
    }
    software[@"wifid_jobs"] = jobs;
    struct ifaddrs *interfaces = NULL;
    int result = getifaddrs(&interfaces);
    software[@"getifaddrs_errno"] = @(result == 0 ? 0 : errno);
    NSMutableDictionary *bsd = [NSMutableDictionary dictionary];
    if (result == 0) {
        for (struct ifaddrs *entry = interfaces; entry; entry = entry->ifa_next) {
            NSString *name = @(entry->ifa_name);
            NSMutableDictionary *record = bsd[name];
            if (!record) {
                record = [@{@"flags": @(entry->ifa_flags), @"address_families": [NSMutableArray array], @"ip_addresses": [NSMutableArray array]} mutableCopy];
                bsd[name] = record;
            }
            if (entry->ifa_addr) {
                NSNumber *family = @(entry->ifa_addr->sa_family);
                if (![record[@"address_families"] containsObject:family])
                    [record[@"address_families"] addObject:family];
                const void *address = NULL;
                if (entry->ifa_addr->sa_family == AF_INET)
                    address = &((struct sockaddr_in *)entry->ifa_addr)->sin_addr;
                else if (entry->ifa_addr->sa_family == AF_INET6)
                    address = &((struct sockaddr_in6 *)entry->ifa_addr)->sin6_addr;
                char text[INET6_ADDRSTRLEN] = {0};
                if (address && inet_ntop(entry->ifa_addr->sa_family, address, text, sizeof(text)))
                    [record[@"ip_addresses"] addObject:@(text)];
            }
        }
        freeifaddrs(interfaces);
    }
    software[@"bsd_interfaces"] = bsd;
    void *kit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW);
    if (!kit) return @{@"read_only": @YES, @"error": @"IOKit unavailable", @"software": software};
    uint32_t (*fromPath)(uint32_t, const char *) = dlsym(kit, "IORegistryEntryFromPath");
    CFTypeRef (*property)(uint32_t, CFStringRef, CFAllocatorRef, uint32_t) = dlsym(kit, "IORegistryEntryCreateCFProperty");
    int (*release)(uint32_t) = dlsym(kit, "IOObjectRelease");
    CFMutableDictionaryRef (*matching)(const char *) = dlsym(kit, "IOServiceMatching");
    int (*services)(uint32_t, CFDictionaryRef, uint32_t *) = dlsym(kit, "IOServiceGetMatchingServices");
    uint32_t (*next)(uint32_t) = dlsym(kit, "IOIteratorNext");
    NSMutableDictionary *classes = [NSMutableDictionary dictionary];
    for (NSString *name in @[@"IO80211Controller", @"IO80211Interface", @"IONetworkInterface"]) {
        uint32_t iterator = 0, entry = 0;
        int status = services(0, matching(name.UTF8String), &iterator);
        unsigned count = 0;
        NSMutableArray *entries = [NSMutableArray array];
        if (status == 0) while ((entry = next(iterator))) {
            ++count;
            NSMutableDictionary *properties = [NSMutableDictionary dictionary];
            for (NSString *key in @[@"IOInterfaceName", @"BSD Name", @"IOInterfaceNamePrefix",
                                    @"IOInterfaceType", @"IOInterfaceUnit", @"IOBuiltin",
                                    @"IO80211InterfaceRole", @"IO80211VirtualInterfaceRole"]) {
                id value = CFBridgingRelease(property(entry, (__bridge CFStringRef)key, NULL, 0));
                if (value) properties[key] = value;
            }
            [entries addObject:properties];
            release(entry);
        }
        if (iterator) release(iterator);
        classes[name] = @{@"status": @(status), @"count": @(count), @"entries": entries};
    }
    software[@"iokit_matching_classes"] = classes;
    int (*iterate)(uint32_t, const char *, uint32_t, uint32_t *) = dlsym(kit, "IORegistryCreateIterator");
    int (*busyState)(uint32_t, uint32_t *) = dlsym(kit, "IOServiceGetBusyState");
    int (*getPath)(uint32_t, const char *, char *) = dlsym(kit, "IORegistryEntryGetPath");
    int (*getClass)(uint32_t, char *) = dlsym(kit, "IOObjectGetClass");
    NSMutableArray *busy = [NSMutableArray array];
    uint32_t busyIterator = 0, busyEntry = 0;
    int iteratorStatus = iterate(0, "IOService", 1, &busyIterator);
    if (!iteratorStatus) while ((busyEntry = next(busyIterator))) {
        uint32_t count = 0;
        if (!busyState(busyEntry, &count) && count) {
            char path[512] = {0}, name[128] = {0};
            int pathStatus = getPath(busyEntry, "IOService", path);
            getClass(busyEntry, name);
            [busy addObject:@{@"path": @(path), @"path_status": @(pathStatus),
                @"class": @(name), @"busy": @(count)}];
        }
        release(busyEntry);
    }
    if (busyIterator) release(busyIterator);
    software[@"iokit_busy_services"] = @{@"iterator_status": @(iteratorStatus), @"entries": busy};
    NSMutableDictionary *defaults = [NSMutableDictionary dictionary];
    for (NSString *path in @[@"IODeviceTree:/defaults", @"IOService:/GenericARMPE/defaults"]) {
        uint32_t entry = fromPath(0, path.UTF8String);
        NSMutableDictionary *values = [@{@"found": @(entry != 0)} mutableCopy];
        for (NSString *key in @[@"AAPL,ignore", @"sleep-disabled", @"kern.vm_compressor", @"name"]) {
            id value = entry ? CFBridgingRelease(property(entry, (__bridge CFStringRef)key, NULL, 0)) : nil;
            if ([value isKindOfClass:NSData.class]) values[key] = @{@"base64": [value base64EncodedStringWithOptions:0]};
            else if (value) values[key] = value;
        }
        if (entry) release(entry);
        defaults[path] = values;
    }
    software[@"defaults_nodes"] = defaults;
    software[@"system_configuration"] = systemConfigurationInventory();
    uint32_t chosen = fromPath(0, "IODeviceTree:/chosen");
    id value = chosen ? CFBridgingRelease(property(chosen, CFSTR("nabu-wireless-report"), NULL, 0)) : nil;
    NSMutableDictionary *crash = [NSMutableDictionary dictionary];
    for (NSString *phase in @[@"pfr", @"restart", @"end"]) {
        NSString *key = [@"nabu-wlan-crash-" stringByAppendingString:phase];
        id data = chosen ? CFBridgingRelease(property(chosen, (__bridge CFStringRef)key, NULL, 0)) : nil;
        if ([data isKindOfClass:NSData.class]) crash[phase] = [data base64EncodedStringWithOptions:0];
    }
    if (chosen) release(chosen);
    dlclose(kit);
    return @{@"read_only": @YES, @"registry_entry_found": @(chosen != 0),
             @"report": value ?: NSNull.null, @"wlan_smem611_snapshots_base64": crash,
             @"software": software,
             @"interpretation": @"Job files, matching services and BSD interfaces are presence observations; they do not prove radio readiness, association or packet delivery."};
}

static NSDictionary *gpuSnapshot(void) {
    void *kit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW);
    uint32_t (*fromPath)(uint32_t, const char *) = dlsym(kit, "IORegistryEntryFromPath");
    CFTypeRef (*property)(uint32_t, CFStringRef, CFAllocatorRef, uint32_t) = dlsym(kit, "IORegistryEntryCreateCFProperty");
    int (*release)(uint32_t) = dlsym(kit, "IOObjectRelease");
    uint32_t chosen = fromPath(0, "IODeviceTree:/chosen");
    id state = chosen ? CFBridgingRelease(property(chosen, CFSTR("nabu-gpu-state"), NULL, 0)) : nil;
    id data = chosen ? CFBridgingRelease(property(chosen, CFSTR("nabu-gpu-stats"), NULL, 0)) : nil;
    NSMutableDictionary *result = [@{@"read_only": @YES, @"state": state ?: NSNull.null,
        @"hardware_command_completed": @NO, @"graphics_rendering_verified": @NO} mutableCopy];
    if ([data isKindOfClass:NSData.class] && [data length] == 24 * sizeof(uint32_t)) {
        uint32_t stats[24]; memcpy(stats, [data bytes], sizeof(stats));
        NSMutableArray *values = [NSMutableArray array];
        for (unsigned i = 0; i < 24; ++i) [values addObject:@(stats[i])];
        result[@"stats"] = values;
        result[@"phase"] = @(stats[0]); result[@"error"] = @(stats[1]);
        result[@"issued_fence"] = @(stats[8]); result[@"completed_fence"] = @(stats[9]);
        result[@"scratch"] = @(stats[10]);
        result[@"cp_stopped"] = @(stats[20]); result[@"gmu_stop_status"] = @(stats[21]);
        result[@"hardware_command_completed"] = @(stats[8] != 0 && stats[8] == stats[9] && stats[10] == 0x6401cafe);
        result[@"offscreen_raster_verified"] = @(stats[23] == 1 && stats[19] == 512 && stats[14] != 0 && stats[14] == stats[15]);
        result[@"render_pixels_matched"] = @(stats[19]);
        result[@"render_issued_fence"] = @(stats[14]); result[@"render_completed_fence"] = @(stats[15]);
        result[@"metal_verified"] = @NO;
    }
    if (chosen) release(chosen);
    dlclose(kit);
    return result;
}

static NSDictionary *bulkDirectory(void) {
    struct attrlist attributes = {0};
    attributes.bitmapcount = ATTR_BIT_MAP_COUNT;
    attributes.commonattr = ATTR_CMN_RETURNED_ATTRS | ATTR_CMN_ERROR | ATTR_CMN_NAME | ATTR_CMN_OBJTYPE;
    attributes.dirattr = ATTR_DIR_ENTRYCOUNT | ATTR_DIR_MOUNTSTATUS;
    NSMutableArray *entries = [NSMutableArray array];
    int fd = open("/Applications", O_RDONLY);
    if (fd < 0) return @{@"open_errno": @(errno)};
    char buffer[16384];
    int count;
    while ((count = getattrlistbulk(fd, &attributes, buffer, sizeof(buffer), 0)) > 0) {
        char *cursor = buffer;
        for (int i = 0; i < count; i++) {
            uint32_t length;
            attribute_set_t returned;
            memcpy(&length, cursor, 4);
            memcpy(&returned, cursor + 4, sizeof(returned));
            char *value = cursor + 4 + sizeof(returned);
            NSMutableDictionary *entry = [@{@"returned_common": @(returned.commonattr),
                @"returned_directory": @(returned.dirattr), @"record_bytes": @(length)} mutableCopy];
            if (returned.commonattr & ATTR_CMN_ERROR) {
                uint32_t error; memcpy(&error, value, 4); value += 4; entry[@"error"] = @(error);
            }
            if (returned.commonattr & ATTR_CMN_NAME) {
                attrreference_t name; memcpy(&name, value, sizeof(name));
                entry[@"name"] = name.attr_length ? @(value + name.attr_dataoffset) : @"";
                value += sizeof(name);
            }
            if (returned.commonattr & ATTR_CMN_OBJTYPE) {
                uint32_t type; memcpy(&type, value, 4); value += 4; entry[@"type"] = @(type);
            }
            if (returned.dirattr & ATTR_DIR_ENTRYCOUNT) {
                uint32_t children; memcpy(&children, value, 4); value += 4; entry[@"children"] = @(children);
            }
            if (returned.dirattr & ATTR_DIR_MOUNTSTATUS) {
                uint32_t mounted; memcpy(&mounted, value, 4); entry[@"mount_status"] = @(mounted);
            }
            [entries addObject:entry];
            cursor += length;
        }
    }
    int error = count < 0 ? errno : 0;
    close(fd);
    return @{@"entries": entries, @"final_errno": @(error), @"common_attributes": @(attributes.commonattr)};
}

static NSDictionary *pathInfo(NSString *path) {
    NSMutableDictionary *out = [@{@"path": path} mutableCopy];
    struct stat st;
    if (stat(path.fileSystemRepresentation, &st) == 0) {
        out[@"inode"] = @(st.st_ino);
        out[@"device"] = @(st.st_dev);
        out[@"mode"] = @(st.st_mode);
        out[@"bytes"] = @(st.st_size);
    } else out[@"stat_errno"] = @(errno);
    int fd = open(path.fileSystemRepresentation, O_RDONLY);
    if (fd >= 0) {
        char actual[PATH_MAX];
        if (fcntl(fd, F_GETPATH, actual) == 0)
            out[@"fd_path"] = @(actual);
        else out[@"getpath_errno"] = @(errno);
        close(fd);
    } else out[@"open_errno"] = @(errno);
    return out;
}

static id jsonValue(id value) {
    if ([value isKindOfClass:NSURL.class]) return [value path] ?: [value absoluteString];
    if ([value isKindOfClass:NSString.class] || [value isKindOfClass:NSNumber.class] ||
        [value isKindOfClass:NSArray.class] || [value isKindOfClass:NSDictionary.class])
        return value;
    return value ? [value description] : NSNull.null;
}

static NSArray *applications(LSApplicationWorkspace *workspace) {
    NSMutableArray *out = [NSMutableArray array];
    for (id proxy in [workspace allApplications]) {
        NSMutableDictionary *app = [NSMutableDictionary dictionary];
        for (NSString *key in @[@"bundleIdentifier", @"applicationIdentifier", @"applicationType",
                                @"bundleURL", @"containerURL", @"appTags", @"isInstalled",
                                @"isPlaceholder", @"isRestricted", @"isRemovedSystemApp"]) {
            if (![proxy respondsToSelector:NSSelectorFromString(key)]) continue;
            @try { app[key] = jsonValue([proxy valueForKey:key]); }
            @catch (NSException *error) { app[key] = @{@"exception": error.reason ?: error.name}; }
        }
        [out addObject:app];
    }
    return out;
}

static NSArray *appFiles(void) {
    NSFileManager *fm = NSFileManager.defaultManager;
    NSError *error = nil;
    NSArray *names = [fm contentsOfDirectoryAtPath:@"/Applications" error:&error];
    NSMutableArray *out = [NSMutableArray array];
    if (!names) return @[@{@"enumeration_error": error.description ?: @"unknown"}];
    NSArray *staged = [NSArray arrayWithContentsOfFile:@"/redwood/etc/staged-apps.plist"];
    // Include expected aliases even when readdir omits one of them.
    NSMutableSet *all = [NSMutableSet setWithArray:names];
    [all addObjectsFromArray:staged ?: @[]];
    for (NSString *name in [[all allObjects] sortedArrayUsingSelector:@selector(compare:)]) {
        if (![name hasSuffix:@".app"]) continue;
        NSString *path = [@"/Applications" stringByAppendingPathComponent:name];
        NSMutableDictionary *entry = [pathInfo(path) mutableCopy];
        entry[@"enumerated"] = @([names containsObject:name]);
        entry[@"staged"] = @([staged containsObject:name]);
        entry[@"parent"] = pathInfo([path stringByAppendingPathComponent:@".."]);
        NSString *infoPath = [path stringByAppendingPathComponent:@"Info.plist"];
        entry[@"info_file"] = pathInfo(infoPath);
        NSDictionary *info = [NSDictionary dictionaryWithContentsOfFile:infoPath];
        entry[@"info_readable"] = @(info != nil);
        NSMutableDictionary *selected = [NSMutableDictionary dictionary];
        for (NSString *key in @[@"CFBundleIdentifier", @"CFBundleExecutable", @"CFBundleDisplayName",
                                @"CFBundleName", @"SBAppTags", @"SBIconVisibilityDefaultVisible",
                                @"UIRequiredDeviceCapabilities", @"UIDeviceFamily", @"LSRequiresIPhoneOS"])
            if (info[key]) selected[key] = info[key];
        entry[@"info"] = selected;
        if (info[@"CFBundleExecutable"])
            entry[@"executable"] = pathInfo([path stringByAppendingPathComponent:info[@"CFBundleExecutable"]]);
        [out addObject:entry];
    }
    return out;
}

static NSDictionary *identityQuery(void) {
    void *library = dlopen("/usr/lib/libMobileGestalt.dylib", RTLD_NOW);
    CFTypeRef (*answer)(CFStringRef, void *, int32_t *) = dlsym(library, "MGCopyAnswerWithError");
    if (!answer) return @{@"symbol_available": @NO};
    int32_t error = 0;
    CFTypeRef value = answer(CFSTR("UniqueDeviceID"), NULL, &error);
    NSMutableDictionary *out = [@{@"error": @(error), @"has_value": @(value != NULL)} mutableCopy];
    if (value) {
        out[@"type"] = @(CFGetTypeID(value));
        if (CFGetTypeID(value) == CFStringGetTypeID()) out[@"length"] = @(CFStringGetLength(value));
        CFRelease(value);
    }
    return out;
}

static NSDictionary *processes(void) {
    void *library = dlopen("/usr/lib/libproc.dylib", RTLD_NOW);
    int (*list)(void *, int) = dlsym(library, "proc_listallpids");
    int (*name)(int, void *, uint32_t) = dlsym(library, "proc_name");
    if (!list || !name) return @{@"error": @"libproc symbols unavailable"};
    int capacity = list(NULL, 0) + 32;
    NSMutableData *buffer = [NSMutableData dataWithLength:(NSUInteger)capacity * sizeof(int)];
    int count = list(buffer.mutableBytes, (int)buffer.length);
    if (count < 0) return @{@"errno": @(errno)};
    int *pids = buffer.mutableBytes;
    NSMutableArray *out = [NSMutableArray array];
    for (int i = 0; i < count && i < capacity; i++) {
        char text[1024] = {0};
        if (name(pids[i], text, sizeof(text)) > 0)
            [out addObject:@{@"pid": @(pids[i]), @"name": @(text)}];
    }
    return @{@"entries": out, @"returned_count": @(count)};
}

static NSDictionary *snapshot(LSApplicationWorkspace *workspace) {
    NSMutableDictionary *out = [@{@"uid": @(getuid()), @"time": @((long long)time(NULL)),
        @"paths": @[pathInfo(@"/Applications"), pathInfo(@"/private/var/staged_system_apps"),
                     pathInfo(@"/System/Cryptexes/App"),
                     pathInfo(@"/System/Cryptexes/App/usr/libexec/com.apple.Safari.History"),
                     pathInfo(@"/System/Cryptexes/App/usr/libexec/webbookmarksd"),
                     pathInfo(@"/System/Cryptexes/OS")],
        @"processes": processes(),
        @"getattrlistbulk": bulkDirectory(),
        @"application_files": appFiles(), @"ls_applications": applications(workspace),
        @"mg_unique_device_id": identityQuery()} mutableCopy];
    NSMutableDictionary *methods = [NSMutableDictionary dictionary];
    for (NSString *name in @[@"allApplications", @"registerApplication:",
        @"_LSPrivateRebuildApplicationDatabasesForSystemApps:internal:user:"]) {
        Method method = class_getInstanceMethod(workspace.class, NSSelectorFromString(name));
        if (method) methods[name] = @(method_getTypeEncoding(method));
    }
    out[@"ls_method_types"] = methods;
    return out;
}

static void saveReport(NSDictionary *report, NSString *name) {
    NSError *error = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:&error];
    NSString *path = [reportDirectory stringByAppendingPathComponent:name];
    if (!data || ![data writeToFile:path options:NSDataWritingAtomic error:&error])
        NSLog(@"NABU SERVICES: report %@ failed %@", name, error);
    else NSLog(@"NABU SERVICES: saved %@ bytes=%lu", name, (unsigned long)data.length);
}

static NSDictionary *errorInfo(NSError *error) {
    if (!error) return @{};
    NSMutableDictionary *out = [@{@"domain": error.domain, @"code": @(error.code),
        @"description": error.localizedDescription ?: @"", @"details": error.userInfo.description ?: @""} mutableCopy];
    NSError *underlying = error.userInfo[NSUnderlyingErrorKey];
    if (underlying) out[@"underlying"] = errorInfo(underlying);
    return out;
}

static NSDictionary *installationDaemonContainer(void) {
    // Match the original 20F66 MIDaemonConfiguration query, but return its
    // error instead of entering that initializer's process-abort path.
    void *library = dlopen("/usr/lib/system/libsystem_containermanager.dylib", RTLD_NOW);
    void *(*create)(void) = dlsym(library, "container_query_create");
    void (*setClass)(void *, uint64_t) = dlsym(library, "container_query_set_class");
    void (*setIdentifiers)(void *, void *) = dlsym(library, "container_query_set_identifiers");
    void (*setPersona)(void *, const char *) = dlsym(library, "container_query_set_persona_unique_string");
    void (*setFlags)(void *, uint64_t) = dlsym(library, "container_query_operation_set_flags");
    void *(*getResult)(void *) = dlsym(library, "container_query_get_single_result");
    void *(*getError)(void *) = dlsym(library, "container_query_get_last_error");
    char *(*describeError)(void *) = dlsym(library, "container_error_copy_unlocalized_description");
    const char *(*getPath)(void *) = dlsym(library, "container_get_path");
    void (*freeQuery)(void *) = dlsym(library, "container_query_free");
    const char **primaryPersona = dlsym(library, "CONTAINER_PERSONA_PRIMARY");
    void *(*createString)(const char *) = dlsym(RTLD_DEFAULT, "xpc_string_create");
    void (*releaseXPC)(void *) = dlsym(RTLD_DEFAULT, "xpc_release");
    NSMutableDictionary *result = [@{ @"identifier": @"com.apple.installd", @"class": @10,
        @"flags": @0x900000001ULL, @"uid": @(getuid()), @"euid": @(geteuid()) } mutableCopy];
    void *query = create();
    setClass(query, 10);
    void *identifier = createString("com.apple.installd");
    setIdentifiers(query, identifier);
    releaseXPC(identifier);
    setPersona(query, *primaryPersona);
    setFlags(query, 0x900000001ULL);
    void *container = getResult(query);
    result[@"query_succeeded"] = @(container != NULL);
    if (container) result[@"path_present"] = @(getPath(container) != NULL);
    else {
        char *description = describeError(getError(query));
        result[@"error"] = description ? @(description) : @"container query returned no result";
        free(description);
    }
    freeQuery(query);
    dlclose(library);
    return result;
}

static NSDictionary *nativeRegister(LSApplicationWorkspace *workspace, NSString *path, NSString *identifier) {
    // Original 20F66 factory: reads the shipped signature and creates required
    // data/group containers. Never synthesize signer, container or plugin data.
    NSDictionary *container = installationDaemonContainer();
    saveReport(container, @"native-container-query.json");
    if (![container[@"query_succeeded"] boolValue]) return @{@"daemon_container": container};
    NSLog(@"NABU SERVICES: %@ loading original metadata framework", identifier);
    dlopen("/System/Library/PrivateFrameworks/InstalledContentLibrary.framework/InstalledContentLibrary", RTLD_NOW);
    Class bundleClass = NSClassFromString(@"MIExecutableBundle");
    Class gathererClass = NSClassFromString(@"MILaunchServicesDatabaseGatherer");
    Class recordClass = NSClassFromString(@"ICLBundleRecord");
    NSMutableDictionary *result = [@{@"metadata_source": @"original InstalledContentLibrary",
        @"creates_containers": @YES, @"daemon_container": container} mutableCopy];
    if (!bundleClass || !gathererClass || !recordClass) {
        result[@"error"] = @"original metadata classes unavailable";
        return result;
    }
    NSLog(@"NABU SERVICES: %@ constructing original executable bundle", identifier);
    NSError *error = nil;
    MIExecutableBundle *bundle = [bundleClass bundleForURL:[NSURL fileURLWithPath:path] error:&error];
    if (!bundle) {
        result[@"bundle_error"] = errorInfo(error);
        return result;
    }
    NSLog(@"NABU SERVICES: %@ gathering original installation metadata", identifier);
    NSArray *records = [gathererClass fetchInfoForBundle:bundle inContainer:nil withError:&error];
    if (!records) {
        result[@"gather_error"] = errorInfo(error);
        return result;
    }
    NSLog(@"NABU SERVICES: %@ converting %lu original records", identifier, (unsigned long)records.count);
    NSArray<NSDictionary *> *infos = [recordClass bundleRecordArrayToInfoDictionaryArray:records];
    NSMutableArray *summary = [NSMutableArray array];
    NSDictionary *application = nil;
    NSMutableDictionary *plugins = [NSMutableDictionary dictionary];
    for (NSDictionary *info in infos) {
        NSMutableDictionary *item = [@{@"keys": [info.allKeys sortedArrayUsingSelector:@selector(compare:)]} mutableCopy];
        for (NSString *key in @[@"CFBundleIdentifier", @"ApplicationType", @"Path", @"Container",
                                @"IsContainerized", @"IsPlaceholder", @"SignerIdentity", @"SignerOrganization"])
            if (info[key]) item[key] = jsonValue(info[key]);
        if ([info[@"Entitlements"] isKindOfClass:NSDictionary.class])
            item[@"entitlement_keys"] = [((NSDictionary *)info[@"Entitlements"]).allKeys sortedArrayUsingSelector:@selector(compare:)];
        if ([info[@"_LSBundlePlugins"] isKindOfClass:NSDictionary.class])
            item[@"plugin_identifiers"] = [((NSDictionary *)info[@"_LSBundlePlugins"]).allKeys sortedArrayUsingSelector:@selector(compare:)];
        [summary addObject:item];
        if ([info[@"ApplicationType"] isEqual:@"PluginKitPlugin"] &&
            [info[@"PluginOwnerBundleID"] isEqual:identifier]) {
            plugins[info[@"CFBundleIdentifier"]] = info;
        } else if (![info[@"ApplicationType"] isEqual:@"PluginKitPlugin"] &&
                   [info[@"CFBundleIdentifier"] isEqual:identifier] && [info[@"Path"] isEqual:path]) {
            application = info;
        }
    }
    result[@"generated_records"] = summary;
    if (!application) result[@"error"] = @"original factory did not return the requested application";
    else {
        // Match the original app-and-contents collapse: retain plugin metadata
        // verbatim and attach only extensions owned by the selected app.
        NSMutableDictionary *submission = [application mutableCopy];
        if (plugins.count) submission[@"_LSBundlePlugins"] = plugins;
        result[@"plugin_count"] = @(plugins.count);
        NSLog(@"NABU SERVICES: %@ submitting original dictionary with %lu plugins", identifier, (unsigned long)plugins.count);
        result[@"register_return"] = @([workspace registerApplicationDictionary:submission]);
    }
    return result;
}

static NSDictionary *registerMissing(LSApplicationWorkspace *workspace, NSArray *bundleIDs, BOOL nativeMetadata) {
    NSMutableSet *installed = [NSMutableSet set];
    for (NSDictionary *app in applications(workspace)) {
        id identifier = app[@"bundleIdentifier"] ?: app[@"applicationIdentifier"];
        if ([identifier isKindOfClass:NSString.class]) [installed addObject:identifier];
    }
    NSMutableArray *results = [NSMutableArray array];
    for (NSDictionary *app in appFiles()) {
        NSString *identifier = app[@"info"][@"CFBundleIdentifier"];
        if (!identifier || ![app[@"staged"] boolValue] || ![bundleIDs containsObject:identifier]) continue;
        NSMutableDictionary *result = [@{@"bundle_id": identifier, @"path": app[@"path"]} mutableCopy];
        if ([installed containsObject:identifier]) result[@"already_registered"] = @YES;
        else if (nativeMetadata) [result addEntriesFromDictionary:nativeRegister(workspace, app[@"path"], identifier)];
        else result[@"register_return"] = @([workspace registerApplication:[NSURL fileURLWithPath:app[@"path"]]]);
        [results addObject:result];
    }
    return @{@"applications": results};
}

int main(void) {
    @autoreleasepool {
        NSFileManager *fm = NSFileManager.defaultManager;
        [fm createDirectoryAtPath:reportDirectory withIntermediateDirectories:YES attributes:nil error:NULL];
        NSString *requestPath = [reportDirectory stringByAppendingPathComponent:@"request.plist"];
        // A request belongs only to the current live test, never to a later boot.
        [fm removeItemAtPath:requestPath error:NULL];
        nabuStartSQLiteVnodeWatch();
        sleep(45);
        dlopen("/System/Library/Frameworks/MobileCoreServices.framework/MobileCoreServices", RTLD_NOW);
        LSApplicationWorkspace *workspace = [NSClassFromString(@"LSApplicationWorkspace") defaultWorkspace];
        if (!workspace) { saveReport(@{@"error": @"LSApplicationWorkspace unavailable"}, @"baseline.json"); return 1; }
        saveReport(snapshot(workspace), @"baseline.json");
        for (unsigned i = 0; i < 240; i++) {
            @autoreleasepool {
                NSDictionary *request = [NSDictionary dictionaryWithContentsOfFile:requestPath];
                if (request) {
                    [fm removeItemAtPath:requestPath error:NULL];
                    NSString *action = request[@"Action"];
                    NSMutableDictionary *result = [@{@"request": request, @"before": snapshot(workspace)} mutableCopy];
                    saveReport(result, @"request-before.json");
                    @try {
                        if ([action isEqual:@"Inventory"]) result[@"read_only"] = @YES;
                        else if ([action isEqual:@"GPUInventory"]) {
                            result[@"read_only"] = @YES;
                            result[@"gpu"] = gpuSnapshot();
                        }
                        else if ([action isEqual:@"DpuSnapshot"] || [action isEqual:@"DpuHaltResume"]) {
                            result[@"dpu"] = nabuDpuRequest(action, request[@"ID"] ?: @"");
                        }
                        else if ([action isEqual:@"WirelessInventory"]) {
                            result[@"read_only"] = @YES;
                            result[@"wireless"] = wirelessSnapshot();
                        }
                        else if ([action isEqual:@"WirelessNativeScan"] ||
                                 [action isEqual:@"WirelessNativePowerOff"] ||
                                 [action isEqual:@"WirelessNativePowerOn"] ||
                                 [action isEqual:@"WirelessNativeSignal"]) {
                            result[@"wireless_control"] = nabuWiFiControlTrial(action);
                            result[@"wireless"] = wirelessSnapshot();
                        }
                        else if ([action isEqual:@"AudioInventory"] || [action isEqual:@"AudioBluetoothPlaybackTrial"]) {
                            result[@"audio"] = nabuAudioRequest(action, request[@"ID"] ?: @"");
                        }
                        else if ([action isEqual:@"BluetoothInventory"]) {
                            result[@"read_only"] = @YES;
                            result[@"bluetooth"] = nabuBluetoothSnapshot();
                        }
                        else if ([action isEqual:@"BluetoothUseSingleAdvertising"]) {
                            result[@"read_only"] = @NO;
                            result[@"policy"] = nabuBluetoothUseSingleAdvertising();
                            result[@"bluetooth"] = nabuBluetoothSnapshot();
                        }
                        else if ([action isEqual:@"BluetoothTransportTrial"]) {
                            result[@"bluetooth"] = nabuBluetoothSnapshot();
                            result[@"transport"] = nabuBluetoothTransportTrial();
                        }
                        else if ([action isEqual:@"BluetoothSocketTrial"]) {
                            result[@"bluetooth"] = nabuBluetoothSnapshot();
                            result[@"transport"] = nabuBluetoothSocketTrial();
                        }
                        else if ([action isEqual:@"ExperienceInventory"]) {
                            result[@"read_only"] = @YES;
                            result[@"experience"] = nabuExperienceSnapshot();
                        }
                        else if ([action isEqual:@"ExperienceCompatibilityTrial"]) {
                            result[@"scope"] = @"Process-local method changes after paired host request; no other process or preferences changed";
                            result[@"experience_original"] = nabuExperienceSnapshot();
                            saveReport(result, @"experience-original.json");
                            nabuInstallExperienceCompatibility();
                            result[@"experience_candidate"] = nabuExperienceSnapshot();
                        }
                        else if ([action isEqual:@"WallpaperInventory"]) {
                            result[@"read_only"] = @YES;
                            result[@"wallpaper"] = nabuWallpaperSnapshot();
                        }
                        else if ([action isEqual:@"RegisterMissingStaged"] && [request[@"BundleIDs"] isKindOfClass:NSArray.class])
                            result[@"registration"] = registerMissing(workspace, request[@"BundleIDs"], NO);
                        else if ([action isEqual:@"RegisterNativeStaged"] && [request[@"BundleIDs"] isKindOfClass:NSArray.class])
                            result[@"registration"] = registerMissing(workspace, request[@"BundleIDs"], YES);
                        else result[@"error"] = @"unsupported action";
                    } @catch (NSException *error) { result[@"exception"] = error.reason ?: error.name; }
                    result[@"after"] = snapshot(workspace);
                    saveReport(result, @"request-result.json");
                }
            }
            sleep(5);
        }
        NSLog(@"NABU SERVICES: diagnostic request window ended");
    }
    return 0;
}
