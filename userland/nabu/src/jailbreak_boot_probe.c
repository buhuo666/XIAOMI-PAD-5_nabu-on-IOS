#include "jailbreak_paths.h"
#include <errno.h>
#include <mach-o/dyld.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

int main(void) {
    struct stat st;
    int requested=stat(NABU_JB_PREFIX "/.nabu-tweaks-enabled",&st)==0;
    int loaded=0;
    for (uint32_t i=0;i<_dyld_image_count();i++) {
        const char *name=_dyld_get_image_name(i);
        if (name && (strstr(name,"/ellekit/libinjector.dylib") || strstr(name,"/usr/lib/TweakLoader.dylib"))) loaded=1;
    }
    const char *env=getenv("DYLD_INSERT_LIBRARIES");
    int environment=env && !strcmp(env,"/var/jb/usr/lib/TweakLoader.dylib");
    int passed=requested && loaded && environment && getuid()==501 && geteuid()==501;
    struct timeval boot={0}; size_t bootSize=sizeof(boot);
    int bootError=sysctlbyname("kern.boottime",&boot,&bootSize,NULL,0)?errno:0;
    passed=passed && bootError==0;
    FILE *out=fopen("/var/mobile/Media/NabuJailbreak/Setup/boot-injection.json","w");
    if (!out) return 2;
    fprintf(out,"{\"pid\":%d,\"uid\":%u,\"euid\":%u,\"tweaks_requested\":%s,\"loader_loaded\":%s,\"kernel_injected_environment\":%s,\"passed\":%s,\"boot_sec\":%lld,\"boot_usec\":%d,\"boot_time_errno\":%d,\"observed_at\":%lld}\n",
        getpid(),(unsigned)getuid(),(unsigned)geteuid(),requested?"true":"false",loaded?"true":"false",environment?"true":"false",passed?"true":"false",
        (long long)boot.tv_sec,boot.tv_usec,bootError,(long long)time(NULL));
    fflush(out);
    int saved=fsync(fileno(out));
    if (fclose(out) || saved) return 2;
    return requested && !passed ? 1 : 0;
}
