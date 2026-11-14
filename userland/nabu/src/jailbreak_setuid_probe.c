#include <stdio.h>
#include <unistd.h>

int main(void) {
    uid_t real=getuid(),effective=geteuid();
    int passed=real==501 && effective==0;
    printf("{\"uid\":%u,\"euid\":%u,\"passed\":%s}\n",
        (unsigned)real,(unsigned)effective,passed?"true":"false");
    return passed?0:1;
}
