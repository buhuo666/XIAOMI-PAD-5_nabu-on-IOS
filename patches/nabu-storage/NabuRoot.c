// SPDX-License-Identifier: BSD-2-Clause-Patent
// BSD block providers for two verified, read-only nabu_system windows.
#include <sys/types.h>
#include <sys/param.h>
#include <sys/conf.h>
#include <sys/buf.h>
#include <sys/disk.h>
#include <sys/errno.h>
#include <sys/systm.h>
#include <sys/proc.h>
#include <sys/uio.h>
#include <sys/vnode.h>
#include <sys/vnode_if.h>
#include <sys/sysctl.h>
#include <os/atomic_private.h>
#include <miscfs/devfs/devfs.h>
#include <pexpert/pexpert.h>
#include <libkern/crypto/sha2.h>
#include "../../iokit/Kernel/nabu_ufs/NabuStorageApi.h"
#include "../../iokit/Kernel/nabu_ufs/NabuStoragePolicy.h"
#include "../../iokit/Kernel/nabu_ufs/NabuStorageContract.h"

extern void loader_log_line(const char *);
static int nabu_major = -1;
static uint32_t nabu_block_size[2] = {4096,4096};
static char nabu_probe_result[192];
static uint8_t nabu_probe_buffer[16384];
static uint32_t nabu_user_status;

static int nabu_user_status_sysctl(struct sysctl_oid *oid, void *arg1 __unused,
                                 int arg2 __unused, struct sysctl_req *req)
{
  int value=(int)os_atomic_load(&nabu_user_status,acquire);
  if (req->newptr && proc_selfpid()!=1) return EPERM;
  int error=sysctl_io_number(req,value,sizeof(value),&value,NULL);
  (void)oid;
  if (error || !req->newptr) return error;
  if (value<0 || ((unsigned)value>>16)>8 || ((unsigned)value&0xffff)>4095) return EINVAL;
  os_atomic_store(&nabu_user_status,(uint32_t)value,release);
  return 0;
}
SYSCTL_PROC(_kern,OID_AUTO,nabu_userland_stage,CTLTYPE_INT|CTLFLAG_RW|CTLFLAG_LOCKED,
    NULL,0,nabu_user_status_sysctl,"I","PID1 bootstrap phase and errno");

uint32_t nabu_userland_status(void)
{ return os_atomic_load(&nabu_user_status,acquire); }

/* Retain the first PID1 setup failure through shutdown and the later return
 * report. Immutable after publication; readers never see a partial string. */
static unsigned nabu_failure_state;
static char nabu_failure_text[192];
static int nabu_user_failure_sysctl(struct sysctl_oid *oid __unused,
    void *arg1 __unused, int arg2 __unused, struct sysctl_req *req)
{
  char text[sizeof(nabu_failure_text)];
  if (!req->newptr || proc_selfpid()!=1) return EPERM;
  if (!req->newlen || req->newlen>=sizeof(text)) return EINVAL;
  int error=SYSCTL_IN(req,text,req->newlen);
  if (error) return error;
  for (size_t i=0;i<req->newlen;i++)
    if ((unsigned char)text[i]<32 || (unsigned char)text[i]>126) return EINVAL;
  text[req->newlen]=0;
  if (os_atomic_cmpxchg(&nabu_failure_state,0,1,acq_rel)) {
    memcpy(nabu_failure_text,text,req->newlen+1);
    os_atomic_store(&nabu_failure_state,2,release);
  }
  return 0;
}
SYSCTL_PROC(_kern,OID_AUTO,nabu_userland_failure,CTLTYPE_STRING|CTLFLAG_WR|CTLFLAG_LOCKED,
    NULL,0,nabu_user_failure_sysctl,"A","First PID1 bootstrap failure");

const char *nabu_userland_failure(void)
{ return os_atomic_load(&nabu_failure_state,acquire)==2 ? nabu_failure_text : NULL; }

static int nabu_open(dev_t dev, int flags, int type __unused, proc_t p __unused)
{
  if (nabu_major < 0 || (unsigned)minor(dev) >= 2) return ENXIO;
  return (flags & FWRITE) ? EROFS : 0;
}
static int nabu_close(dev_t dev __unused, int flags __unused, int type __unused, proc_t p __unused)
{ return 0; }

static void nabu_strategy(buf_t bp)
{
  unsigned window = (unsigned)minor(buf_device(bp));
  uint64_t offset = 0, take = 0;
  int error = 0;
  caddr_t mapped;
  buf_setresid(bp, buf_count(bp));
  if (nabu_major < 0 || window >= 2) error = ENXIO;
  else if (!(buf_flags(bp) & B_READ)) error = EROFS;
  else if (buf_blkno(bp) < 0 || !nabuStorageRequest(nabu_storage_size(window),
      (uint64_t)buf_blkno(bp), nabu_block_size[window], buf_count(bp), &offset, &take)) error = EINVAL;
  else if (take && !(error = buf_map(bp, &mapped))) {
    error = nabu_storage_read(window, offset, mapped, take);
    buf_unmap(bp);
    if (!error) buf_setresid(bp, (uint32_t)(buf_count(bp) - take));
  }
  if (error) buf_seterror(bp,error);
  buf_biodone(bp);
}

