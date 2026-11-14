#define _GNU_SOURCE 1
#include "jailbreak_fs_probe.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <spawn.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <sys/xattr.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#include <sys/mount.h>
#endif

extern char **environ;

struct probe {
    FILE *out;
    unsigned rows, failed, skipped;
    char lower[PATH_MAX], upper[PATH_MAX];
};

static void json_string(FILE *out, const char *value) {
    fputc('"',out);
    for (const unsigned char *p=(const unsigned char *)value; *p; p++) {
        if (*p=='"' || *p=='\\') fprintf(out,"\\%c",*p);
        else if (*p<32) fprintf(out,"\\u%04x",*p);
        else fputc(*p,out);
    }
    fputc('"',out);
}

static void result(struct probe *p, const char *name, bool passed, int error) {
    if (p->rows++) fputs(",\n",p->out);
    fputs("    {\"name\":",p->out); json_string(p->out,name);
    fprintf(p->out,",\"passed\":%s,\"errno\":%d}",passed?"true":"false",error);
    if (!passed) p->failed++;
    fflush(p->out);
}

static void skipped(struct probe *p, const char *name, const char *reason) {
    if (p->rows++) fputs(",\n",p->out);
    fputs("    {\"name\":",p->out); json_string(p->out,name);
    fputs(",\"passed\":null,\"status\":\"not_run\",\"reason\":",p->out);
    json_string(p->out,reason); fputc('}',p->out);
    p->skipped++; fflush(p->out);
}

static int path(char *buffer, const char *directory, const char *leaf) {
    int n=snprintf(buffer,PATH_MAX,"%s/%s",directory,leaf);
    if (n<0 || n>=PATH_MAX) { errno=ENAMETOOLONG; return -1; }
    return 0;
}

static bool equal_at(int fd, off_t offset, const char *wanted) {
    char buffer[64]; size_t size=strlen(wanted);
    ssize_t n=pread(fd,buffer,size,offset);
    if (n<0) return false;
    if ((size_t)n!=size || memcmp(buffer,wanted,size)) { errno=EIO; return false; }
    return true;
}

static bool file_equals(const char *name, const char *wanted) {
    int fd=open(name,O_RDONLY);
    if (fd<0) return false;
    bool ok=equal_at(fd,0,wanted); int error=errno;
    close(fd); errno=error;
    return ok;
}

static int new_file(const char *name, const char *contents) {
    int fd=open(name,O_RDWR|O_CREAT|O_EXCL,0600);
    if (fd<0) return -1;
    size_t size=strlen(contents);
    ssize_t n=write(fd,contents,size); int error=errno;
    if (n>=0 && (size_t)n!=size) error=EIO;
    if (n<0 || (size_t)n!=size) { close(fd); errno=error; return -1; }
    return fd;
}

static bool size_is(int fd, off_t wanted) {
    struct stat s;
    if (fstat(fd,&s)) return false;
    if (s.st_size!=wanted) { errno=EIO; return false; }
    return true;
}

#define CHECK(p, name, expression) do { \
    errno=0; bool check_ok=(expression); int check_error=errno; \
    result((p),(name),check_ok,check_ok?0:(check_error?check_error:EIO)); \
} while (0)

static int set_lock(int fd, bool use_flock, bool lock) {
    if (use_flock) return flock(fd,lock?(LOCK_EX|LOCK_NB):LOCK_UN);
    struct flock request={0};
    request.l_type=lock?F_WRLCK:F_UNLCK;
    request.l_whence=SEEK_SET; request.l_start=0; request.l_len=1;
    return fcntl(fd,F_SETLK,&request);
}

int nabu_jailbreak_fs_probe_child(int argc,char **argv) {
    if (argc<2 || strcmp(argv[1],"--nabu-fs-lock-child")) return -1;
    if (argc!=5) return EINVAL;
    int fd=open(argv[3],O_RDWR);
    if (fd<0) return errno;
    int status=set_lock(fd,!strcmp(argv[2],"flock"),true);
    int error=status<0?errno:0;
    close(fd);
    bool expect_busy=!strcmp(argv[4],"busy");
    if (expect_busy && status<0 && (error==EAGAIN || error==EACCES || error==EWOULDBLOCK)) return 0;
    if (!expect_busy && status==0) return 0;
    return error?error:128; /* Unexpected lock acquisition is not an errno. */
}

