#include "jailbreak_paths.h"
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc,char **argv) {
    if (argc!=2 || strcmp(argv[1],"--restore")) return 2;
    struct stat st;
    if (stat(NABU_JB_PREFIX "/.nabu-seed-v1",&st) && errno==ENOENT) return 0;
    const char *stage=NULL;
    int result=nabu_jailbreak_restore_paths(&stage),error=result?errno:0;
    printf("NABU JAILBREAK: restore %s errno=%d\n",stage,error);
    FILE *out=fopen(NABU_JB_BASE "/boot-paths.json","w");
    if (out) {
        fprintf(out,"{\"paths_restored\":%s,\"stage\":\"%s\",\"errno\":%d,\"pid\":%d}\n",
            result?"false":"true",stage,error,getpid());
        fflush(out);
        fsync(fileno(out));
        fclose(out);
    }
    return result?1:0;
}
