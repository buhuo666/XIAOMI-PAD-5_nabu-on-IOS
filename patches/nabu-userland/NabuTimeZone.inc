/* Correct the shipped US/Pacific default once; retain later user choices. */
static int
nabu_fix_timezone(void)
{
    const char *marker = "/private/var/db/timezone/nabu-default-v1";
    const char *local = "/private/var/db/timezone/localtime";
    const char *temporary = "/private/var/db/timezone/localtime.nabu";
    const char *wanted = "/var/db/timezone/zoneinfo/Asia/Shanghai";
    char current[128];
    struct stat st;
    if (stat(marker, &st) == 0) return 1;
    ssize_t size = readlink(local, current, sizeof(current) - 1);
    if (size < 0) return 0;
    current[size] = 0;
    if (!strcmp(current, "/var/db/timezone/zoneinfo/US/Pacific")) {
        unlink(temporary);
        if (symlink(wanted, temporary) != 0 || rename(temporary, local) != 0) return 0;
        printf("NABU TIME: initial timezone US/Pacific -> Asia/Shanghai (UTC+8)\n");
    } else printf("NABU TIME: keeping timezone %s\n", current);
    int fd = open(marker, O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (fd < 0) return 0;
    const char record[] = "default timezone initialized\n";
    int ok = write(fd, record, sizeof(record) - 1) == (ssize_t)(sizeof(record) - 1) && nabu_data_fullfsync(fd) == 0;
    close(fd);
    if (!ok) return 0;
    fd = open("/private/var/db/timezone", O_RDONLY | O_DIRECTORY, 0);
    if (fd < 0) return 0;
    ok = nabu_data_fullfsync(fd) == 0;
    close(fd);
    return ok;
}
