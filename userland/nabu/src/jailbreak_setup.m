#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>
#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/wait.h>
#include <unistd.h>
#include "jailbreak_paths.h"
#include "jailbreak_fs_probe.h"

// Stable libarchive ABI; the public iOS SDK omits these headers.
struct archive;
struct archive_entry;
extern struct archive *archive_read_new(void);
extern int archive_read_support_filter_gzip(struct archive *);
extern int archive_read_support_format_tar(struct archive *);
extern int archive_read_open_filename(struct archive *, const char *, size_t);
extern int archive_read_next_header(struct archive *, struct archive_entry **);
extern int archive_read_extract(struct archive *, struct archive_entry *, int);
extern const char *archive_entry_pathname(struct archive_entry *);
extern const char *archive_error_string(struct archive *);
extern int archive_read_free(struct archive *);
extern int posix_spawnattr_set_persona_np(const posix_spawnattr_t *, uid_t, uint32_t);
extern int posix_spawnattr_set_persona_uid_np(const posix_spawnattr_t *, uid_t);
extern int posix_spawnattr_set_persona_gid_np(const posix_spawnattr_t *, uid_t);
extern char **environ;

static NSString *const base = @"/private/var/db/nabu-jailbreak";
static NSString *const input = @"/var/mobile/Media/NabuJailbreak/Inputs";
static NSString *const output = @"/var/mobile/Media/NabuJailbreak/Setup";
static NSMutableDictionary *report;
static NSMutableArray *steps;

static BOOL makeDirectory(NSString *path) {
    NSError *error = nil;
    BOOL ok = [[NSFileManager defaultManager] createDirectoryAtPath:path withIntermediateDirectories:YES
        attributes:@{NSFilePosixPermissions:@0755} error:&error];
    if (!ok) {
        report[@"error"] = [NSString stringWithFormat:@"mkdir %@: %@",path,error];
        NSError *underlying=error.userInfo[NSUnderlyingErrorKey];
        if ([underlying.domain isEqualToString:NSPOSIXErrorDomain]) errno=(int)underlying.code;
    }
    return ok;
}

static BOOL publish(void) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
    return [data writeToFile:[output stringByAppendingPathComponent:@"setup.json"] atomically:YES];
}

static BOOL failure(NSString *stage) {
    report[@"failed_stage"] = stage;
    report[@"errno"] = @(errno);
    report[@"errno_text"] = @(strerror(errno));
    publish();
    return NO;
}

static NSDictionary *run(NSString *name, NSArray<NSString *> *arguments, int uid) {
    NSString *log = [output stringByAppendingPathComponent:[name stringByAppendingString:@".log"]];
    char **argv = calloc(arguments.count+1,sizeof(char *));
    for (NSUInteger i=0;i<arguments.count;i++) argv[i]=strdup(arguments[i].UTF8String);
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addopen(&actions,STDOUT_FILENO,log.fileSystemRepresentation,O_WRONLY|O_CREAT|O_TRUNC,0644);
    posix_spawn_file_actions_adddup2(&actions,STDOUT_FILENO,STDERR_FILENO);
    posix_spawnattr_t attr;
    posix_spawnattr_init(&attr);
    if (uid >= 0) {
        posix_spawnattr_set_persona_np(&attr,99,1);
        posix_spawnattr_set_persona_uid_np(&attr,(uid_t)uid);
        posix_spawnattr_set_persona_gid_np(&attr,(uid_t)uid);
    }
    char *environment[] = {"PATH=/var/jb/usr/bin:/var/jb/bin:/var/jb/usr/sbin:/var/jb/sbin:/usr/bin:/bin:/usr/sbin:/sbin",
        "HOME=/var/jb/var/root", "LANG=C", "LC_ALL=C", NULL};
    pid_t pid = 0;
    int error = posix_spawn(&pid,argv[0],&actions,&attr,argv,environment);
    posix_spawn_file_actions_destroy(&actions);
    posix_spawnattr_destroy(&attr);
    for (NSUInteger i=0;i<arguments.count;i++) free(argv[i]);
    free(argv);
    NSMutableDictionary *step = [@{@"name":name,@"argv":arguments,@"spawn_errno":@(error),@"log":log} mutableCopy];
    if (!error) {
        int status = 0;
        pid_t waited;
        do { waited=waitpid(pid,&status,0); } while (waited<0 && errno==EINTR);
        step[@"wait_errno"]=@(waited<0 ? errno : 0);
        step[@"exit_code"]=@(waited==pid && WIFEXITED(status) ? WEXITSTATUS(status) : -1);
        step[@"signal"]=@(waited==pid && WIFSIGNALED(status) ? WTERMSIG(status) : 0);
        step[@"passed"]=@(waited==pid && WIFEXITED(status) && WEXITSTATUS(status)==0);
    } else step[@"passed"]=@NO;
    [steps addObject:step];
    publish();
    return step;
}

