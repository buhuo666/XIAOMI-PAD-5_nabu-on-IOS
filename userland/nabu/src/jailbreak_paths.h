#ifndef NABU_JAILBREAK_PATHS_H
#define NABU_JAILBREAK_PATHS_H
#include <stddef.h>

#define NABU_JB_BASE "/private/var/db/nabu-jailbreak"
#define NABU_JB_PREFIX NABU_JB_BASE "/procursus"
#define NABU_JB_TWEAK_RULE "/var/jb/usr/lib/TweakLoader.dylib *"
int nabu_jailbreak_restore_paths(const char **stage);
int nabu_jailbreak_enable_tweaks(char *previous,size_t capacity);
int nabu_jailbreak_restore_tweak_config(const char *previous);

#endif
