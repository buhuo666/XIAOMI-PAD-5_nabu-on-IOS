// SPDX-License-Identifier: BSD-2-Clause-Patent
// Verified system reads and a separately admitted append-only log slot for XNU 8796.
namespace {
#include "RootLayout.h"
RootLayout gNabuLayout;
IOLock *gNabuReadLock;
bool gNabuAttempted, gNabuPublished;
char gNabuResult[256] = "not selected";
char gNabuCause[192];
char gNabuReport[2300];
#include "NabuLogWriter.h"
int nabuLogBeginConfigured(void);

bool nabuContract(const char **why)
{
  if (!findRootLayout(&gNabuLayout,why)) return false;
  const auto &r=gNabuLayout;
  if (r.userdataLast>=gHost.blocks || r.userdataLast<r.userdataFirst ||
      r.userdataLast-r.userdataFirst+1!=NABU_PARTITION_BYTES/4096 ||
      r.manifestStatus || r.windows!=2 || r.imageBytes!=NABU_IMAGE_BYTES) {
    *why="installed partition/manifest contract"; return false;
  }
  for (unsigned i=0;i<2;i++) {
    const auto &actual=r.window[i]; const auto &expected=nabu_windows[i];
    if (strcmp(actual.name,expected.name) || actual.offset!=expected.offset || actual.size!=expected.bytes ||
        memcmp(actual.sha256,expected.image_sha256,32)) {
      *why="installed window contract"; return false;
    }
    if (hostRead4k(0,r.userdataFirst+actual.offset/4096,1,gScratch)!=kIOReturnSuccess) {
      *why="APFS superblock read"; return false;
    }
    SHA256_CTX c; uint8_t hash[32];
    SHA256_Init(&c); SHA256_Update(&c,gScratch,4096); SHA256_Final(hash,&c);
    if (memcmp(hash,expected.superblock_sha256,32) || memcmp(gScratch+32,"NXSB",4) ||
        le32(gScratch+36)!=4096 || le64(gScratch+40)!=expected.bytes/4096) {
      *why="APFS superblock identity/geometry"; return false;
    }
    char line[192];
    snprintf(line,sizeof(line),"NABU STORAGE: %s offset=%llu bytes=%llu superblock SHA256 MATCH\n",
        expected.name,(unsigned long long)actual.offset,(unsigned long long)actual.size);
    loader_log_line(line);
  }
  gNabuReadLock=IOLockAlloc();
  if (!gNabuReadLock) { *why="read lock allocation"; return false; }
  gNabuPublished=true;
  gRootDiagnostic.published=2;
  return true;
}
}

extern "C" int nabu_storage_prepare(void)
{
  if (gNabuPublished) return 0;
  if (gNabuAttempted) return EIO;
  gNabuAttempted=true; gRootDiagnosticEnabled=true;
  const char *why="initializing";
  if (!hostBringUp(&why) || !nabuContract(&why)) {
    strlcpy(gNabuResult,why,sizeof(gNabuResult));
    strlcpy(gNabuCause,why,sizeof(gNabuCause)); return EIO;
  }
  int logError=nabuLogBeginConfigured();
  if (logError) {
    gNabuPublished=false;
    strlcpy(gNabuResult,"prepared append-only log slot could not be opened",sizeof(gNabuResult));
    strlcpy(gNabuCause,gNabuResult,sizeof(gNabuCause));
    return logError;
  }
  strlcpy(gNabuResult,"OS/SystemOS validated; both windows read-only",sizeof(gNabuResult));
  return 0;
}

extern "C" uint64_t nabu_storage_size(unsigned window)
{ return gNabuPublished && window<2 ? nabu_windows[window].bytes : 0; }

extern "C" int nabu_storage_read(unsigned window,uint64_t offset,void *out,uint64_t bytes)
{
  if (!gNabuPublished || window>=2 || (bytes && !out) ||
      !nabuStorageRange(nabu_windows[window].bytes,offset,bytes)) return EINVAL;
  if (!bytes) return 0;
  IOLockLock(gNabuReadLock);
  uint8_t *dst=static_cast<uint8_t *>(out);
  int error=0;
  while (bytes) {
    uint64_t skip=offset&4095, take=bytes;
    if (take>kDataMax-skip) take=kDataMax-skip;
    uint32_t blocks=static_cast<uint32_t>((skip+take+4095)/4096);
    uint64_t lba=gNabuLayout.userdataFirst+nabu_windows[window].offset/4096+offset/4096;
    if (hostRead4k(0,lba,blocks,gScratch)!=kIOReturnSuccess) { error=EIO; break; }
    memcpy(dst,gScratch+skip,static_cast<size_t>(take));
    dst+=take; offset+=take; bytes-=take;
    gRootDiagnostic.reads++;
  }
  if (error) gRootDiagnostic.failures++;
  IOLockUnlock(gNabuReadLock);
  return error;
}

extern "C" void nabu_storage_append_report(void)
{
  if (!gNabuAttempted) return;
  formatUfsRootDiagnostics(gNabuReport,sizeof(gNabuReport),gRootDiagnostic,gNabuResult,"NABU STORAGE REPORT");
  loader_log_line(gNabuReport);
  uint32_t status=nabu_userland_status();
  char userland[128];
  snprintf(userland,sizeof(userland),"NABU USERLAND: phase=%u errno=%u (PID1 reported; phase 7 is exec attempt)\n",
      status>>16,status&0xffff);
  loader_log_line(userland);
  nabu_log_append_report();
  const char *failure=nabu_userland_failure();
  if (failure) { loader_log_line(failure); loader_log_line("\n"); }
  if (gNabuCause[0]) {
    char line[224]; snprintf(line,sizeof(line),"NABU STORAGE CAUSE: %s\n",gNabuCause);
    loader_log_line(line);
  }
}

extern "C" void nabu_storage_finish(const char *result)
{
  if (gNabuResult[0] && strcmp(gNabuResult,result)) {
    // Keep both the transport-specific reason and the caller's outcome.
    char line[320]; snprintf(line,sizeof(line),"NABU STORAGE context: %s\n",gNabuResult);
    loader_log_line(line);
  }
  strlcpy(gNabuResult,result,sizeof(gNabuResult));
  nabu_storage_append_report();
  // A failed command retains its DMA allocation for the remainder of this run.
  // With a completed idle queue, stop further fetches before terminal reporting.
  if (gHost.ready && !gHost.poisoned && !read32(gHost.hc,0x58) && !read32(gHost.hc,0x78)) {
    const char *why=""; (void)hostStopQueue(&why);
  }
  loader_return();
  for (;;) __asm__ volatile("wfe");
}