static BOOL extractSeed(void) {
    NSString *prefix = [base stringByAppendingPathComponent:@"procursus"];
    NSString *marker = [prefix stringByAppendingPathComponent:@".nabu-seed-v1"];
    if ([[NSFileManager defaultManager] fileExistsAtPath:marker]) {
        report[@"existing_seed_preserved"]=@YES;
        return YES;
    }
    struct stat st;
    if (lstat(prefix.fileSystemRepresentation,&st)==0) { errno=EEXIST; return failure(@"unmarked_prefix_exists"); }
    NSString *staging = [base stringByAppendingPathComponent:@"seed-stage"];
    if (mkdir(staging.fileSystemRepresentation,0755)) return failure(@"new_seed_staging");
    if (chdir(staging.fileSystemRepresentation)) return failure(@"seed_chdir");
    struct archive *a = archive_read_new();
    archive_read_support_filter_gzip(a);
    archive_read_support_format_tar(a);
    int status = archive_read_open_filename(a,[[input stringByAppendingPathComponent:@"prefix.tar.gz"] fileSystemRepresentation],65536);
    size_t files = 0;
    struct archive_entry *entry = NULL;
    while (status==0 && (status=archive_read_next_header(a,&entry))==0) {
        const char *path = archive_entry_pathname(entry);
        // This imported tar was reviewed on the host; keep extraction in its new staging tree.
        if (strncmp(path,"procursus/",10) && strcmp(path,"procursus")) { errno=EINVAL; status=-30; break; }
        // OWNER | PERM | TIME | SECURE_SYMLINKS | SECURE_NODOTDOT | SECURE_NOABSOLUTEPATHS.
        status=archive_read_extract(a,entry,1|2|4|0x100|0x2000|0x10000);
        if (status==0) files++;
    }
    report[@"seed_entries_extracted"]=@(files);
    report[@"archive_status"]=@(status);
    if (status!=1) {
        const char *message=archive_error_string(a);
        if (message) report[@"archive_error"]=@(message);
        archive_read_free(a);
        chdir("/");
        return failure(@"extract_seed");
    }
    archive_read_free(a);
    chdir("/");
    NSString *from=[staging stringByAppendingPathComponent:@"procursus"];
    if (rename(from.fileSystemRepresentation,prefix.fileSystemRepresentation)) return failure(@"publish_seed");
    if (![@"seed-v1\n" writeToFile:marker atomically:YES encoding:NSUTF8StringEncoding error:nil]) return failure(@"seed_marker");
    rmdir(staging.fileSystemRepresentation);
    return YES;
}

static BOOL mountPrefix(void) {
    const char *stage=NULL;
    if (nabu_jailbreak_restore_paths(&stage)) return failure(@(stage));
    struct statfs mapped;
    if (statfs("/var/jb",&mapped)) return failure(@"prefix_statfs");
    report[@"prefix_mount_flags"]=@(mapped.f_flags);
    report[@"prefix_mount_readonly"]=@((mapped.f_flags & MNT_RDONLY)!=0);
    report[@"prefix_mount_nosuid"]=@((mapped.f_flags & MNT_NOSUID)!=0);
    report[@"prefix_filesystem"]=@(mapped.f_fstypename);
    report[@"prefix_storage"]=@"persistent native APFS Data";
    report[@"prefix_visible_path"]=@(NABU_JB_PREFIX);
    report[@"prefix_uses_bindfs"]=@NO;
    NSData *data=[NSData dataWithContentsOfFile:@(NABU_JB_BASE "/boot-paths.json")];
    if (data) report[@"boot_path_receipt"]=[NSJSONSerialization JSONObjectWithData:data options:0 error:nil] ?: @{};
    return YES;
}

