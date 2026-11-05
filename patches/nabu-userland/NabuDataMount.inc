/* Mounted by PID1 before seed files or launchd can modify /private/var. */
static int
mount_data_volume(void)
{
    const char *enabled=boot_arg("nabu-data");
    if (!enabled || strcmp(enabled,"1")) return 0;
    char device[64];
    struct stat disk;
    int attempt;
    for (attempt=0;attempt<50;attempt++) {
        size_t length=sizeof(device);
        if (sysctlbyname("kern.nabu_data_device",device,&length,0,0)==0 &&
            stat(device,&disk)==0) break;
        usleep(100000);
    }
    if (attempt==50) {
        int error=errno;
        nabu_failure("find persistent APFS Data",(unsigned)error);
        printf("NABU DATA: volume device unavailable errno=%d\n",error);
        return -1;
    }
    unsigned char args[0x160]={0};
    const char *path=device;
    uint16_t mode=1;
    uint32_t owner=99;
    memcpy(args,&path,sizeof(path));
    memcpy(args+0x10,&mode,sizeof(mode));
    memcpy(args+0x144,&owner,sizeof(owner));
    memcpy(args+0x148,&owner,sizeof(owner));
    if (mount("apfs","/private/var",0,args)!=0) {
        int error=errno;
        nabu_failure("mount persistent APFS Data",(unsigned)error);
        printf("NABU DATA: APFS mount failed errno=%d; launchd will not start\n",error);
        return -1;
    }
    printf("NABU DATA: /private/var mounted from %s; existing settings kept\n",device);
    return 1;
}

static int
nabu_data_fullfsync(int fd)
{
    /* Darwin fcntl(92), F_FULLFSYNC(51): commit and flush to the media. */
    int result=(int)mini_syscall(92,fd,51,0,0,0,0);
    if (result<0) printf("NABU DATA: fullfsync failed errno=%d\n",errno);
    return result;
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
    int ok=write(fd,record,sizeof(record))==sizeof(record) && nabu_data_fullfsync(fd)==0;
    close(fd);
    if (!ok || rename(temp,path)!=0) return 0;
    fd=open("/private/var/db",O_RDONLY|O_DIRECTORY,0);
    if (fd<0) return 0;
    ok=nabu_data_fullfsync(fd)==0;
    close(fd);
    if (ok) printf("NABU DATA: boot record previous=%u current=%u fullfsync=ok\n",previous,record[1]);
    return ok;
}