static int lock_child(const char *file,bool use_flock,bool expect_busy) {
    char self[PATH_MAX];
#ifdef __APPLE__
    uint32_t size=sizeof(self);
    if (_NSGetExecutablePath(self,&size)) return ENAMETOOLONG;
#else
    ssize_t size=readlink("/proc/self/exe",self,sizeof(self)-1);
    if (size<0) return errno;
    self[size]=0;
#endif
    char *args[]={self,"--nabu-fs-lock-child",use_flock?"flock":"fcntl",
        (char *)file,expect_busy?"busy":"free",NULL};
    pid_t pid=0;
    int error=posix_spawn(&pid,self,NULL,NULL,args,environ);
    if (error) return error;
    int status=0;
    for (unsigned i=0;i<500;i++) {
        pid_t waited=waitpid(pid,&status,WNOHANG);
        if (waited==pid) return WIFEXITED(status)?WEXITSTATUS(status):EINTR;
        if (waited<0 && errno!=EINTR) return errno;
        usleep(10000);
    }
    kill(pid,SIGKILL);
    while (waitpid(pid,&status,0)<0 && errno==EINTR) {}
    return ETIMEDOUT;
}

static void locks(struct probe *p,const char *lower,const char *upper) {
    for (unsigned kind=0;kind<2;kind++) for (unsigned direction=0;direction<2;direction++) {
        char name[100];
        snprintf(name,sizeof(name),"%s_%s_lock_conflict_and_release",kind?"flock":"fcntl",direction?"upper_to_lower":"lower_to_upper");
        int fd=open(direction?upper:lower,O_RDWR);
        if (fd<0) { result(p,name,false,errno); continue; }
        int error=0;
        if (set_lock(fd,kind!=0,true)) error=errno;
        else {
            error=lock_child(direction?lower:upper,kind!=0,true);
            if (set_lock(fd,kind!=0,false) && !error) error=errno;
            if (!error) error=lock_child(direction?lower:upper,kind!=0,false);
        }
        close(fd); result(p,name,error==0,error);
    }
}

