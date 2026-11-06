/* Local software bring-up: inspect actual files and LaunchServices records.
 * The default action is read-only. A paired host may request one of the two
 * stock LS repair operations through AFC; no arbitrary commands are accepted.
 */
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/attr.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <time.h>
#include <unistd.h>

@interface LSApplicationWorkspace : NSObject
+ (instancetype)defaultWorkspace;
- (NSArray *)allApplications;
- (BOOL)registerApplication:(NSURL *)url;
- (BOOL)_LSPrivateRebuildApplicationDatabasesForSystemApps:(BOOL)system
                                               internal:(BOOL)internal
                                                   user:(BOOL)user;
@end

static NSString *const reportDirectory = @"/private/var/mobile/Media/NabuServices";

static NSDictionary *bulkDirectory(void) {
    struct attrlist attributes = {0};
    attributes.bitmapcount = ATTR_BIT_MAP_COUNT;
    attributes.commonattr = ATTR_CMN_RETURNED_ATTRS | ATTR_CMN_ERROR | ATTR_CMN_NAME | ATTR_CMN_OBJTYPE;
    NSMutableArray *entries = [NSMutableArray array];
    int fd = open("/Applications", O_RDONLY);
    if (fd < 0) return @{@"open_errno": @(errno)};
    char buffer[65536];
    int count;
    while ((count = getattrlistbulk(fd, &attributes, buffer, sizeof(buffer), FSOPT_PACK_INVAL_ATTRS)) > 0) {
        char *cursor = buffer;
        for (int i = 0; i < count; i++) {
            struct {
                uint32_t length;
                attribute_set_t returned;
                uint32_t error;
                attrreference_t name;
                fsobj_type_t type;
            } record;
            memcpy(&record, cursor, sizeof(record));
            const char *name = cursor + offsetof(typeof(record), name) + record.name.attr_dataoffset;
            NSString *text = record.name.attr_length ? @(name) : @"";
            [entries addObject:@{@"name": text, @"error": @(record.error), @"type": @(record.type),
                @"returned_common": @(record.returned.commonattr), @"record_bytes": @(record.length)}];
            cursor += record.length;
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

static NSDictionary *snapshot(LSApplicationWorkspace *workspace) {
    NSMutableDictionary *out = [@{@"uid": @(getuid()), @"time": @((long long)time(NULL)),
        @"paths": @[pathInfo(@"/Applications"), pathInfo(@"/private/var/staged_system_apps"),
                     pathInfo(@"/System/Cryptexes/App"), pathInfo(@"/System/Cryptexes/App/Applications/MobileSafari.app"),
                     pathInfo(@"/System/Cryptexes/OS")],
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

static NSDictionary *registerMissing(LSApplicationWorkspace *workspace, NSArray *bundleIDs) {
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
                        else if ([action isEqual:@"RebuildSystemApplications"])
                            result[@"rebuild_return"] = @([workspace _LSPrivateRebuildApplicationDatabasesForSystemApps:YES internal:NO user:NO]);
                        else if ([action isEqual:@"RegisterMissingStaged"] && [request[@"BundleIDs"] isKindOfClass:NSArray.class])
                            result[@"registration"] = registerMissing(workspace, request[@"BundleIDs"]);
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
