// SPDX-License-Identifier: BSD-2-Clause-Patent
// Host fixture: production writer + production UFS descriptors/response logic.
// Only hardware, lock scheduling and the disk medium are simulated.
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
#include <array>
#include <vector>
#include <algorithm>
#include <fstream>
#ifdef __APPLE__
#include <CommonCrypto/CommonDigest.h>
#define SHA256_CTX CC_SHA256_CTX
#define SHA256_Init CC_SHA256_Init
#define SHA256_Update(c,p,n) CC_SHA256_Update(c,p,(CC_LONG)(n))
#define SHA256_Final CC_SHA256_Final
#define SHA256(p,n,d) CC_SHA256(p,(CC_LONG)(n),d)
#else
// Use the installed libcrypto one-shot ABI without requiring development
// headers. The host adapter is copyable like XNU's SHA context; production
// digest calls remain in NabuLogWriter.h and expected bytes use libcrypto.
extern "C" unsigned char *SHA256(const unsigned char *, size_t, unsigned char *);
struct SHA256_CTX { std::vector<uint8_t> bytes; };
static void SHA256_Init(SHA256_CTX *c) { c->bytes.clear(); }
static void SHA256_Update(SHA256_CTX *c, const void *p, size_t n)
{ auto b=static_cast<const uint8_t *>(p);c->bytes.insert(c->bytes.end(),b,b+n); }
static void SHA256_Final(uint8_t *out, SHA256_CTX *c) { SHA256(c->bytes.data(),c->bytes.size(),out); }
#endif
#include "headers/RootDiagnostics.h"
#include "headers/TransferPoll.h"
#include "headers/RootTransportLayout.h"
using IOReturn = uint32_t;
constexpr IOReturn kIOReturnSuccess=0, kIOReturnError=0xe00002bc,
  kIOReturnBadArgument=0xe00002c2, kIOReturnIOError=0xe00002ca,
  kIOReturnBusy=0xe00002d5, kIOReturnTimeout=0xe00002d6, kIOReturnNotReady=0xe00002d8;
constexpr unsigned kMicrosecondScale=1;
static UfsRootDiagnostics gRootDiagnostic;
struct Host { uint8_t *virt; uint64_t phys; bool ready, poisoned; uintptr_t hc; void *lock; uint64_t blocks; };
static Host gHost;
alignas(4096) static uint8_t memory[kDmaBytes];
static std::array<uint8_t,kDmaBytes> device;
static std::array<uint32_t,64> registers;
static std::vector<uint8_t> medium(67108864);
struct Operation { unsigned opcode; uint64_t lba; unsigned blocks; };
static std::vector<Operation> operations;
static uint64_t ticks;
static unsigned mmioWrites, releases, diskWrites, syncs, failWrite, failSync;
static bool released, poisonOnLock, fatalOnLock, busyOnLock, partialWrite, lockHeld;
static constexpr uint64_t partitionFirst=108652288, slotFirst=124118784;
static uint64_t activeSlotFirst=slotFirst;
static uint32_t read32(uintptr_t, unsigned at) { return registers.at(at/4); }
static uint32_t be32(const uint8_t *p)
{ return (uint32_t(p[0])<<24)|(uint32_t(p[1])<<16)|(uint32_t(p[2])<<8)|p[3]; }

