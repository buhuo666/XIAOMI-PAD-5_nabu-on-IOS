// SPDX-License-Identifier: BSD-2-Clause-Patent
// Load the original 20F66 APFS closure after VFS initialization.
#include <sys/types.h>
#include <sys/param.h>
#include <sys/mount.h>
#include <sys/mount_internal.h>
#include <sys/sysctl.h>
#include <sys/systm.h>
#include <pexpert/pexpert.h>
#include <mach/kern_return.h>

extern kern_return_t OSKextLoadKextWithIdentifier(const char *);
extern struct vfsops apfs_vfsops; // HakiOS reader, kept for the existing bootstrap.
extern int nabu_data_device_path(char *, unsigned);

static int nabu_data_device_sysctl SYSCTL_HANDLER_ARGS
{
    char path[64];
    int error=nabu_data_device_path(path,sizeof(path));
    if (error) return error;
    return sysctl_handle_string(oidp,path,sizeof(path),req);
}
SYSCTL_PROC(_kern,OID_AUTO,nabu_data_device,CTLTYPE_STRING|CTLFLAG_RD|CTLFLAG_LOCKED,
    0,0,nabu_data_device_sysctl,"A","BSD path of the persistent APFS Data volume");

static int nabu_apfs_legacy_renamed;
static int nabu_apfs_load_status=-1;
static int nabu_apfs_registered;
SYSCTL_INT(_kern,OID_AUTO,nabu_apfs_legacy_renamed,CTLFLAG_RD|CTLFLAG_LOCKED,
    &nabu_apfs_legacy_renamed,0,"HakiOS bootstrap reader is registered as apfsro");
SYSCTL_INT(_kern,OID_AUTO,nabu_apfs_load_status,CTLFLAG_RD|CTLFLAG_LOCKED,
    &nabu_apfs_load_status,0,"Original 20F66 APFS load status");
SYSCTL_INT(_kern,OID_AUTO,nabu_apfs_registered,CTLFLAG_RD|CTLFLAG_LOCKED,
    &nabu_apfs_registered,0,"Original APFS VFS registration observed");

void nabu_apfs_prepare_vfs(void)
{
    uint32_t enabled=0;
    if (!PE_parse_boot_argn("nabu-native-apfs",&enabled,sizeof(enabled)) || enabled!=1) return;
    // Reserve the original name and type for Apple's driver. The bootstrap
    // reader remains available while native Data integration is qualified.
    for (int i=0;i<maxvfsslots && vfsconf[i].vfc_vfsops;i++)
        if (vfsconf[i].vfc_typenum==63) panic("NABU APFS: bootstrap type 63 occupied");
    for (int i=0;i<maxvfsslots && vfsconf[i].vfc_vfsops;i++) {
        if (vfsconf[i].vfc_vfsops==&apfs_vfsops) {
            strlcpy(vfsconf[i].vfc_name,"apfsro",sizeof(vfsconf[i].vfc_name));
            vfsconf[i].vfc_typenum=63;
            nabu_apfs_legacy_renamed=1;
            printf("NABU APFS: bootstrap reader registered separately as apfsro\n");
            return;
        }
    }
    panic("NABU APFS: bootstrap reader missing");
}

// APFS registers from its deferred initialization thread, after kext start has
// returned. Called by vfs_fsadd only after the new VFS has finished vfs_init.
void nabu_apfs_vfs_registered(struct vfstable *entry)
{
    if (nabu_apfs_legacy_renamed && !nabu_apfs_registered && entry &&
        !strcmp(entry->vfc_name,"apfs") && entry->vfc_vfsops!=&apfs_vfsops) {
        nabu_apfs_registered=1;
        printf("NABU APFS: original VFS registered type=%d flags=%#x\n",
            entry->vfc_typenum,entry->vfc_vfsflags);
    }
}

void nabu_apfs_load(void)
{
    if (!nabu_apfs_legacy_renamed) return;
    printf("NABU APFS: loading original com.apple.filesystems.apfs\n");
    nabu_apfs_load_status=OSKextLoadKextWithIdentifier("com.apple.filesystems.apfs");
    mount_list_lock();
    for (struct vfstable *entry=vfsconf;entry;entry=entry->vfc_next) {
        nabu_apfs_vfs_registered(entry);
    }
    mount_list_unlock();
    printf("NABU APFS: load-status=%#x registered=%d (registration may be deferred)\n",
        nabu_apfs_load_status,nabu_apfs_registered);
    if (!nabu_apfs_load_status) {
        kern_return_t data_status=OSKextLoadKextWithIdentifier("org.nabu.driver.DataBlock");
        printf("NABU DATA BLOCK: kext load-status=%#x\n",data_status);
    }
}