static void mapping(struct probe *p,int *upper_fd,int *lower_fd) {
    size_t page=(size_t)getpagesize(), length=page*2;
    errno=0;
    bool extended=ftruncate(*upper_fd,(off_t)page*3)==0 && size_is(*lower_fd,(off_t)page*3);
    result(p,"upper_extend_lower_size",extended,extended?0:errno);
    if (!extended) { skipped(p,"shared_mapping_checks","the required file extension failed"); return; }
    unsigned char *upper=mmap(NULL,length,PROT_READ|PROT_WRITE,MAP_SHARED,*upper_fd,0);
    int error=upper==MAP_FAILED?errno:0;
    result(p,"upper_shared_mmap",upper!=MAP_FAILED,error);
    unsigned char *lower=mmap(NULL,length,PROT_READ|PROT_WRITE,MAP_SHARED,*lower_fd,0);
    error=lower==MAP_FAILED?errno:0;
    result(p,"lower_shared_mmap",lower!=MAP_FAILED,error);
    if (upper==MAP_FAILED || lower==MAP_FAILED) {
        skipped(p,"shared_mapping_coherence_and_truncate","a required mmap failed");
        if (upper!=MAP_FAILED) munmap(upper,length);
        if (lower!=MAP_FAILED) munmap(lower,length);
        return;
    }
    CHECK(p,"upper_pwrite_lower_mapping",pwrite(*upper_fd,"UPPER",5,32)==5 && !memcmp(lower+32,"UPPER",5));
    CHECK(p,"lower_pwrite_upper_mapping",pwrite(*lower_fd,"LOWER",5,64)==5 && !memcmp(upper+64,"LOWER",5));
    memcpy(upper+128,"UPMAP",5);
    CHECK(p,"upper_msync_lower_pread",msync(upper,length,MS_SYNC)==0 && equal_at(*lower_fd,128,"UPMAP") && !memcmp(lower+128,"UPMAP",5));
    memcpy(lower+192,"LOMAP",5);
    CHECK(p,"lower_msync_upper_pread",msync(lower,length,MS_SYNC)==0 && equal_at(*upper_fd,192,"LOMAP") && !memcmp(upper+192,"LOMAP",5));
    upper[page+128]=0x51;
    CHECK(p,"mapping_seed_before_lower_truncate",msync(upper,length,MS_SYNC)==0);
    CHECK(p,"lower_shrink_upper_open_size",ftruncate(*lower_fd,(off_t)page+64)==0 && size_is(*upper_fd,(off_t)page+64));
    CHECK(p,"lower_regrow_upper_mapping_zero_tail",ftruncate(*lower_fd,(off_t)page*3)==0 && size_is(*upper_fd,(off_t)page*3) && upper[page+128]==0);
    lower[page+128]=0x52;
    CHECK(p,"mapping_seed_before_upper_truncate",msync(lower,length,MS_SYNC)==0);
    CHECK(p,"upper_shrink_lower_open_size",ftruncate(*upper_fd,(off_t)page+64)==0 && size_is(*lower_fd,(off_t)page+64));
    CHECK(p,"upper_regrow_lower_mapping_zero_tail",ftruncate(*upper_fd,(off_t)page*3)==0 && size_is(*lower_fd,(off_t)page*3) && lower[page+128]==0);
    close(*upper_fd); *upper_fd=-1; close(*lower_fd); *lower_fd=-1;
    memcpy(upper+256,"HELD",4);
    CHECK(p,"upper_mapping_without_open_descriptors",msync(upper,length,MS_SYNC)==0);
    memcpy(lower+288,"LIVE",4);
    CHECK(p,"lower_mapping_without_open_descriptors",msync(lower,length,MS_SYNC)==0);
    char name[PATH_MAX]; path(name,p->lower,"data"); *lower_fd=open(name,O_RDWR);
    path(name,p->upper,"data"); *upper_fd=open(name,O_RDWR);
    if (*lower_fd<0 || *upper_fd<0) {
        result(p,"reopen_after_mapping_descriptors_close",false,errno);
    } else {
        CHECK(p,"upper_mapping_survives_original_fd_close",equal_at(*lower_fd,256,"HELD"));
        CHECK(p,"lower_mapping_survives_original_fd_close",equal_at(*upper_fd,288,"LIVE"));
    }
    CHECK(p,"upper_munmap",munmap(upper,length)==0);
    CHECK(p,"lower_munmap",munmap(lower,length)==0);
}

static void attributes(struct probe *p,const char *lower,const char *upper) {
    struct stat s;
    CHECK(p,"chmod_upper_observed_lower",chmod(upper,0640)==0 && stat(lower,&s)==0 && (s.st_mode&07777)==0640);
    CHECK(p,"chmod_lower_observed_upper",chmod(lower,0600)==0 && stat(upper,&s)==0 && (s.st_mode&07777)==0600);
    if (geteuid()==0) {
        CHECK(p,"chown_upper_observed_lower",chown(upper,501,501)==0 && stat(lower,&s)==0 && s.st_uid==501 && s.st_gid==501);
        CHECK(p,"chown_lower_observed_upper",chown(lower,0,0)==0 && stat(upper,&s)==0 && s.st_uid==0 && s.st_gid==0);
    } else skipped(p,"chown_cross_alias","requires root; host test did not exercise ownership changes");
    char value[16]={0};
#ifdef __APPLE__
    const char *key="com.nabu.fsprobe";
    CHECK(p,"setxattr_upper_get_lower",setxattr(upper,key,"UP",2,0,0)==0 && getxattr(lower,key,value,sizeof(value),0,0)==2 && !memcmp(value,"UP",2));
    CHECK(p,"setxattr_lower_get_upper",setxattr(lower,key,"LO",2,0,0)==0 && getxattr(upper,key,value,sizeof(value),0,0)==2 && !memcmp(value,"LO",2));
    CHECK(p,"removexattr_upper",removexattr(upper,key,0)==0);
    errno=0; ssize_t n=getxattr(lower,key,value,sizeof(value),0,0); int error=errno;
    result(p,"removed_xattr_absent_lower",n<0 && error==ENOATTR,error);
#else
    const char *key="user.nabu.fsprobe";
    CHECK(p,"setxattr_upper_get_lower",setxattr(upper,key,"UP",2,0)==0 && getxattr(lower,key,value,sizeof(value))==2 && !memcmp(value,"UP",2));
    CHECK(p,"setxattr_lower_get_upper",setxattr(lower,key,"LO",2,0)==0 && getxattr(upper,key,value,sizeof(value))==2 && !memcmp(value,"LO",2));
    CHECK(p,"removexattr_upper",removexattr(upper,key)==0);
    errno=0; ssize_t n=getxattr(lower,key,value,sizeof(value)); int error=errno;
    result(p,"removed_xattr_absent_lower",n<0 && error==ENODATA,error);
#endif
}

