/* Mounted by PID1 before seed files or launchd can modify /private/var. */
static int
mount_data_volume(void)
{
    const char *enabled=boot_arg("nabu-data");
    if (!enabled || strcmp(enabled,"1")) return 0;
    if (mount("apfs","/private/var",0,(void *)"/dev/nabu_data")!=0) {
        nabu_failure("mount persistent APFS Data",(unsigned)errno);
        printf("NABU DATA: APFS mount failed errno=%d; launchd will not start\n",errno);
        return -1;
    }
    printf("NABU DATA: /private/var mounted from /dev/nabu_data; existing settings kept\n");
    return 1;
}

static int
nabu_data_boot_record(void)
{
    const char *path="/private/var/db/nabu-boot-count";
    const char *temp="/private/var/db/nabu-boot-count.tmp";
    uint32_t record[2]={0x3144424e,0}; /* NBD1, boot count */
    int fd=open(path,O_RDONLY,0);
    if (fd>=0) {
        ssize_t got=read(fd,record,sizeof(record));
        close(fd);
        if (got!=sizeof(record) || record[0]!=0x3144424e || record[1]==0xffffffffu) return 0;
    } else if (errno!=2) return 0;
    unsigned previous=record[1]++;
    fd=open(temp,O_WRONLY|O_CREAT|O_TRUNC,0600);
    if (fd<0) return 0;
    int ok=write(fd,record,sizeof(record))==sizeof(record) && fsync(fd)==0;
    close(fd);
    if (!ok || rename(temp,path)!=0) return 0;
    fd=open("/private/var/db",O_RDONLY|O_DIRECTORY,0);
    if (fd<0) return 0;
    ok=fsync(fd)==0;
    close(fd);
    if (ok) printf("NABU DATA: boot record previous=%u current=%u fsync=ok\n",previous,record[1]);
    return ok;
}
