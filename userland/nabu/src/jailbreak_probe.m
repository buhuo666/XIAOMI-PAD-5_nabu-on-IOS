#import <UIKit/UIKit.h>
#import <Foundation/Foundation.h>
#import <mach/mach.h>
#import <libkern/OSCacheControl.h>
#include <dlfcn.h>
#include <errno.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

// Darwin 8796 interfaces exist on the device but are omitted from the public iOS SDK.
extern kern_return_t mach_vm_read_overwrite(vm_map_t, mach_vm_address_t, mach_vm_size_t, mach_vm_address_t, mach_vm_size_t *);
extern kern_return_t mach_vm_write(vm_map_t, mach_vm_address_t, vm_offset_t, mach_msg_type_number_t);
extern int ptrace(int, pid_t, caddr_t, int);
#define PT_ATTACH 10
#define PT_DETACH 11

extern int posix_spawnattr_set_persona_np(const posix_spawnattr_t *, uid_t, uint32_t);
extern int posix_spawnattr_set_persona_uid_np(const posix_spawnattr_t *, uid_t);
extern int posix_spawnattr_set_persona_gid_np(const posix_spawnattr_t *, uid_t);
extern char **environ;
static NSString *const directory = @"/var/mobile/Media/NabuJailbreak";
static volatile uint64_t memoryWord = 0x1020304050607080ULL;

static void save(NSDictionary *value, NSString *name) {
    [[NSFileManager defaultManager] createDirectoryAtPath:directory withIntermediateDirectories:YES attributes:nil error:nil];
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted error:nil];
    [data writeToFile:[directory stringByAppendingPathComponent:name] options:NSDataWritingAtomic error:nil];
}

static int spawnMode(const char *mode, uid_t uid, int output, char **environment, pid_t *pid) {
    const char *path = NSBundle.mainBundle.executablePath.fileSystemRepresentation;
    char *args[] = {(char *)path, (char *)mode, NULL};
    posix_spawnattr_t attr;
    posix_spawnattr_init(&attr);
    posix_spawnattr_set_persona_np(&attr, 99, 1);
    posix_spawnattr_set_persona_uid_np(&attr, uid);
    posix_spawnattr_set_persona_gid_np(&attr, uid);
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    if (output >= 0) posix_spawn_file_actions_adddup2(&actions, output, STDOUT_FILENO);
    int result = posix_spawn(pid, path, &actions, &attr, args, environment);
    posix_spawn_file_actions_destroy(&actions);
    posix_spawnattr_destroy(&attr);
    return result;
}

static NSDictionary *waitResult(pid_t pid, int spawnError) {
    if (spawnError) return @{@"spawn_errno": @(spawnError)};
    int status = 0;
    pid_t waited;
    do { waited = waitpid(pid, &status, 0); } while (waited < 0 && errno == EINTR);
    if (waited < 0) return @{@"wait_errno": @(errno)};
    return @{@"raw_status": @(status), @"exited": @(WIFEXITED(status)),
             @"exit_code": @(WIFEXITED(status) ? WEXITSTATUS(status) : -1),
             @"signal": @(WIFSIGNALED(status) ? WTERMSIG(status) : 0)};
}

static NSDictionary *debugChild(void) {
    NSMutableDictionary *result = [NSMutableDictionary new];
    int fds[2];
    if (pipe(fds)) return @{@"pipe_errno": @(errno)};
    pid_t pid = 0;
    int error = spawnMode("--memory-child", 501, fds[1], environ, &pid);
    close(fds[1]);
    result[@"spawn_errno"] = @(error);
    if (error) { close(fds[0]); return result; }
    uint64_t message[3] = {0};
    struct pollfd descriptor = {.fd=fds[0], .events=POLLIN};
    int ready = poll(&descriptor, 1, 5000);
    ssize_t count = ready > 0 ? read(fds[0], message, sizeof(message)) : -1;
    close(fds[0]);
    result[@"child_uid"] = @(message[1]);
    result[@"child_euid"] = @(message[2]);
    result[@"ready_bytes"] = @(count);
    mach_port_t task = MACH_PORT_NULL;
    if (count == sizeof(message)) {
        kern_return_t kr = task_for_pid(mach_task_self(), pid, &task);
        result[@"task_for_pid"] = @(kr);
        if (kr == KERN_SUCCESS) {
            uint64_t value = 0;
            mach_vm_size_t actual = 0;
            kr = mach_vm_read_overwrite(task, message[0], sizeof(value), (mach_vm_address_t)&value, &actual);
            result[@"read_memory"] = @(kr);
            result[@"initial_value_matches"] = @(kr == 0 && actual == sizeof(value) && value == memoryWord);
            uint64_t replacement = 0xa1b2c3d4e5f60718ULL;
            kr = mach_vm_write(task, message[0], (vm_offset_t)&replacement, sizeof(replacement));
            result[@"write_memory"] = @(kr);
            kr = mach_vm_read_overwrite(task, message[0], sizeof(value), (mach_vm_address_t)&value, &actual);
            result[@"written_value_matches"] = @(kr == 0 && actual == sizeof(value) && value == replacement);
            thread_act_array_t threads = NULL;
            mach_msg_type_number_t threadCount = 0;
            kr = task_threads(task, &threads, &threadCount);
            result[@"task_threads"] = @(kr);
            result[@"thread_count"] = @(threadCount);
            if (kr == 0) {
                for (mach_msg_type_number_t i = 0; i < threadCount; i++) mach_port_deallocate(mach_task_self(), threads[i]);
                vm_deallocate(mach_task_self(), (vm_address_t)threads, threadCount * sizeof(thread_t));
            }
            mach_port_deallocate(mach_task_self(), task);
        }
        int attached = ptrace(PT_ATTACH, pid, 0, 0);
        result[@"ptrace_attach_errno"] = @(attached == 0 ? 0 : errno);
        if (attached == 0) {
            int status = 0;
            pid_t waited = 0;
            for (int i=0; i<300 && waited == 0; i++) {
                waited = waitpid(pid, &status, WNOHANG | WUNTRACED);
                if (waited == 0) usleep(10000);
            }
            result[@"ptrace_stop_observed"] = @(waited == pid && WIFSTOPPED(status));
            int detached = ptrace(PT_DETACH, pid, (caddr_t)1, 0);
            result[@"ptrace_detach_errno"] = @(detached == 0 ? 0 : errno);
        }
    }
    kill(pid, SIGKILL);
    result[@"cleanup"] = waitResult(pid, 0);
    return result;
}