static void namespace_ops(struct probe *p,const char *lower_data,const char *upper_data) {
    char a[PATH_MAX],b[PATH_MAX],raw[PATH_MAX]; struct stat first,second;
    path(a,p->upper,"symbol"); path(raw,p->lower,"symbol");
    char linktext[32]={0};
    CHECK(p,"symlink_upper_readlink_lower",symlink("data",a)==0 && readlink(raw,linktext,sizeof(linktext))==4 && !memcmp(linktext,"data",4) && file_equals(raw,"seed"));
    path(a,p->upper,"hard"); path(raw,p->lower,"hard");
    CHECK(p,"hardlink_upper_seen_lower",link(upper_data,a)==0 && stat(lower_data,&first)==0 && stat(raw,&second)==0 && first.st_ino==second.st_ino && first.st_nlink==2);
    path(a,p->lower,"raw-hard"); path(raw,p->upper,"raw-hard");
    CHECK(p,"hardlink_lower_seen_upper",link(lower_data,a)==0 && file_equals(raw,"seed") && stat(upper_data,&second)==0 && second.st_nlink==3);
    path(a,p->upper,"replace"); int retained=new_file(a,"old");
    result(p,"replacement_old_file",retained>=0,retained>=0?0:errno);
    path(raw,p->lower,"replace"); CHECK(p,"replacement_prime_lower_lookup",file_equals(raw,"old"));
    path(b,p->upper,"replacement"); int fd=new_file(b,"new");
    result(p,"replacement_new_file",fd>=0,fd>=0?0:errno); if (fd>=0) close(fd);
    CHECK(p,"rename_atomic_replace_and_open_inode",retained>=0 && fd>=0 && rename(b,a)==0 && file_equals(raw,"new") && equal_at(retained,0,"old"));
    if (retained>=0) close(retained);
    path(a,p->upper,"empty-directory"); path(raw,p->lower,"empty-directory");
    CHECK(p,"mkdir_and_rmdir_upper",mkdir(a,0700)==0 && stat(raw,&first)==0 && S_ISDIR(first.st_mode) && rmdir(a)==0);
    errno=0; int directory_status=lstat(raw,&first); int directory_error=errno;
    result(p,"removed_directory_absent_lower",directory_status<0 && directory_error==ENOENT,directory_error);
    path(a,p->upper,"directory"); CHECK(p,"mkdir_upper",mkdir(a,0700)==0);
    path(b,p->upper,"directory/moved"); path(a,p->upper,"replace");
    CHECK(p,"rename_into_directory",rename(a,b)==0);
    path(a,p->upper,"directory"); path(b,p->upper,"renamed-directory");
    path(raw,p->lower,"renamed-directory/moved");
    CHECK(p,"rename_directory_and_lower_lookup",rename(a,b)==0 && file_equals(raw,"new"));
    path(a,p->upper,"renamed-directory/..");
    CHECK(p,"renamed_directory_parent",stat(a,&first)==0 && stat(p->upper,&second)==0 && first.st_ino==second.st_ino);
    path(a,p->upper,"swap-a"); path(b,p->upper,"swap-b");
    int fa=new_file(a,"AAA"),fb=new_file(b,"BBB");
    if (fa>=0) close(fa); if (fb>=0) close(fb);
#ifdef __APPLE__
    CHECK(p,"rename_swap",fa>=0 && fb>=0 && renamex_np(a,b,RENAME_SWAP)==0);
    path(a,p->lower,"swap-a"); path(b,p->lower,"swap-b");
    CHECK(p,"rename_swap_lower_contents",file_equals(a,"BBB") && file_equals(b,"AAA"));
#else
    skipped(p,"rename_swap","Apple renamex_np is unavailable on this host");
#endif
    path(a,p->upper,"unlinked"); path(b,p->lower,"unlinked");
    fa=new_file(a,"open"); fb=open(b,O_RDWR);
    CHECK(p,"unlink_with_both_aliases_open",fa>=0 && fb>=0 && unlink(a)==0 && equal_at(fb,0,"open") && pwrite(fa,"kept",4,0)==4 && equal_at(fb,0,"kept"));
    errno=0; int status=lstat(b,&first); int error=errno;
    result(p,"unlinked_name_absent_lower",status<0 && error==ENOENT,error);
    if (fa>=0) close(fa); if (fb>=0) close(fb);
}