static int nabu_ioctl(dev_t dev, u_long cmd, caddr_t data, int flags __unused, proc_t p __unused)
{
  unsigned window=(unsigned)minor(dev);
  if (nabu_major < 0 || window >= 2) return ENXIO;
  switch (cmd) {
    case DKIOCGETBLOCKSIZE: *(uint32_t *)data=nabu_block_size[window]; return 0;
    case DKIOCGETPHYSICALBLOCKSIZE: *(uint32_t *)data=4096; return 0;
    case DKIOCSETBLOCKSIZE: {
      uint32_t n=*(uint32_t *)data;
      if (n<512 || n>4096 || (n&(n-1))) return EINVAL;
      nabu_block_size[window]=n; return 0;
    }
    case DKIOCGETBLOCKCOUNT: *(uint64_t *)data=nabu_storage_size(window)/nabu_block_size[window]; return 0;
    case DKIOCISWRITABLE: *(uint32_t *)data=0; return 0;
    case DKIOCGETMAXBLOCKCOUNTREAD: *(uint64_t *)data=131072/nabu_block_size[window]; return 0;
    default: return ENOTTY;
  }
}
static int nabu_psize(dev_t dev)
{ return (unsigned)minor(dev)<2 ? (int)nabu_block_size[minor(dev)] : -1; }
static const struct bdevsw nabu_bdevsw = {
  .d_open=nabu_open, .d_close=nabu_close, .d_strategy=nabu_strategy,
  .d_ioctl=nabu_ioctl, .d_dump=eno_dump, .d_psize=nabu_psize, .d_type=D_DISK,
};

int nabu_root_device(char *name, unsigned name_bytes, int *device, uint32_t *flags)
{
  uint32_t enabled=0;
  if (!PE_parse_boot_argn("nabu-storage",&enabled,sizeof(enabled)) || enabled!=1) return 0;
  if (nabu_storage_prepare()!=0) nabu_storage_finish("UFS/GPT/system-window validation failed");
  if (nabu_major < 0) {
    nabu_major=bdevsw_add(-1,&nabu_bdevsw);
    if (nabu_major < 0) nabu_storage_finish("no BSD block major");
    for (unsigned i=0;i<2;i++) {
      if (!devfs_make_node(makedev(nabu_major,i),DEVFS_BLOCK,UID_ROOT,GID_OPERATOR,0440,
          "nabu_%s",i ? "systemos":"os")) nabu_storage_finish("devfs publication failed");
    }
  }
  uint32_t bootstrap=0;
  if (PE_parse_boot_argn("nabu-bootstrap",&bootstrap,sizeof(bootstrap)) && bootstrap==1) {
    loader_log_line("NABU STORAGE: published windows; bootstrap RAM disk selects initial root\n");
    return 0;
  }
  strlcpy(name,"nabu_os",name_bytes);
  *device=makedev(nabu_major,0); *flags=0;
  loader_log_line("NABU STORAGE: validated OS selected as BSD root\n");
  return 1;
}

void nabu_root_probe_mounted(void)
{
  uint32_t probe=0;
  if (nabu_major < 0 || !PE_parse_boot_argn("nabu-root-probe",&probe,sizeof(probe)) || probe!=1) return;
  vnode_t vp=NULLVP;
  vfs_context_t ctx=vfs_context_kernel();
  int error=vnode_lookup(NABU_PROBE_PATH,0,&vp,ctx);
  SHA256_CTX hash; uint8_t digest[32]; uint64_t offset=0;
  if (!error) {
    struct vnode_attr attr;
    VATTR_INIT(&attr); VATTR_WANTED(&attr,va_data_size);
    error=vnode_getattr(vp,&attr,ctx);
    if (!error && (vnode_vtype(vp)!=VREG || !VATTR_IS_SUPPORTED(&attr,va_data_size) ||
                   attr.va_data_size!=NABU_PROBE_BYTES)) error=EINVAL;
    SHA256_Init(&hash);
    while (!error && offset<NABU_PROBE_BYTES) {
      int count=(int)MIN((uint64_t)sizeof(nabu_probe_buffer),NABU_PROBE_BYTES-offset), resid=0;
      error=vn_rdwr(UIO_READ,vp,(caddr_t)nabu_probe_buffer,count,(off_t)offset,
          UIO_SYSSPACE,IO_NOCACHE,vfs_context_ucred(ctx),&resid,vfs_context_proc(ctx));
      if (!error && resid) error=EIO;
      if (!error) { SHA256_Update(&hash,nabu_probe_buffer,(size_t)count); offset+=(unsigned)count; }
    }
    if (!error) { SHA256_Final(digest,&hash); if (memcmp(digest,nabu_probe_sha256,32)) error=EIO; }
    vnode_put(vp);
  }
  snprintf(nabu_probe_result,sizeof(nabu_probe_result),
      "NABU ROOT PROBE: mounted OS, launchd bytes=%llu sha256=%s errno=%d",
      (unsigned long long)offset,error ? "NOT VERIFIED":"MATCH",error);
  nabu_storage_finish(nabu_probe_result);
}
