/* Observe the existing ScreenTime/RemoteManagement database's vnode events.
 * This opens event-only descriptors; it never reads or changes database data.
 */
#import <Foundation/Foundation.h>
#include <dispatch/dispatch.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <sys/event.h>
#include <sys/stat.h>
#include <unistd.h>

static dispatch_source_t sqliteWatchSources[3];

static void sqliteWatchReport(const char *path, int fd, unsigned long flags,
                              NSString *event) {
    @autoreleasepool {
        NSMutableDictionary *report = [@{@"event": event, @"path": @(path),
            @"fd": @(fd), @"flags": @(flags), @"pid": @(getpid())} mutableCopy];
        NSMutableArray *names = [NSMutableArray array];
        if (flags & NOTE_DELETE) [names addObject:@"DELETE"];
        if (flags & NOTE_WRITE) [names addObject:@"WRITE"];
        if (flags & NOTE_EXTEND) [names addObject:@"EXTEND"];
        if (flags & NOTE_ATTRIB) [names addObject:@"ATTRIB"];
        if (flags & NOTE_LINK) [names addObject:@"LINK"];
        if (flags & NOTE_RENAME) [names addObject:@"RENAME"];
        if (flags & NOTE_REVOKE) [names addObject:@"REVOKE"];
        report[@"events"] = names;

        struct stat descriptorInfo = {0}, pathInfo = {0};
        int descriptorResult = fstat(fd, &descriptorInfo);
        int descriptorError = descriptorResult == 0 ? 0 : errno;
        int pathResult = stat(path, &pathInfo);
        int pathError = pathResult == 0 ? 0 : errno;
        report[@"fstat_errno"] = @(descriptorError);
        report[@"stat_errno"] = @(pathError);
        if (descriptorResult == 0) {
            report[@"fd_device"] = @(descriptorInfo.st_dev);
            report[@"fd_inode"] = @(descriptorInfo.st_ino);
            report[@"fd_nlink"] = @(descriptorInfo.st_nlink);
            report[@"fd_size"] = @(descriptorInfo.st_size);
        }
        if (pathResult == 0) {
            report[@"path_device"] = @(pathInfo.st_dev);
            report[@"path_inode"] = @(pathInfo.st_ino);
            report[@"path_nlink"] = @(pathInfo.st_nlink);
            report[@"path_size"] = @(pathInfo.st_size);
        }
        if (descriptorResult == 0 && pathResult == 0)
            report[@"path_matches_open_inode"] = @(descriptorInfo.st_dev == pathInfo.st_dev &&
                                                    descriptorInfo.st_ino == pathInfo.st_ino);
        char resolved[PATH_MAX] = {0};
        int pathLookup = fcntl(fd, F_GETPATH, resolved);
        report[@"getpath_errno"] = @(pathLookup == 0 ? 0 : errno);
        if (pathLookup == 0) report[@"fd_path"] = @(resolved);
        NSData *data = [NSJSONSerialization dataWithJSONObject:report options:0 error:NULL];
        NSLog(@"NABU SQLITE VNODE: %@", [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding]);
    }
}

void nabuStartSQLiteVnodeWatch(void) {
    static const char *const paths[] = {
        "/private/var/mobile/Library/Application Support/com.apple.remotemanagementd/RMAdminStore-Local.sqlite",
        "/private/var/mobile/Library/Application Support/com.apple.remotemanagementd/RMAdminStore-Local.sqlite-wal",
        "/private/var/mobile/Library/Application Support/com.apple.remotemanagementd/RMAdminStore-Local.sqlite-shm"
    };
    // SQLite itself watches 0x71; WRITE/EXTEND/ATTRIB provide the comparison.
    unsigned long mask = NOTE_DELETE | NOTE_LINK | NOTE_RENAME | NOTE_REVOKE |
                         NOTE_WRITE | NOTE_EXTEND | NOTE_ATTRIB;
    for (NSUInteger index = 0; index < sizeof(paths) / sizeof(paths[0]); index++) {
        const char *path = paths[index];
        int fd = open(path, O_EVTONLY | O_CLOEXEC);
        if (fd < 0) {
            NSLog(@"NABU SQLITE VNODE: watch unavailable path=%s errno=%d", path, errno);
            continue;
        }
        dispatch_source_t source = dispatch_source_create(DISPATCH_SOURCE_TYPE_VNODE,
            (uintptr_t)fd, mask, dispatch_get_global_queue(QOS_CLASS_UTILITY, 0));
        if (!source) {
            NSLog(@"NABU SQLITE VNODE: source unavailable path=%s", path);
            close(fd);
            continue;
        }
        sqliteWatchSources[index] = source;
        dispatch_source_set_event_handler(source, ^{
            sqliteWatchReport(path, fd, dispatch_source_get_data(sqliteWatchSources[index]), @"vnode-event");
        });
        dispatch_source_set_cancel_handler(source, ^{ close(fd); });
        dispatch_resume(source);
        sqliteWatchReport(path, fd, 0, @"watch-started");
    }
}
