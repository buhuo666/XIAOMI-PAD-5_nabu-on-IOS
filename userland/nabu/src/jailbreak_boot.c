#include "jailbreak_paths.h"
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

int main(int argc,char **argv) {
    if (argc!=2 || strcmp(argv[1],"--restore")) return 2;
    struct stat st;
    if (stat(NABU_JB_PREFIX "/.nabu-seed-v1",&st) && errno==ENOENT) return 0;
    const char *stage=NULL;
    int result=nabu_jailbreak_restore_paths(&stage),error=result?errno:0;
    int paths=result==0;
    int requested=stat(NABU_JB_PREFIX "/.nabu-tweaks-enabled",&st)==0;
    int tweaks=0;
    if (!result && requested) {
        char previous[4096];
        stage="tweak_configuration";
        result=nabu_jailbreak_enable_tweaks(previous,sizeof(previous));
        error=result?errno:0;
        tweaks=result==0;
    }
    printf("NABU JAILBREAK: restore %s errno=%d\n",stage,error);
    struct timeval boot={0}; size_t bootSize=sizeof(boot);
    int bootError=sysctlbyname("kern.boottime",&boot,&bootSize,NULL,0)?errno:0;
    const char *reports[]={NABU_JB_BASE "/boot-paths.json","/var/mobile/Media/NabuJailbreak/Setup/boot-paths.json"};
    for (unsigned i=0;i<2;i++) {
        FILE *out=fopen(reports[i],"w");
        if (!out) continue;
        fprintf(out,"{\"paths_restored\":%s,\"stage\":\"%s\",\"errno\":%d,\"pid\":%d,\"tweaks_requested\":%s,\"tweaks_restored\":%s,\"boot_sec\":%lld,\"boot_usec\":%d,\"boot_time_errno\":%d,\"observed_at\":%lld}\n",
            paths?"true":"false",stage,error,getpid(),requested?"true":"false",tweaks?"true":"false",
            (long long)boot.tv_sec,boot.tv_usec,bootError,(long long)time(NULL));
        fflush(out);
        fsync(fileno(out));
        fclose(out);
    }
    return result?1:0;
}
