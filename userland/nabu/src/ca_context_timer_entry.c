#include "ca_context_timer.h"
#include "ca_frame_trace.h"
#include "ca_trace_marker.h"
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
        const char *trace=getenv("NABU_CA_FRAME_TRACE");
        if(trace&&!strcmp(trace,"1")){
            const int traced=nabu_ca_frame_trace_install(nabu_ca_trace_marker);
            fprintf(stderr,"NABU CA FRAME TRACE: install=%d capabilities=%u build=20F66 process=backboardd; bundled before context timer\n",
                    traced,nabu_ca_frame_trace_capabilities());
        }
        const int result=nabu_ca_context_timer_install();
        fprintf(stderr,"NABU CA CONTEXT TIMER: install=%d active=%d single-free-page=%d slots=%u build=20F66 process=backboardd; zero-time context commits, native VSync keepalive\n",
                result,nabu_ca_context_timer_active(),nabu_ca_single_free_page_active(),nabu_ca_context_timer_slots());
    }
    errno=saved;
}
