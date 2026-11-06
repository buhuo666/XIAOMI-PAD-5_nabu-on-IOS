/* Read-only diagnostics for the original 20F66 wallpaper resources and state.
 * Called only by the paired host's explicit WallpaperInventory request.
 */
#import <Foundation/Foundation.h>
#import <ImageIO/ImageIO.h>
#import <CoreGraphics/CoreGraphics.h>
#import <objc/message.h>
#include <errno.h>
#include <sys/stat.h>

static NSString *const wallpaperDirectory =
    @"/Library/Wallpaper/Stills/iPad/7410.WWDC_2022-810w-1080h@2x~ipad.wallpaper";

static NSDictionary *wallpaperError(NSError *error) {
    return error ? @{ @"domain": error.domain, @"code": @(error.code) } : @{};
}

static NSMutableDictionary *wallpaperPath(NSString *path) {
    NSMutableDictionary *result = [@{ @"path": path } mutableCopy];
    struct stat attributes;
    if (stat(path.fileSystemRepresentation, &attributes) == 0) {
        result[@"exists"] = @YES;
        result[@"bytes"] = @(attributes.st_size);
        result[@"is_directory"] = @(S_ISDIR(attributes.st_mode));
    } else {
        result[@"exists"] = @NO;
        result[@"stat_errno"] = @(errno);
    }
    return result;
}

static NSDictionary *wallpaperDirectoryNames(NSString *path) {
    NSMutableDictionary *result = wallpaperPath(path);
    NSError *error = nil;
    NSArray<NSString *> *names = [NSFileManager.defaultManager contentsOfDirectoryAtPath:path error:&error];
    if (names) result[@"names"] = [names sortedArrayUsingSelector:@selector(compare:)];
    else result[@"enumeration_error"] = wallpaperError(error);
    return result;
}

static NSDictionary *wallpaperDefault(void) {
    NSString *path = @"/Library/Wallpaper/DefaultWallpapers~ipad.plist";
    NSMutableDictionary *result = wallpaperPath(path);
    NSError *error = nil;
    NSData *data = [NSData dataWithContentsOfFile:path options:0 error:&error];
    if (!data) {
        result[@"read_error"] = wallpaperError(error);
        return result;
    }
    result[@"read_bytes"] = @(data.length);
    id plist = [NSPropertyListSerialization propertyListWithData:data
        options:NSPropertyListImmutable format:NULL error:&error];
    if (![plist isKindOfClass:NSDictionary.class]) {
        result[@"plist_error"] = error ? wallpaperError(error) : @{ @"reason": @"default plist is not a dictionary" };
        return result;
    }
    id settings = plist[@"default"];
    if ([settings isKindOfClass:NSDictionary.class]) {
        NSMutableDictionary *selected = [NSMutableDictionary dictionary];
        for (NSString *key in @[@"wallpaperIdentifier", @"collectionIdentifier"])
            if (settings[key]) selected[key] = settings[key];
        result[@"default"] = selected;
    } else result[@"error"] = @"default mapping unavailable";
    return result;
}

static NSDictionary *wallpaperImage(NSString *name) {
    NSString *path = [wallpaperDirectory stringByAppendingPathComponent:name];
    NSLog(@"NABU WALLPAPER: reading %@", name);
    NSMutableDictionary *result = wallpaperPath(path);
    NSError *error = nil;
    NSData *data = [NSData dataWithContentsOfFile:path options:0 error:&error];
    if (!data) {
        result[@"read_error"] = wallpaperError(error);
        return result;
    }
    result[@"read_bytes"] = @(data.length);
    CGImageSourceRef source = CGImageSourceCreateWithData((__bridge CFDataRef)data, NULL);
    result[@"source_created"] = @(source != NULL);
    if (!source) {
        result[@"error"] = @"CGImageSourceCreateWithData returned NULL";
        return result;
    }
    result[@"source_status_before"] = @(CGImageSourceGetStatus(source));
    result[@"image_count"] = @(CGImageSourceGetCount(source));
    CFStringRef type = CGImageSourceGetType(source);
    if (type) result[@"image_type"] = (__bridge NSString *)type;
    NSDictionary *options = @{ (__bridge NSString *)kCGImageSourceShouldCache: @YES,
        (__bridge NSString *)kCGImageSourceShouldCacheImmediately: @YES };
    NSLog(@"NABU WALLPAPER: decoding %@", name);
    CGImageRef image = CGImageSourceCreateImageAtIndex(source, 0, (__bridge CFDictionaryRef)options);
    result[@"image_created"] = @(image != NULL);
    result[@"source_status_after"] = @(CGImageSourceGetStatus(source));
    result[@"index_status_after"] = @(CGImageSourceGetStatusAtIndex(source, 0));
    if (image) {
        result[@"width"] = @(CGImageGetWidth(image));
        result[@"height"] = @(CGImageGetHeight(image));
        result[@"bits_per_pixel"] = @(CGImageGetBitsPerPixel(image));
        result[@"bytes_per_row"] = @(CGImageGetBytesPerRow(image));
        // Request decoded backing bytes as well as the CGImage, so a lazily
        // created image alone is not mistaken for successful pixel decoding.
        CFDataRef pixels = CGDataProviderCopyData(CGImageGetDataProvider(image));
        result[@"pixel_data_copied"] = @(pixels != NULL);
        if (pixels) {
            result[@"pixel_data_bytes"] = @(CFDataGetLength(pixels));
            CFRelease(pixels);
        }
        CGImageRelease(image);
    }
    NSLog(@"NABU WALLPAPER: %@ image=%@ pixels=%@ source_status=%@", name,
        result[@"image_created"], result[@"pixel_data_copied"], result[@"source_status_after"]);
    CFRelease(source);
    return result;
}

