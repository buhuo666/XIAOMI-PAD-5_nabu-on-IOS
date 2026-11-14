/* Existing exec_inject syntax plus an explicit standalone '*' process token.
 * Configuration is empty at boot. No path or library is enabled implicitly.
 * Included in the kernel and in the differential host checks.
 */
#ifndef NABU_EXEC_INJECTION_H
#define NABU_EXEC_INJECTION_H

#define NABU_EXEC_INJECT_CONFIG_SIZE 4096
#define NABU_EXEC_INJECT_ENV_SIZE 512

static bool
nabu_exec_injection_env(const char *configuration, const char *name,
    size_t namelen, char *env, size_t size)
{
    const char *p = configuration;
    size_t used;
    bool any = false;

    if (*p == 0 || name == NULL) return false;
    used = strlcpy(env, "DYLD_INSERT_LIBRARIES=", size);
    while (*p != 0) {
        const char *library;
        size_t liblen;
        bool matched = false;

        while (*p == ' ' || *p == ';') p++;
        library = p;
        while (*p != 0 && *p != ' ' && *p != ';') p++;
        liblen = (size_t)(p - library);
        while (*p == ' ') {
            const char *word = ++p;
            while (*p != 0 && *p != ' ' && *p != ';') p++;
            size_t wordlen = (size_t)(p - word);
            if (!matched && namelen != 0 && liblen != 0 &&
                ((wordlen == namelen && strncmp(word, name, namelen) == 0) ||
                 (wordlen == 1 && word[0] == '*'))) matched = true;
        }
        /* Preserve the original whole-library capacity rule. Never emit a
         * truncated library path, and still consider later matching groups.
         */
        if (matched && liblen != 0 && used + 1 + liblen < size) {
            if (any) env[used++] = ':';
            memcpy(env + used, library, liblen);
            used += liblen;
            env[used] = 0;
            any = true;
        }
    }
    return any;
}

#endif
