/* Explicit diagnostic boot opt-in. The core object has no constructor. */
#include "ca_frame_trace.h"
#include "ca_trace_marker.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

__attribute__((constructor)) static void nabu_ca_trace_initialize(void)
{
    const char *setting=getenv("NABU_CA_FRAME_TRACE");
    if(!setting||strcmp(setting,"1"))return;
    const char *process=getprogname();
    if(!process||strcmp(process,"backboardd"))return;
    const int saved=errno;
    const int result=nabu_ca_frame_trace_install(nabu_ca_trace_marker);
    fprintf(stderr,"NABU CA FRAME TRACE: install=%d capabilities=%u build=20F66 process=backboardd; bounded snapshots, no internal selection hooks\n",
            result,nabu_ca_frame_trace_capabilities());
    errno=saved;
}