static void hostWrite(unsigned at, uint32_t value)
{
  ++mmioWrites;
  if(at==0x20) registers[at/4]&=~value;
  else registers.at(at/4)=value;
  if(at!=0x58) return;
  assert(released);released=false;
  registers[0x58/4]=0;
  uint8_t *cmd=device.data()+kUcdOffset, *rsp=cmd+kRspOffset;
  uint8_t opcode=cmd[16];
  uint64_t lba=be32(cmd+18);
  unsigned blocks=(unsigned(cmd[23])<<8)|cmd[24];
  operations.push_back({opcode,lba,blocks});
  memset(rsp,0,512);memcpy(rsp,cmd,32);rsp[0]=0x21;rsp[1]=0;
  memset(rsp+12,0,4);
  *reinterpret_cast<uint32_t *>(device.data()+8)=0;
  if(opcode==0x35) {
    ++syncs;
    if(failSync && syncs==failSync) rsp[7]=2;
    return;
  }
  assert(opcode==0x28 || opcode==0x2a);
  assert(lba>=activeSlotFirst && lba-activeSlotFirst<medium.size()/4096 && blocks<=medium.size()/4096-(lba-activeSlotFirst));
  auto disk=medium.data()+(lba-activeSlotFirst)*4096;
  if(opcode==0x28) memcpy(device.data()+kDataOffset,disk,blocks*4096);
  else {
    ++diskWrites;
    assert(cmd[17]==0x08 && cmd[1]==0x20 && cmd[2]==0);
    if(failWrite && diskWrites==failWrite) {
      if(partialWrite) memcpy(disk,device.data()+kDataOffset,blocks*4096/2);
      rsp[7]=2;
    } else memcpy(disk,device.data()+kDataOffset,blocks*4096);
  }
}
static void cacheCivac(const void *p, size_t n)
{
  auto offset=static_cast<const uint8_t *>(p)-memory;
  assert(offset>=0 && size_t(offset)+n<=device.size());
  memcpy(device.data()+offset,p,n);++releases;released=true;
}
static void cacheInvalidate(const void *p, size_t n)
{
  auto offset=static_cast<const uint8_t *>(p)-memory;
  assert(offset>=0 && size_t(offset)+n<=device.size());
  memcpy(const_cast<void *>(p),device.data()+offset,n);
}
static void clock_interval_to_deadline(uint32_t n, unsigned scale, uint64_t *out) { *out=ticks+uint64_t(n)*scale; }
static uint64_t mach_absolute_time() { return ticks; }
static void IODelay(uint32_t n) { ticks+=n; }
static void IOLockLock(void *)
{
  assert(!lockHeld);lockHeld=true;
  if(poisonOnLock) { gHost.poisoned=true;gHost.ready=false; }
  if(fatalOnLock) registers[0x20/4]=0x20000;
  if(busyOnLock) registers[0x58/4]=1;
}
static void IOLockUnlock(void *) { assert(lockHeld);lockHeld=false; }
static IOReturn recordTransport(IOReturn result, uint32_t ocs)
{ gRootDiagnostic.result=result;gRootDiagnostic.ocs=ocs;return result; }
#include "headers/RootCommands.h"
static struct { uint64_t userdataFirst, userdataLast; } gNabuLayout;
static bool gNabuPublished;
#include "headers/NabuLogWriter.h"

