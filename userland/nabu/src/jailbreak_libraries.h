#ifndef NABU_JAILBREAK_LIBRARIES_H
#define NABU_JAILBREAK_LIBRARIES_H
#include <string.h>

/* Compatibility libraries and the tweak loader share the dyld list. */
static inline int nabu_jailbreak_has_library(const char *list,const char *library) {
    if (!list) return 0;
    size_t wanted=strlen(library);
    while (*list) {
        const char *end=strchr(list,':');
        size_t length=end?(size_t)(end-list):strlen(list);
        if (length==wanted && !memcmp(list,library,length)) return 1;
        if (!end) break;
        list=end+1;
    }
    return 0;
}
#endif
