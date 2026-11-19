#import <UIKit/UIKit.h>
#include <dlfcn.h>
#include <errno.h>
#include <signal.h>
#include <spawn.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <unistd.h>

extern char **environ;
extern int posix_spawnattr_set_persona_np(const posix_spawnattr_t *, uid_t, uint32_t);
extern int posix_spawnattr_set_persona_uid_np(const posix_spawnattr_t *, uid_t);
extern int posix_spawnattr_set_persona_gid_np(const posix_spawnattr_t *, uid_t);
static NSString *const directory = @"/var/mobile/Media/NabuGpuOpt";
static NSString *const library = @"/var/mobile/Media/NabuGpuOpt/libnabu.ca-frame-trace.dylib";
static NSString *originalConfiguration;
static NSString *enabledConfiguration;
static NSMutableArray<NSString *> *ownedAliases;

static void save(NSDictionary *value, NSString *name) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted error:nil];
    [data writeToFile:[directory stringByAppendingPathComponent:name] options:NSDataWritingAtomic error:nil];
}
static NSString *configuration(void) {
    char bytes[4096] = {0}; size_t size = sizeof(bytes);
    if (sysctlbyname("kern.exec_inject", bytes, &size, NULL, 0)) return nil;
    return @(bytes);
}
static NSDictionary *setConfiguration(NSString *next) {
    size_t size = strlen(next.UTF8String) + 1;
    if (size >= 512) return @{@"success":@NO, @"error":@"exec_inject capacity exceeded", @"bytes_with_nul":@(size)};
    int result = sysctlbyname("kern.exec_inject", NULL, NULL, (void *)next.UTF8String, size);
    int error = result ? errno : 0;
    NSString *readback = configuration();
    return @{@"success":@(!result && [readback isEqualToString:next]), @"write_errno":@(error),
             @"bytes_with_nul":@(size), @"readback":readback ?: @""};
}
static NSDictionary *restartBackboard(void) {
    int mib[] = {CTL_KERN, KERN_PROC, KERN_PROC_ALL, 0}; size_t bytes = 0;
    if (sysctl(mib, 4, NULL, &bytes, NULL, 0)) return @{@"success":@NO, @"errno":@(errno)};
    struct kinfo_proc *processes = malloc(bytes);
    int result = sysctl(mib, 4, processes, &bytes, NULL, 0);
    NSMutableArray *stopped = [NSMutableArray array];
    if (!result) for (size_t i = 0; i < bytes / sizeof(*processes); ++i)
        if (!strcmp(processes[i].kp_proc.p_comm, "backboardd")) {
            pid_t pid = processes[i].kp_proc.p_pid;
            int sent = kill(pid, SIGTERM);
            [stopped addObject:@{@"pid":@(pid), @"result":@(sent), @"errno":@(sent ? errno : 0)}];
        }
    free(processes);
    return @{@"success":@(!result && stopped.count == 1), @"processes":stopped};
}
static BOOL alias(NSString *path, NSString *target) {
    int result = symlink(target.fileSystemRepresentation, path.fileSystemRepresentation);
    char actual[4096] = {0};
    ssize_t count = readlink(path.fileSystemRepresentation, actual, sizeof(actual) - 1);
    if (count < 0 || strcmp(actual, target.fileSystemRepresentation)) return NO;
    if (!result) [ownedAliases addObject:path];
    return YES;
}
static NSDictionary *enable(void) {
    NSString *before = configuration();
    if (!before) return @{@"success":@NO, @"errno":@(errno)};
    if (enabledConfiguration) return @{@"success":@YES, @"already_enabled":@YES};
    if (![[NSFileManager defaultManager] fileExistsAtPath:library]) return @{@"success":@NO, @"error":@"Observer library has not been uploaded"};
    originalConfiguration = before;
    NSMutableArray<NSString *> *rules = [[before componentsSeparatedByString:@";"] mutableCopy];
    if (!alias(@"/tmp/ngc", library)) return @{@"success":@NO, @"error":@"Observer alias failed"};
    [rules addObject:@"/tmp/ngc backboardd"];
    unsigned serial = 0;
    while (strlen([[rules componentsJoinedByString:@";"] UTF8String]) + 1 >= 512) {
        NSUInteger selected = NSNotFound; NSInteger savings = 0;
        NSString *shortPath = [NSString stringWithFormat:@"/tmp/ng%u", serial++];
        for (NSUInteger i = 0; i < rules.count - 1; ++i) {
            NSRange separator = [rules[i] rangeOfString:@" "];
            if (separator.location == NSNotFound) continue;
            NSString *path = [rules[i] substringToIndex:separator.location];
            NSInteger saved = (NSInteger)path.length - (NSInteger)shortPath.length;
            if (saved > savings) { selected = i; savings = saved; }
        }
        if (selected == NSNotFound) return @{@"success":@NO, @"error":@"No room for observer rule", @"before":before};
        NSString *rule = rules[selected]; NSRange separator = [rule rangeOfString:@" "];
        NSString *path = [rule substringToIndex:separator.location];
        if (!alias(shortPath, path)) return @{@"success":@NO, @"error":@"Retained library alias failed"};
        rules[selected] = [shortPath stringByAppendingString:[rule substringFromIndex:separator.location]];
    }
    NSString *next = [rules componentsJoinedByString:@";"];
    NSDictionary *written = setConfiguration(next);
    save(@{@"before":before, @"after":next, @"write":written, @"aliases":ownedAliases}, @"configuration.json");
    if (![written[@"success"] boolValue]) return written;
    enabledConfiguration = next;
    return @{@"success":@YES, @"configuration":written, @"restart":restartBackboard()};
}
static NSDictionary *disable(void) {
    if (!enabledConfiguration) return @{@"success":@YES, @"already_disabled":@YES};
    NSString *current = configuration();
    if (![current isEqualToString:enabledConfiguration]) return @{@"success":@NO, @"error":@"Configuration changed outside this observation", @"current":current ?: @""};
    NSDictionary *restored = setConfiguration(originalConfiguration);
    if (![restored[@"success"] boolValue]) return restored;
    enabledConfiguration = nil;
    return @{@"success":@YES, @"configuration":restored, @"restart":restartBackboard()};
}
static int rootMain(void) {
    NSFileManager *fm = NSFileManager.defaultManager;
    [fm createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil];
    chown(directory.fileSystemRepresentation, 501, 501);
    ownedAliases = [NSMutableArray array];
    NSString *requestPath = [directory stringByAppendingPathComponent:@"request.plist"];
    [fm removeItemAtPath:requestPath error:nil];
    save(@{@"pid":@(getpid()), @"uid":@(geteuid()), @"ready":@(geteuid() == 0),
           @"exec_inject":configuration() ?: @"", @"observer_installed":@NO}, @"ready.json");
    if (geteuid() != 0) return 1;
    BOOL running = YES;
    while (running) { @autoreleasepool {
        NSDictionary *request = [NSDictionary dictionaryWithContentsOfFile:requestPath];
        if (request) {
            [fm removeItemAtPath:requestPath error:nil]; NSString *action = request[@"Action"];
            NSDictionary *result = nil;
            if ([action isEqualToString:@"Snapshot"]) result = @{@"success":@YES, @"pid":@(getpid()), @"exec_inject":configuration() ?: @"", @"enabled":@(enabledConfiguration != nil)};
            else if ([action isEqualToString:@"Enable"]) result = enable();
            else if ([action isEqualToString:@"Disable"]) result = disable();
            else if ([action isEqualToString:@"Stop"]) { result = disable(); running = ![result[@"success"] boolValue]; }
            else result = @{@"success":@NO, @"error":@"Unknown action"};
            save(@{@"request":request, @"result":result, @"uid":@(geteuid())}, @"response.json");
        }
        usleep(200000);
    }}
    return 0;
}
@interface GpuTraceController : UIViewController
@property(nonatomic, strong) UILabel *status;
@end
@implementation GpuTraceController
- (void)start {
    posix_spawnattr_t attributes; posix_spawnattr_init(&attributes);
    posix_spawnattr_set_persona_np(&attributes, 99, 1);
    posix_spawnattr_set_persona_uid_np(&attributes, 0); posix_spawnattr_set_persona_gid_np(&attributes, 0);
    posix_spawnattr_setpgroup(&attributes, 0);
    posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP);
    NSString *path = NSBundle.mainBundle.executablePath;
    char *argv[] = {(char *)path.UTF8String, "--trace-root", NULL}; pid_t pid = 0;
    int result = posix_spawn(&pid, path.fileSystemRepresentation, NULL, &attributes, argv, environ);
    posix_spawnattr_destroy(&attributes);
    self.status.text = result ? @"采集准备未完成" : @"采集控制已启动，请保持电脑USB连接。";
}
- (void)viewDidLoad {
    [super viewDidLoad]; self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.status = [[UILabel alloc] initWithFrame:CGRectMake(40, 80, self.view.bounds.size.width - 80, 160)];
    self.status.font = [UIFont systemFontOfSize:24]; self.status.numberOfLines = 0;
    self.status.text = @"GPU系统合成采集\n准备完成后可回到帧率基准或桌面。"; [self.view addSubview:self.status];
    UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem]; button.frame = CGRectMake(40, 260, 300, 60);
    [button setTitle:@"启动采集控制" forState:UIControlStateNormal];
    [button addTarget:self action:@selector(start) forControlEvents:UIControlEventTouchUpInside]; [self.view addSubview:button];
}
@end
@interface GpuTraceApp : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation GpuTraceApp
- (BOOL)application:(UIApplication *)app didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)app; (void)options; self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [GpuTraceController new]; [self.window makeKeyAndVisible]; return YES;
}
@end
int main(int argc, char **argv) {
    @autoreleasepool { if (argc > 1 && !strcmp(argv[1], "--trace-root")) return rootMain();
        return UIApplicationMain(argc, argv, nil, NSStringFromClass(GpuTraceApp.class)); }
}