static bool readonly_mount(struct probe *p) {
#ifdef __APPLE__
    char source[PATH_MAX],target[PATH_MAX],file[PATH_MAX],rofile[PATH_MAX];
    path(source,p->lower,"ro-source"); path(target,p->lower,"ro-target");
    if (mkdir(source,0700) || mkdir(target,0700)) { result(p,"readonly_mount_directories",false,errno); return false; }
    path(file,source,"child"); int fd=new_file(file,"readonly");
    if (fd<0) { result(p,"readonly_source_file",false,errno); return false; } close(fd);
    int status=mount("bindfs",target,MNT_RDONLY,source); int error=status<0?errno:0;
    result(p,"explicit_readonly_bind_mount",status==0,error);
    if (status) return false;
    struct statfs fs;
    CHECK(p,"explicit_readonly_mount_flag",statfs(target,&fs)==0 && (fs.f_flags&MNT_RDONLY));
    path(rofile,target,"child"); CHECK(p,"readonly_alias_read",file_equals(rofile,"readonly"));
    errno=0; fd=open(rofile,O_RDWR); error=errno;
    result(p,"readonly_alias_rejects_write_open",fd<0 && error==EROFS,error); if (fd>=0) close(fd);
    errno=0; status=chmod(rofile,0644); error=errno;
    result(p,"readonly_alias_rejects_chmod",status<0 && error==EROFS,error);
    errno=0; status=unlink(rofile); error=errno;
    result(p,"readonly_alias_rejects_unlink",status<0 && error==EROFS,error);
    path(rofile,target,"new"); errno=0; fd=open(rofile,O_WRONLY|O_CREAT|O_EXCL,0600); error=errno;
    result(p,"readonly_alias_rejects_create",fd<0 && error==EROFS,error); if (fd>=0) close(fd);
    status=unmount(target,0); error=status?errno:0;
    result(p,"readonly_alias_unmount",status==0,error);
    return status!=0;
#else
    skipped(p,"explicit_readonly_bind_mount","Darwin bindfs mount is unavailable on this host");
    return false;
#endif
}

static void cleanup(struct probe *p,bool mounted) {
    const char *files[]={"data","symbol","hard","raw-hard","replace","replacement","swap-a","swap-b","unlinked",
        "directory/moved","renamed-directory/moved","ro-source/child","ro-source/new"};
    const char *directories[]={"empty-directory","directory","renamed-directory","ro-target","ro-source"};
    int error=0; char name[PATH_MAX];
    for (unsigned i=0;i<sizeof(files)/sizeof(files[0]);i++) {
        path(name,p->lower,files[i]);
        if (unlink(name) && errno!=ENOENT && !error) error=errno;
    }
    for (unsigned i=0;i<sizeof(directories)/sizeof(directories[0]);i++) {
        if (mounted && i>=3) continue;
        path(name,p->lower,directories[i]);
        if (rmdir(name) && errno!=ENOENT && !error) error=errno;
    }
    if (!mounted && rmdir(p->lower) && !error) error=errno;
    if (mounted && !error) error=EBUSY;
    result(p,"remove_only_probe_owned_files",error==0,error);
}