static void manifest(unsigned slot=0,unsigned span=1)
{
  uint8_t *p=medium.data();memset(p,0,4096);memcpy(p,"NABULG01",8);
  nabuLogPut32(p+8,span==1?1:2);nabuLogPut32(p+12,slot);
  nabuLogPut64(p+16,kNabuLogSlotBytes*span);nabuLogPut64(p+24,kNabuLogPartitionBytes);
  nabuLogPut64(p+32,kNabuLogReservedOffset);nabuLogPut64(p+40,kNabuLogReservedBytes);
  nabuLogPut32(p+48,4096);nabuLogPut32(p+52,65536);
  for(unsigned i=0;i<16;++i)p[56+i]=uint8_t(i+1);
  nabuLogPut64(p+72,1793808000);
  for(unsigned i=0;i<32;++i)p[80+i]=uint8_t(0x40+i);
  nabuLogPut32(p+4092,nabuLogCrc(p,4092));
}
static void reset(bool clearDisk=true, unsigned slot=0,unsigned span=1)
{
  activeSlotFirst=slotFirst+uint64_t(slot)*16384;
  if(clearDisk) {medium.assign(kNabuLogSlotBytes*span,0);manifest(slot,span);}
  memset(memory,0xa5,sizeof(memory));device.fill(0);registers.fill(0);
  registers[0x30/4]=15;registers[0x34/4]=1;registers[0x60/4]=1;
  gHost={memory,0x8cb5e9000,true,false,0,reinterpret_cast<void *>(1),124380950};
  gNabuLayout={partitionFirst,124380927};gNabuPublished=true;
  gNabuLogWriter={};gNabuLogWriteOpen=false;gNabuLogWriteFirst=gNabuLogWriteBlocks=0;
  gRootDiagnostic={};ticks=mmioWrites=releases=diskWrites=syncs=failWrite=failSync=0;
  poisonOnLock=fatalOnLock=busyOnLock=partialWrite=released=lockHeld=false;
  operations.clear();
}
static std::array<uint8_t,32> digest(const uint8_t *p, size_t n)
{ std::array<uint8_t,32> result;SHA256(p,n,result.data());return result; }
struct Recovery { uint64_t sequence=0, bytes=0;bool ended=false; };
static Recovery recover()
{
  Recovery r;uint64_t block=1;SHA256_CTX stream;SHA256_Init(&stream);
  while(block<medium.size()/4096) {
    const uint8_t *h=medium.data()+block*4096;
    if(!nabuLogRecordValid(h,medium.data()+56,r.sequence,r.bytes)) break;
    uint32_t kind=nabuLogLe32(h+12),n=nabuLogLe32(h+32),count=nabuLogLe32(h+36);
    if(count>medium.size()/4096-block) break;
    if(kind==kNabuLogData) {
      auto payload=h+4096;auto hash=digest(payload,n);
      if(!nabuLogEqual(hash.data(),h+56,32) || !nabuLogZero(payload+n,(count-1)*4096-n))break;
      SHA256_Update(&stream,payload,n);r.bytes+=n;
    } else {
      SHA256_CTX copy=stream;uint8_t hash[32];SHA256_Final(hash,&copy);
      if(!nabuLogEqual(hash,h+56,32))break;
      if(kind==kNabuLogEnd)r.ended=true;
    }
    ++r.sequence;block+=count;if(r.ended)break;
  }
  return r;
}
static void assertNoDmaChange(const std::array<uint8_t,kDmaBytes> &before,unsigned writes,unsigned releaseCount)
{
  assert(!memcmp(before.data(),memory,sizeof(memory)));
  assert(mmioWrites==writes && releases==releaseCount);
}
static void testCommands()
{
  reset();assert(nabuLogWriteWindowOpen(slotFirst));
  std::array<uint8_t,4096> payload{};payload[0]=42;
  auto before=std::array<uint8_t,kDmaBytes>{};memcpy(before.data(),memory,sizeof(memory));
  for(auto wrong:{slotFirst,uint64_t(0),UINT64_MAX,slotFirst+kNabuLogSlotBlocks})
    assert(nabuLogWrite4k(0,wrong,1,payload.data())!=0);
  assert(nabuLogWrite4k(1,slotFirst+1,1,payload.data())!=0);
  assert(nabuLogWrite4k(0,slotFirst+1,0,payload.data())!=0);
  assert(nabuLogWrite4k(0,slotFirst+1,17,payload.data())!=0);
  assert(nabuLogWrite4k(0,slotFirst+kNabuLogSlotBlocks-1,2,payload.data())!=0);
  assertNoDmaChange(before,0,0);
  for(unsigned mode=0;mode<4;++mode) {
    reset();assert(nabuLogWriteWindowOpen(slotFirst));memcpy(before.data(),memory,sizeof(memory));
    poisonOnLock=mode==0;fatalOnLock=mode==1;busyOnLock=mode==2;
    if(mode==3)registers[0x78/4]=1;
    assert(nabuLogWrite4k(0,slotFirst+1,1,payload.data())!=0);assertNoDmaChange(before,0,0);
  }
  reset();assert(nabuLogWriteWindowOpen(slotFirst));
  uint8_t cdb[10]={0x2a,8,uint8_t((slotFirst+1)>>24),uint8_t((slotFirst+1)>>16),
      uint8_t((slotFirst+1)>>8),uint8_t(slotFirst+1),0,0,1,0};
  uint32_t scsi=0;
  memcpy(before.data(),memory,sizeof(memory));
  for(unsigned mutation=0;mutation<6;++mutation) {
    auto c=std::array<uint8_t,10>{};memcpy(c.data(),cdb,10);
    if(mutation==0)c[0]=0x28;
    if(mutation==1)c[1]=0;
    if(mutation==2)c[6]=1;
    if(mutation==3)c[9]=1;
    if(mutation==4)c[8]=2;
    if(mutation==5)c[2]=0;
    assert(hostScsiDir(0,c.data(),10,1,4096,1000,&scsi)!=0);
  }
  assert(hostScsiDir(1,cdb,10,1,4096,1000,&scsi)!=0);
  assert(hostScsiDir(0,cdb,10,0,0,1000,&scsi)!=0);assertNoDmaChange(before,0,0);
  assert(nabuLogWrite4k(0,slotFirst+1,1,payload.data())==0 && medium[4096]==42);
  assert(nabuLogSync()==0);
  nabuLogWriteWindowClose();memcpy(before.data(),memory,sizeof(memory));
  auto oldWrites=mmioWrites,oldReleases=releases;
  assert(nabuLogWrite4k(0,slotFirst+2,1,payload.data())!=0);assertNoDmaChange(before,oldWrites,oldReleases);
  puts("PASS command gates: bounds/overflow, wrong LUN/CDB, immutable manifest, after-lock poison/fatal/busy, no rejected DMA writes");
}
static void testWriter(const char *dump)
{
  reset();assert(nabuLogStart(0));assert(nabuLogIsOpen());assert(nabuLogCommittedRecords()==1);
  const uint8_t a[]={1,2,3,4,5};std::vector<uint8_t> b(65536);
  for(unsigned i=0;i<b.size();++i)b[i]=uint8_t(i*29);
  operations.clear();assert(nabuLogAppend(a,sizeof(a)));
  std::vector<unsigned> mutating;for(auto op:operations)if(op.opcode!=0x28)mutating.push_back(op.opcode);
  assert((mutating==std::vector<unsigned>{0x2a,0x35,0x2a,0x35}));
  assert(nabuLogAppend(b.data(),uint32_t(b.size())));
  assert(nabuLogEnd(0,0) && nabuLogHasEnded() && !nabuLogIsOpen());
  assert(nabuLogCommittedBytes()==65541 && nabuLogCommittedRecords()==4 && !nabuLogLastError());
  auto r=recover();assert(r.ended && r.bytes==65541 && r.sequence==4);
  if(dump) {std::ofstream out(dump,std::ios::binary);out.write(reinterpret_cast<const char *>(medium.data()),medium.size());assert(out.good());}
  auto saved=medium;reset(false);assert(!nabuLogStart(0) && !diskWrites);assert(medium==saved);
  for(unsigned mutation=0;mutation<6;++mutation) {
    medium=saved;
    uint8_t *h=medium.data()+2*4096;
    if(mutation==0)nabuLogPut64(h+16,99);
    if(mutation==1)nabuLogPut64(h+24,1);
    if(mutation==2)h[40]^=1;
    if(mutation==3)h[104]=1;
    if(mutation==4)medium[3*4096+sizeof(a)]=1;
    if(mutation==5)medium[3*4096]^=1;
    if(mutation<4)nabuLogPut32(h+4092,nabuLogCrc(h,4092));
    r=recover();assert(!r.ended && r.sequence==1 && !r.bytes);
  }
  reset();medium.back()=1;assert(!nabuLogStart(0) && nabuLogLastError()==kNabuLogNotEmpty && !diskWrites);
  for(unsigned mutation=0;mutation<4;++mutation) {
    reset();if(mutation==0)medium[112]=1;
    if(mutation==1)medium[8]=2;
    if(mutation==2)medium[12]=1;
    if(mutation==3)medium[4092]^=1;
    if(mutation<3)nabuLogPut32(medium.data()+4092,nabuLogCrc(medium.data(),4092));
    assert(!nabuLogStart(0) && !diskWrites && nabuLogLastError()==kNabuLogManifest);
  }
  reset();assert(!nabuLogStart(16) && !diskWrites);
  reset();gNabuPublished=false;assert(!nabuLogStart(0) && !diskWrites);
  reset();gNabuLayout.userdataFirst=UINT64_MAX;assert(!nabuLogStart(0) && !diskWrites);
  reset();assert(nabuLogStart(0));gNabuLogWriter.nextBlock=kNabuLogSlotBlocks-3;
  assert(nabuLogAppend(a,sizeof(a)));assert(!nabuLogAppend(a,sizeof(a)));
  assert(nabuLogIsOpen() && nabuLogLastError()==kNabuLogFull && nabuLogEnd(0,0));
  assert(nabuLogLe32(medium.data()+(kNabuLogSlotBlocks-1)*4096+96)==kNabuLogFull);
  reset();assert(nabuLogStart(0));assert(nabuLogEnd(7,0));
  const uint8_t *end=medium.data()+8192;
  assert(nabuLogLe32(end+100)==3 && nabuLogLe32(end+96)==kNabuLogCaptureLoss);
  assert(nabuLogFinalStatus()==kNabuLogCaptureLoss && nabuLogFinalLost()==7);
  reset(true,15);assert(nabuLogStart(15) && nabuLogEnd(0,0));
  assert(nabuLogFinalStatus()==0 && nabuLogFinalLost()==0);
  reset();assert(nabuLogStart(0));auto beforeInvalid=diskWrites;
  assert(!nabuLogAppend(nullptr,1) && !nabuLogAppend(a,0) && !nabuLogAppend(a,65537));
  assert(diskWrites==beforeInvalid && nabuLogIsOpen());
  assert(nabuLogEnd(0,0) && nabuLogFinalStatus()==kNabuLogInvalid);
  puts("PASS writer: full-slot freshness, manifest/reserved CRC, BEGIN/DATA/END hashes, sequence/padding recovery, END reservation and loss flags");
}
static void testFailures()
{
  const uint8_t bytes[]={9,8,7,6};
  for(unsigned phase=0;phase<4;++phase) {
    reset();assert(nabuLogStart(0));diskWrites=syncs=0;
    if(phase==0){failWrite=1;partialWrite=true;}
    if(phase==1)failSync=1;
    if(phase==2){failWrite=2;partialWrite=true;}
    if(phase==3)failSync=2;
    assert(!nabuLogAppend(bytes,sizeof(bytes)) && !nabuLogIsOpen());
    assert(!nabuLogCommittedBytes() && nabuLogCommittedRecords()==1);
    auto saved=medium;unsigned oldWrites=diskWrites,oldSyncs=syncs;
    assert(!nabuLogAppend(bytes,sizeof(bytes)) && !nabuLogEnd(0,0));
    assert(medium==saved && diskWrites==oldWrites && syncs==oldSyncs);
    auto r=recover();assert(!r.ended && r.bytes==(phase==3?sizeof(bytes):0));
    reset(false);assert(!nabuLogStart(0) && !diskWrites);
  }
  reset();failWrite=1;partialWrite=true;assert(!nabuLogStart(0) && !nabuLogIsOpen());
  reset();failSync=1;assert(!nabuLogStart(0) && !nabuLogIsOpen());
  reset();assert(nabuLogStart(0));medium[8192]=1;
  unsigned before=diskWrites;assert(!nabuLogAppend(bytes,sizeof(bytes)));
  assert(diskWrites==before && nabuLogLastError()==kNabuLogNotEmpty);
  reset();assert(nabuLogStart(0));poisonOnLock=true;
  assert(!nabuLogAppend(bytes,sizeof(bytes)) && nabuLogLastError()==kNabuLogRead);
  puts("PASS failures: partial payload/header, both sync stages, torn claim, target reuse, post-read failure, no retry/overwrite");
}
static void testExtent(const char *dump)
{
  reset(true,2,10);
  auto original=std::array<uint8_t,4096>{};memcpy(original.data(),medium.data(),4096);
  assert(nabuLogManifestValid(medium.data(),2,10));
  assert(!nabuLogManifestValid(medium.data(),2,1));
  assert(!nabuLogManifestValid(medium.data(),2,9));
  assert(!nabuLogManifestValid(medium.data(),7,10));
  medium.back()=1;assert(!nabuLogStart(2,10) && !diskWrites);
  medium.back()=0;reset(false,2);
  assert(!nabuLogStart(7,10) && !diskWrites);
  reset(false,2);assert(!nabuLogStart(2,0) && !diskWrites);
  reset(false,2);assert(!nabuLogStart(2,15) && !diskWrites);
  reset(false,2);assert(nabuLogStart(2,10));
  std::array<uint8_t,65536> payload;
  for(unsigned i=0;i<payload.size();++i)payload[i]=uint8_t(i*29);
  const auto first=activeSlotFirst,last=first+10*kNabuLogSlotBlocks;
  assert(!nabuLogWriteRange(first,1) && !nabuLogWriteRange(first-1,1));
  assert(!nabuLogWriteRange(slotFirst,1) && !nabuLogWriteRange(last,1));
  assert(nabuLogWriteRange(first+1,1) && nabuLogWriteRange(last-1,1));
  assert(!nabuLogWriteRange(last-1,2));
  for(unsigned record=0;record<8192;++record)assert(nabuLogAppend(payload.data(),payload.size()));
  assert(nabuLogCommittedBytes()==512ULL*1024*1024);
  assert(nabuLogEnd(0,0) && !nabuLogFinalStatus() && !nabuLogFinalLost());
  assert(!memcmp(original.data(),medium.data(),4096));
  auto r=recover();assert(r.ended && r.bytes==512ULL*1024*1024 && r.sequence==8194);
  if(dump) {std::ofstream out(dump,std::ios::binary);out.write(reinterpret_cast<const char *>(medium.data()),medium.size());assert(out.good());}
  auto writes=diskWrites;assert(!nabuLogStart(2,10) && diskWrites==writes);
  puts("PASS v2 640 MiB extent, exact slot/span binding, far-tail freshness, prior/next extent exclusion, immutable manifest and 512 MiB continuous committed stream");
}
int main(int argc,char **argv)
{
  (void)hostNop;(void)hostQueryRead; // Retained read-only production helpers.
  testCommands();testWriter(argc>1?argv[1]:nullptr);testFailures();
  testExtent(argc>2?argv[2]:nullptr);
  puts("PASS all actual writer/command scenarios; hardware and medium effects simulated");
}