static id wallpaperGetter(id target, NSString *name, NSMutableDictionary *errors) {
    SEL selector = NSSelectorFromString(name);
    if (![target respondsToSelector:selector]) {
        errors[name] = @"selector unavailable";
        return nil;
    }
    @try {
        return ((id (*)(id, SEL))objc_msgSend)(target, selector);
    } @catch (NSException *error) {
        errors[name] = @{ @"exception": error.name, @"reason": error.reason ?: @"" };
        return nil;
    }
}

static NSDictionary *wallpaperApplication(NSString *identifier) {
    NSMutableDictionary *result = [@{ @"identifier": identifier } mutableCopy];
    Class applicationClass = NSClassFromString(@"LSApplicationProxy");
    SEL factory = NSSelectorFromString(@"applicationProxyForIdentifier:");
    if (![applicationClass respondsToSelector:factory]) {
        result[@"error"] = @"+[LSApplicationProxy applicationProxyForIdentifier:] unavailable";
        return result;
    }
    id application = ((id (*)(id, SEL, id))objc_msgSend)(applicationClass, factory, identifier);
    if (!application) {
        result[@"error"] = @"application proxy unavailable";
        return result;
    }
    NSMutableDictionary *errors = [NSMutableDictionary dictionary];
    id plugins = wallpaperGetter(application, @"plugInKitPlugins", errors);
    if ([plugins isKindOfClass:NSArray.class]) {
        NSMutableArray *entries = [NSMutableArray array];
        for (id plugin in plugins) {
            NSMutableDictionary *entry = [NSMutableDictionary dictionary];
            NSMutableDictionary *getterErrors = [NSMutableDictionary dictionary];
            id pluginID = wallpaperGetter(plugin, @"pluginIdentifier", getterErrors);
            id bundleURL = wallpaperGetter(plugin, @"bundleURL", getterErrors);
            if ([pluginID isKindOfClass:NSString.class]) entry[@"identifier"] = pluginID;
            if ([bundleURL isKindOfClass:NSURL.class]) entry[@"path"] = [bundleURL path];
            if (getterErrors.count) entry[@"getter_errors"] = getterErrors;
            [entries addObject:entry];
        }
        result[@"plugins"] = entries;
    } else if (plugins) errors[@"plugInKitPlugins"] = @"getter did not return an array";
    else result[@"plugins_result_is_nil"] = @YES;

    id container = wallpaperGetter(application, @"containerURL", errors);
    if ([container isKindOfClass:NSURL.class]) {
        NSString *library = [[container path] stringByAppendingPathComponent:@"Library"];
        // Inspect only these configuration-directory names, never selected
        // photos, wallpaper contents, or the values of whole preferences.
        result[@"configuration_directories"] = @[
            wallpaperDirectoryNames(library),
            wallpaperDirectoryNames([library stringByAppendingPathComponent:@"Preferences"]),
            wallpaperDirectoryNames([library stringByAppendingPathComponent:@"Application Support"])];
    } else if (container) errors[@"containerURL"] = @"getter did not return a URL";
    else result[@"container_result_is_nil"] = @YES;
    if (errors.count) result[@"getter_errors"] = errors;
    return result;
}

NSDictionary *nabuWallpaperSnapshot(void) {
    NSMutableArray *images = [NSMutableArray array];
    for (NSString *name in @[
        @"7410.WWDC_2022.thumbnail-810w-1080h@2x~ipad.heic",
        @"7411.WWDC_2022_Light.thumbnail-810w-1080h@2x~ipad.heic",
        @"7411.WWDC_2022_Light-810w-1080h@2x~ipad.heic",
        @"7412.WWDC_2022_Dark.thumbnail-810w-1080h@2x~ipad.heic",
        @"7412.WWDC_2022_Dark-810w-1080h@2x~ipad.heic"]) {
        @autoreleasepool { [images addObject:wallpaperImage(name)]; }
    }
    NSMutableArray *legacyPaths = [NSMutableArray array];
    for (NSString *name in @[@"HomeBackground.cpbitmap", @"LockBackground.cpbitmap",
        @"HomeBackgroundThumbnail.jpg", @"LockBackgroundThumbnail.jpg"])
        [legacyPaths addObject:wallpaperPath([@"/private/var/mobile/Library/SpringBoard"
            stringByAppendingPathComponent:name])];
    return @{ @"read_only": @YES,
        @"default_plist": wallpaperDefault(),
        @"default_resource_directory": wallpaperDirectoryNames(wallpaperDirectory),
        @"images": images,
        @"applications": @[wallpaperApplication(@"com.apple.PaperBoard"),
                            wallpaperApplication(@"com.apple.PosterBoard")],
        @"legacy_wallpaper_files": legacyPaths,
        @"state_directories": @[
            wallpaperDirectoryNames(@"/private/var/mobile/Library/Wallpaper"),
            wallpaperDirectoryNames(@"/private/var/mobile/Library/PaperBoard"),
            wallpaperDirectoryNames(@"/private/var/mobile/Library/PosterBoard")],
        @"selected_wallpaper": @{ @"status": @"unknown",
            @"reason": @"Selected-wallpaper state keys/API have not been verified for 20F66; only configuration-directory names and file existence are collected" } };
}