static BOOL configureDirectories(void) {
    for (NSString *suffix in @[@"var/mobile",@"var/mobile/Library",@"var/mobile/Library/Caches",@"var/mobile/Library/Preferences",
            @"var/mobile/Documents",@"var/lib/apt/sileolists",@"var/lib/apt/sileolists/partial"]) {
        NSString *path=[@"/var/jb" stringByAppendingPathComponent:suffix];
        if (!makeDirectory(path) || chown(path.fileSystemRepresentation,501,501)) return failure(@"mobile_directories");
    }
    if (!makeDirectory(@"/var/mobile/tmp")) return NO;
    if (chown("/var/mobile/tmp",501,501) || chmod("/var/mobile/tmp",0700)) return failure(@"mobile_tmp");
    NSString *sources=@"Types: deb\nURIs: https://apt.procurs.us/\nSuites: iphoneos-arm64-rootless/1800\nComponents: main\n";
    if (![sources writeToFile:@"/var/jb/etc/apt/sources.list.d/procursus.sources" atomically:YES encoding:NSUTF8StringEncoding error:nil]) return failure(@"apt_source");
    NSString *ca=@"Acquire::https::CaInfo \"/var/jb/etc/ssl/certs/cacert.pem\";\n";
    if (![ca writeToFile:@"/var/jb/etc/apt/apt.conf.d/10nabu-ca" atomically:YES encoding:NSUTF8StringEncoding error:nil]) return failure(@"apt_ca");
    return YES;
}

static int setup(void) {
    steps=[NSMutableArray new];
    report=[@{@"uid":@(getuid()),@"euid":@(geteuid()),@"build":[NSBundle.mainBundle objectForInfoDictionaryKey:@"CFBundleVersion"],@"steps":steps,
        @"started":@([[NSDate date] timeIntervalSince1970]),@"standard_jailbreak_complete":@NO} mutableCopy];
    if (getuid()!=0 || geteuid()!=0) return 1;
    if (!makeDirectory(output)) return 1;
    chown(output.fileSystemRepresentation,501,501);
    if (!makeDirectory(base) || !extractSeed() || !mountPrefix()) return 2;
    NSString *probeOutput=[output stringByAppendingPathComponent:@"filesystem.json"];
    int probe=nabu_jailbreak_fs_probe(NABU_JB_PREFIX,"/var/jb",probeOutput.fileSystemRepresentation);
    report[@"filesystem_probe_passed"]=@(probe==0);
    if (probe) { errno=EIO; failure(@"filesystem_probe"); return 2; }
    if (!configureDirectories()) return 2;
    if (![run(@"shell",@[@"/var/jb/bin/sh",@"-c",@"printf 'NABU_SHELL_OK\\n'; id"],-1)[@"passed"] boolValue]) return 3;
    run(@"user_database",@[@"/var/jb/usr/sbin/pwd_mkdb",@"-p",@"/var/jb/etc/master.passwd"],-1);
    run(@"firmware",@[@"/var/jb/usr/libexec/firmware"],-1);
    for (NSString *package in @[@"debianutils",@"apt",@"dash",@"bash",@"zsh",@"vi"]) {
        NSString *script=[NSString stringWithFormat:@"/var/jb/Library/dpkg/info/%@.postinst",package];
        run([@"configure_" stringByAppendingString:package],@[@"/var/jb/bin/sh",script,@"configure",@"999999"],-1);
    }
    run(@"unpack_sileo_ellekit",@[@"/var/jb/usr/bin/dpkg",@"--no-triggers",@"--unpack",
        [input stringByAppendingPathComponent:@"sileo-2.5.1.deb"],[input stringByAppendingPathComponent:@"ellekit-0.4.5.deb"]],-1);
    run(@"configure_sileo_ellekit",@[@"/var/jb/usr/bin/dpkg",@"--no-triggers",@"--configure",@"org.coolstar.sileo",@"ellekit"],-1);
    run(@"register_sileo",@[@"/var/jb/usr/bin/uicache",@"-p",@(NABU_JB_PREFIX "/Applications/Sileo.app")],-1);
    run(@"sileo_setuid",@[@"/var/jb/Applications/Sileo.app/giveMeRoot",@"/var/jb/usr/bin/id",@"-u"],501);
    run(@"package_status",@[@"/var/jb/usr/bin/dpkg-query",@"-W",@"-f=${Package} ${Version} ${Status}\\n"],-1);
    run(@"dependency_check",@[@"/var/jb/usr/bin/apt-get",@"check"],-1);
    NSMutableArray *inventory=[NSMutableArray new];
    for (NSString *path in @[@"/var/jb",@"/var/jb/usr/bin/dpkg",@"/var/jb/Applications/Sileo.app/giveMeRoot",@"/var/jb/usr/lib/TweakLoader.dylib"]) {
        struct stat st;
        int status=stat(path.fileSystemRepresentation,&st);
        NSMutableDictionary *item=[@{@"path":path,@"errno":@(status==0?0:errno)} mutableCopy];
        if (!status) { item[@"uid"]=@(st.st_uid); item[@"gid"]=@(st.st_gid); item[@"mode"]=@(st.st_mode&07777); }
        [inventory addObject:item];
    }
    report[@"inventory"]=inventory;
    report[@"finished"]=@([[NSDate date] timeIntervalSince1970]);
    BOOL all=YES;
    for (NSDictionary *step in steps) all=all && [step[@"passed"] boolValue];
    report[@"all_steps_passed"]=@(all);
    publish();
    return all?0:4;
}

