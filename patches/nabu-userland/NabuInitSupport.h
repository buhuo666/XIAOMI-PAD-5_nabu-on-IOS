// Diagnostics for the source-built PID1 bootstrap; no persistent writes.
#define NABU_DYLD_CACHE_DIRECTORY "/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld"
#define NABU_DYLD_CACHE_ENV "DYLD_SHARED_CACHE_DIR=" NABU_DYLD_CACHE_DIRECTORY

static const char *nabu_boot_filesystem(void)
{
    int renamed=0;
    size_t size=sizeof(renamed);
    if (sysctlbyname("kern.nabu_apfs_legacy_renamed",&renamed,&size,NULL,0)==0 && renamed)
        return "apfsro";
    return "apfs";
}

static unsigned nabu_phase;

static void nabu_stage(unsigned phase, unsigned error)
{
    int saved = errno;
    unsigned value = (phase << 16) | (error & 0xffff);
    nabu_phase = phase;
    (void)sysctlbyname("kern.nabu_userland_stage", NULL, NULL, &value, sizeof(value));
    errno = saved;
}

static void nabu_failure(const char *what, unsigned error)
{
    int saved = errno;
    char line[192], digits[12];
    const char *prefix = "NABU INIT FAILURE: ";
    size_t n = strlen(prefix), d = 0;
    memcpy(line, prefix, n);
    while (*what && n < sizeof(line) - 40) line[n++] = *what++;
    prefix = " phase="; memcpy(line + n, prefix, strlen(prefix)); n += strlen(prefix);
    line[n++] = '0' + nabu_phase;
    prefix = " errno="; memcpy(line + n, prefix, strlen(prefix)); n += strlen(prefix);
    do { digits[d++] = '0' + error % 10; error /= 10; } while (error);
    while (d) line[n++] = digits[--d];
    line[n] = 0;
    (void)sysctlbyname("kern.nabu_userland_failure", NULL, NULL, line, n);
    errno = saved;
}

/* Optional directories differ between iPhone/iPad system images. Only
 * ENOENT is optional; an existing path must be a directory and bind cleanly. */
static int nabu_bind_optional(const char *from, const char *to)
{
    struct stat st;
    if (stat(to, &st) != 0) {
        if (errno == 2) return 1;
        nabu_failure(to, (unsigned)errno);
        return 0;
    }
    if ((st.st_mode & S_IFMT) != S_IFDIR) {
        errno = 20;
        nabu_failure(to, 20);
        return 0;
    }
    if (mount("bindfs", to, MNT_RDONLY, (void *)from) != 0) {
        nabu_failure(to, (unsigned)errno);
        return 0;
    }
    return 1;
}
