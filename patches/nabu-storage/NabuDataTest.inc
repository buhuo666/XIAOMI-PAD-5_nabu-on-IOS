// Exercises the production byte operations and command gate against simulated UFS.
#include "headers/NabuStoragePolicy.h"
#include "headers/NabuStorageContract.h"
#include "headers/NabuDataIdentity.h"
static uint8_t gScratch[kDataMax];
#include "headers/DataOperations.inc"

static void dataReset()
{
  reset();
  gNabuDataFirst=partitionFirst+NABU_DATA_OFFSET/4096;
  activeSlotFirst=gNabuDataFirst;
  medium.assign(kDataMax*3,0x5a);
  gNabuDataWriteOpen=true;
}
static void dataChecksum(uint8_t *b)
{
  uint64_t s1=0,s2=0;
  for (unsigned i=8;i<4096;i+=4) {s1+=nabuLogLe32(b+i);s2+=s1;}
  uint64_t c1=UINT32_MAX-(s1+s2)%UINT32_MAX,c2=UINT32_MAX-(s1+c1)%UINT32_MAX;
  nabuLogPut64(b,(c2<<32)|c1);
}
static void testData()
{
  std::array<uint8_t,4096> super={};
  memcpy(super.data()+32,"NXSB",4);nabuLogPut32(super.data()+36,4096);
  nabuLogPut64(super.data()+40,NABU_DATA_BYTES/4096);
  memcpy(super.data()+72,nabu_data_uuid,16);dataChecksum(super.data());
  assert(nabuDataIdentity(super.data()));
  for (unsigned offset:{32,36,40,72,100,4095}) {
    auto corrupt=super;corrupt[offset]^=1;assert(!nabuDataIdentity(corrupt.data()));
  }
  auto wrong=super;wrong[72]^=1;dataChecksum(wrong.data());assert(!nabuDataIdentity(wrong.data()));
  dataReset();
  std::vector<uint8_t> payload(kDataMax+512,0xab),actual(payload.size());
  assert(nabu_storage_writable(2) && !nabu_storage_writable(0) && !nabu_storage_writable(1));
  assert(nabu_storage_size(2)==NABU_DATA_BYTES && !nabu_storage_size(3));
  auto saved=medium;
  assert(nabu_storage_write(0,0,payload.data(),4096)==EROFS);
  assert(nabu_storage_write(1,0,payload.data(),4096)==EROFS);
  assert(nabu_storage_write(2,NABU_DATA_BYTES-1,payload.data(),2)==EINVAL);
  assert(nabu_storage_write(2,UINT64_MAX,payload.data(),1)==EINVAL);
  assert(medium==saved && !diskWrites);
  assert(nabu_storage_write(2,512,payload.data(),payload.size())==0);
  assert(nabu_storage_read(2,512,actual.data(),actual.size())==0 && actual==payload);
  assert(std::all_of(medium.begin(),medium.begin()+512,[](uint8_t b){return b==0x5a;}));
  assert(std::all_of(medium.begin()+512+payload.size(),medium.end(),[](uint8_t b){return b==0x5a;}));
  assert(nabu_storage_sync(2)==0 && syncs==1);
  assert(!nabuDataWriteRange(gNabuDataFirst-1,1));
  assert(!nabuDataWriteRange(gNabuDataFirst+NABU_DATA_BYTES/4096,1));
  assert(!nabuDataWriteRange(gNabuDataFirst+NABU_DATA_BYTES/4096-1,2));
  assert(!nabuDataWriteRange(slotFirst,1));
  // Last Data block is writable; the following log reservation is untouched.
  activeSlotFirst=gNabuDataFirst+NABU_DATA_BYTES/4096-1;medium.assign(8192,0x33);
  assert(nabu_storage_write(2,NABU_DATA_BYTES-512,payload.data(),512)==0);
  assert(std::all_of(medium.begin()+4096,medium.end(),[](uint8_t b){return b==0x33;}));
  for (unsigned fault=0;fault<4;++fault) {
    dataReset();auto before=medium;
    if(fault==0)poisonOnLock=true;
    if(fault==1)fatalOnLock=true;
    if(fault==2)busyOnLock=true;
    if(fault==3)failWrite=1;
    assert(nabu_storage_write(2,0,payload.data(),4096)==EIO);
    assert(medium==before);
  }
  dataReset();failSync=1;assert(nabu_storage_sync(2)==EIO);
  dataReset();gNabuDataWriteOpen=false;
  assert(!nabu_storage_size(2) && nabu_storage_write(2,0,payload.data(),4096)==EROFS);
  assert(!diskWrites && !syncs);
  puts("PASS Data: NXSB identity/checksum, explicit enable, system/log exclusion, 512-byte RMW, chunk crossing, last block, FUA/flush and transport errors");
}
