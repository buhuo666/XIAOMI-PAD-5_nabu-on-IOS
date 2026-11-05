#include "mini.h"

int main(int argc, char **argv, char **envp)
{
    (void)argc; (void)argv; (void)envp;
    int console=open("/dev/console",O_RDWR,0);
    for (int fd=0;fd<3;fd++) dup2(console,fd);
    size_t size=0;
    printf("IGNITION PROBE: querying security.mac.img4.ignition_blob\n");
    int result=sysctlbyname("security.mac.img4.ignition_blob",0,&size,0,0);
    printf("IGNITION PROBE: result=%d errno=%d size=%lu\n",result,errno,(unsigned long)size);
    printf("APFS PROBE: end\n");
    for (;;) usleep(1000000);
}