static int jitChild(void) {
    size_t length = (size_t)getpagesize();
    void *memory = mmap(NULL, length, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (memory == MAP_FAILED) { save(@{@"mmap_errno": @(errno)}, @"jit.json"); return 2; }
    const uint32_t code[] = {0x52800540, 0xd65f03c0}; // mov w0,#42; ret
    memcpy(memory, code, sizeof(code));
    int protection = mprotect(memory, length, PROT_READ | PROT_EXEC);
    if (protection) { save(@{@"mprotect_errno": @(errno)}, @"jit.json"); munmap(memory,length); return 3; }
    sys_icache_invalidate(memory, sizeof(code));
    int actual = ((int (*)(void))memory)();
    save(@{@"mmap_errno": @0, @"mprotect_errno": @0, @"actual": @(actual)}, @"jit.json");
    munmap(memory,length);
    return actual == 42 ? 0 : 4;
}

static int rootTests(void) {
    NSMutableDictionary *result = [@{@"uid": @(getuid()), @"euid": @(geteuid()),
                                     @"timestamp": @([[NSDate date] timeIntervalSince1970])} mutableCopy];
    if (getuid() != 0 || geteuid() != 0) { save(result,@"results.json"); return 1; }
    result[@"debugging"] = debugChild();
    pid_t child = 0;
    int error = spawnMode("--jit-child", 0, -1, environ, &child);
    result[@"jit_process"] = waitResult(child,error);
    NSString *library = [NSBundle.mainBundle.bundlePath stringByAppendingPathComponent:@"NabuProbeInjection.dylib"];
    NSString *variable = [@"DYLD_INSERT_LIBRARIES=" stringByAppendingString:library];
    char *environment[] = {(char *)variable.UTF8String, "PATH=/usr/bin:/bin", NULL};
    error = spawnMode("--injection-child", 0, -1, environment, &child);
    result[@"injection_process"] = waitResult(child,error);
    NSMutableArray *inventory = [NSMutableArray new];
    for (NSString *path in @[@"/var/jb", @"/var/jb/usr/bin/dpkg", @"/var/jb/usr/bin/apt-get", @"/var/jb/bin/sh", @"/bin/sh", @"/usr/bin/launchctl", @"/var/jb/usr/lib/TweakLoader.dylib", @"/var/jb/Applications/Sileo.app"]) {
        struct stat attributes;
        int status = stat(path.fileSystemRepresentation,&attributes);
        NSMutableDictionary *item = [@{@"path":path,@"stat_errno":@(status == 0 ? 0 : errno)} mutableCopy];
        if (!status) { item[@"uid"]=@(attributes.st_uid); item[@"mode"]=@(attributes.st_mode & 07777); }
        [inventory addObject:item];
    }
    result[@"inventory"]=inventory;
    save(result,@"results.json");
    return 0;
}

@interface NabuProbeDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic,strong) UIWindow *window;
@end
@implementation NabuProbeDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options;
    self.window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *controller=[UIViewController new];
    controller.view.backgroundColor=UIColor.systemBackgroundColor;
    UILabel *label=[[UILabel alloc] initWithFrame:CGRectMake(30,160,UIScreen.mainScreen.bounds.size.width-60,200)];
    label.numberOfLines=0; label.textAlignment=NSTextAlignmentCenter;
    label.text=@"正在验证 root、调试与动态代码执行…";
    [controller.view addSubview:label]; self.window.rootViewController=controller; [self.window makeKeyAndVisible];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0), ^{
        pid_t pid=0; int error=spawnMode("--root-tests",0,-1,environ,&pid);
        NSDictionary *status=waitResult(pid,error);
        save(status,@"root-launch.json");
        dispatch_async(dispatch_get_main_queue(), ^{ label.text=@"验证已结束，结果已保存。\n请保持 USB 连接。"; });
    });
    return YES;
}
@end

int main(int argc,char **argv) {
    @autoreleasepool {
        if (argc == 2) {
            if (!strcmp(argv[1],"--memory-child")) {
                alarm(15);
                uint64_t message[]={(uint64_t)&memoryWord,getuid(),geteuid()};
                write(STDOUT_FILENO,message,sizeof(message));
                for (;;) pause();
            }
            if (!strcmp(argv[1],"--jit-child")) { alarm(10); return jitChild(); }
            if (!strcmp(argv[1],"--injection-child")) {
                uint32_t (*injected)(void)=dlsym(RTLD_DEFAULT,"nabu_probe_injected_value");
                uint32_t value=injected ? injected() : 0;
                save(@{@"symbol_present":@(injected != NULL),@"actual":@(value)},@"injection.json");
                return value == 0x4e414255 ? 0 : 5;
            }
            if (!strcmp(argv[1],"--root-tests")) return rootTests();
        }
        return UIApplicationMain(argc,argv,nil,NSStringFromClass(NabuProbeDelegate.class));
    }
}
