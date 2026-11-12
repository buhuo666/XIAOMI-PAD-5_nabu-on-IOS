#include "ca_context_timer.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

__attribute__((constructor)) static void nabu_ca_context_timer_initialize(void)
{
    const int saved=errno;
    const char *setting=getenv("NABU_CA_CONTEXT_TIMER");
    const char *process=getprogname();
    if(setting&&!strcmp(setting,"1")&&process&&!strcmp(process,"backboardd")){
        const int result=nabu_ca_context_timer_install();
        fprintf(stderr,"NABU CA CONTEXT TIMER: install=%d active=%d build=20F66 process=backboardd; zero-time context commits, native VSync keepalive\n",
                result,nabu_ca_context_timer_active());
    }
    errno=saved;
}
