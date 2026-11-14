/* Keep the writable prefix on its original APFS vnode and pager. */
#include "jailbreak_paths.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <unistd.h>

static int directory(const char *path) {
    if (mkdir(path,0755)==0) return 0;
    if (errno!=EEXIST) return -1;
    struct stat st;
    if (stat(path,&st)) return -1;
    if (!S_ISDIR(st.st_mode)) { errno=ENOTDIR; return -1; }
    return 0;
}

static int link_to(const char *path,const char *target) {
    if (symlink(target,path)==0) return 0;
    if (errno!=EEXIST) return -1;
    char current[1024];
    ssize_t n=readlink(path,current,sizeof(current)-1);
    if (n<0) return -1;
    current[n]=0;
    if (!strcmp(current,target)) return 0;
    errno=EEXIST;
    return -1;
}

static int prefix_link(void) {
    if (!link_to("/var/jb",NABU_JB_PREFIX)) return 0;
    if (errno!=EEXIST) return -1;
    char previous[1024],temporary[128];
    ssize_t n=readlink("/var/jb",previous,sizeof(previous)-1);
    if (n<0) return -1;
    previous[n]=0;
    /* Migrate only the link created by setup build 1/2. */
    if (strcmp(previous,"/private/preboot/nabu-jb/procursus")) { errno=EEXIST; return -1; }
    snprintf(temporary,sizeof(temporary),"/var/jb.nabu-%d",getpid());
    if (symlink(NABU_JB_PREFIX,temporary)) return -1;
    if (rename(temporary,"/var/jb")) {
        int error=errno;
        unlink(temporary);
        errno=error;
        return -1;
    }
    int fd=open("/var",O_RDONLY|O_DIRECTORY);
    if (fd<0) return -1;
    int result=fsync(fd),error=errno;
    close(fd);
    errno=error;
    return result;
}

static int readonly_union(const char *source,const char *target) {
    struct statfs fs;
    if (statfs(target,&fs)) return -1;
    if (!strcmp(fs.f_fstypename,"bindfs") && !strcmp(fs.f_mntfromname,source)) return 0;
    return mount("bindfs",target,MNT_RDONLY|MNT_UNION,(void *)source);
}

int nabu_jailbreak_restore_paths(const char **stage) {
    struct stat st;
    *stage="existing_seed";
    if (stat(NABU_JB_PREFIX "/.nabu-seed-v1",&st)) return -1;
    *stage="persistent_prefix_link";
    if (prefix_link()) return -1;
    *stage="command_directories";
    if (directory(NABU_JB_BASE "/bin") || directory(NABU_JB_BASE "/usr-bin")) return -1;
    const char *names[]={"sh","mv","cp","rm","mkdir","chmod"};
    for (unsigned i=0;i<sizeof(names)/sizeof(names[0]);i++) {
        char path[256],target[256];
        snprintf(path,sizeof(path),NABU_JB_BASE "/bin/%s",names[i]);
        snprintf(target,sizeof(target),"/var/jb/usr/bin/%s",names[i]);
        if (link_to(path,target)) return -1;
    }
    if (link_to(NABU_JB_BASE "/usr-bin/env","/var/jb/usr/bin/env")) return -1;
    *stage="readonly_command_mounts";
    if (readonly_union(NABU_JB_BASE "/bin","/bin") ||
        readonly_union(NABU_JB_BASE "/usr-bin","/usr/bin")) return -1;
    *stage="ready";
    return 0;
}