int nabu_jailbreak_fs_probe(const char *lower_prefix,const char *upper_prefix,const char *output_path) {
    struct probe p={0};
    p.out=fopen(output_path,"w"); if (!p.out) return 1;
    fputs("{\n  \"lower_prefix\":",p.out); json_string(p.out,lower_prefix);
    fputs(",\n  \"upper_prefix\":",p.out); json_string(p.out,upper_prefix);
    fprintf(p.out,",\n  \"uid\":%u,\"euid\":%u,\n  \"checks\":[\n",(unsigned)getuid(),(unsigned)geteuid());
    int upper_fd=-1,lower_fd=-1; bool owned=false,mounted=false;
    char lower_data[PATH_MAX],upper_data[PATH_MAX];
    if (path(p.upper,upper_prefix,".nabu-fs-probe-XXXXXX")) { result(&p,"probe_path",false,errno); goto finish; }
    errno=0; char *created=mkdtemp(p.upper);
    result(&p,"create_unique_directory_through_upper",created!=NULL,created?0:errno);
    if (!created) goto finish;
    if (path(p.lower,lower_prefix,strrchr(p.upper,'/')+1)) { result(&p,"lower_probe_path",false,errno); goto finish; }
    struct stat directory;
    if (stat(p.lower,&directory) || !S_ISDIR(directory.st_mode)) {
        result(&p,"created_directory_visible_lower",false,errno?errno:EIO); rmdir(p.upper); goto finish;
    }
    owned=true; result(&p,"created_directory_visible_lower",true,0);
    path(upper_data,p.upper,"data"); path(lower_data,p.lower,"data");
    upper_fd=new_file(upper_data,"seed");
    result(&p,"create_regular_file_upper",upper_fd>=0,upper_fd>=0?0:errno);
    if (upper_fd<0) goto finish;
    lower_fd=open(lower_data,O_RDWR);
    result(&p,"open_same_file_lower",lower_fd>=0,lower_fd>=0?0:errno);
    if (lower_fd<0) goto finish;
    CHECK(&p,"upper_write_fsync_lower_read",fsync(upper_fd)==0 && equal_at(lower_fd,0,"seed"));
    CHECK(&p,"lower_write_fsync_upper_read",pwrite(lower_fd,"back",4,0)==4 && fsync(lower_fd)==0 && equal_at(upper_fd,0,"back"));
    CHECK(&p,"restore_probe_seed",pwrite(upper_fd,"seed",4,0)==4 && fsync(upper_fd)==0);
    mapping(&p,&upper_fd,&lower_fd);
    if (upper_fd<0 || lower_fd<0) goto finish;
    attributes(&p,lower_data,upper_data);
    locks(&p,lower_data,upper_data);
    namespace_ops(&p,lower_data,upper_data);
    mounted=readonly_mount(&p);
finish:
    if (upper_fd>=0) close(upper_fd); if (lower_fd>=0) close(lower_fd);
    if (owned) cleanup(&p,mounted);
    fprintf(p.out,"\n  ],\n  \"failed\":%u,\"not_run\":%u,\"all_executed_passed\":%s,\"all_target_checks_passed\":%s,\n  \"probe_directory\":",
        p.failed,p.skipped,p.failed?"false":"true",(p.failed||p.skipped)?"false":"true");
    json_string(p.out,p.upper);
    fputs(",\n  \"setuid_and_reboot_persistence\":\"separate_checks_required\"\n}\n",p.out);
    int error=ferror(p.out); if (fclose(p.out)) error=1;
    return (p.failed||error)?1:p.skipped?2:0;
}