@interface NabuSetupDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic,strong) UIWindow *window;
@end
@implementation NabuSetupDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options;
    self.window=[[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    UIViewController *controller=[UIViewController new];
    controller.view.backgroundColor=UIColor.systemBackgroundColor;
    UILabel *label=[[UILabel alloc] initWithFrame:CGRectMake(30,140,UIScreen.mainScreen.bounds.size.width-60,260)];
    label.numberOfLines=0; label.textAlignment=NSTextAlignmentCenter;
    label.text=@"正在安装越狱软件环境…\n请保持此页面和 USB 连接。";
    [controller.view addSubview:label]; self.window.rootViewController=controller; [self.window makeKeyAndVisible];
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0), ^{
        const char *path=NSBundle.mainBundle.executablePath.fileSystemRepresentation;
        char *args[]={(char *)path,"--setup",NULL};
        posix_spawnattr_t attr; posix_spawnattr_init(&attr);
        posix_spawnattr_set_persona_np(&attr,99,1);
        posix_spawnattr_set_persona_uid_np(&attr,0); posix_spawnattr_set_persona_gid_np(&attr,0);
        pid_t pid=0; int error=posix_spawn(&pid,path,NULL,&attr,args,environ);
        posix_spawnattr_destroy(&attr);
        int status=0; pid_t waited=-1;
        if (!error) do { waited=waitpid(pid,&status,0); } while (waited<0 && errno==EINTR);
        BOOL passed=!error && waited==pid && WIFEXITED(status) && WEXITSTATUS(status)==0;
        dispatch_async(dispatch_get_main_queue(), ^{
            label.text=passed ? @"环境安装与检查已结束。\n请保持 USB 连接，等待核对结果。" :
                [NSString stringWithFormat:@"环境配置遇到错误。\n启动错误：%d，等待状态：%d。\n请保持 USB 连接以读取记录。",error,status];
        });
    });
    return YES;
}
@end

int main(int argc,char **argv) {
    int probeChild=nabu_jailbreak_fs_probe_child(argc,argv);
    if (probeChild>=0) return probeChild;
    @autoreleasepool {
        if (argc==2 && !strcmp(argv[1],"--setup")) return setup();
        return UIApplicationMain(argc,argv,nil,NSStringFromClass(NabuSetupDelegate.class));
    }
}
