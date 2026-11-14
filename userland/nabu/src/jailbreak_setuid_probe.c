#include <errno.h>
#include <spawn.h>
#include <stdio.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

int main(int argc,char **argv) {
    if (argc==3 && !strcmp(argv[1],"--launch")) {
        if (getuid()!=501 || geteuid()!=501) return 2;
        char *args[]={argv[2],NULL};
        pid_t child=0;
        int error=posix_spawn(&child,args[0],NULL,NULL,args,environ),status=0;
        if (error) { fprintf(stderr,"setuid child spawn errno=%d\n",error); return 3; }
        pid_t waited;
        do { waited=waitpid(child,&status,0); } while (waited<0 && errno==EINTR);
        return waited==child && WIFEXITED(status) ? WEXITSTATUS(status) : 4;
    }
    if (argc!=1) return 2;
    uid_t real=getuid(),effective=geteuid();
    int passed=real==501 && effective==0;
    printf("{\"uid\":%u,\"euid\":%u,\"passed\":%s}\n",
        (unsigned)real,(unsigned)effective,passed?"true":"false");
    return passed?0:1;
}
