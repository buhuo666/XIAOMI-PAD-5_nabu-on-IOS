#ifndef NABU_JAILBREAK_FS_PROBE_H
#define NABU_JAILBREAK_FS_PROBE_H

/* Returns 0 only when all target checks ran and passed; 2 means checks were
 * unavailable on this host. The JSON report distinguishes skipped from passed.
 * Call after the persistent prefix is mounted, before configuring packages. */
int nabu_jailbreak_fs_probe(const char *lower_prefix, const char *upper_prefix,
    const char *output_path);

/* Call before UIApplicationMain. -1 means ordinary application arguments;
 * otherwise return this value from main. Used for process-owned fcntl locks. */
int nabu_jailbreak_fs_probe_child(int argc, char **argv);

#endif
