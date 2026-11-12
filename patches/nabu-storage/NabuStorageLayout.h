// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include <stddef.h>

// The selected capacity changes Data only. Apple system windows and the final
// 1GiB log reserve retain their existing formats. Legacy media remains valid.
static constexpr uint64_t kNabuGiB = 1073741824ULL;
struct NabuStorageLayout {
  uint64_t partitionBytes, dataOffset, dataBytes, logOffset, logBytes;
  bool dynamic;
};
static NabuStorageLayout gNabuCapacity = {60*kNabuGiB,10*kNabuGiB,49*kNabuGiB,59*kNabuGiB,kNabuGiB,false};

static inline uint64_t nabuLayoutLe64(const uint8_t *p)
{ uint64_t value=0; for(unsigned i=0;i<8;i++) value|=uint64_t(p[i])<<(8*i); return value; }

static inline bool nabuCapacityValid(uint64_t bytes)
{ return bytes>=28*kNabuGiB && bytes%kNabuGiB==0 && bytes/4096<=UINT32_MAX; }

static inline bool nabuReadStorageLayout(const uint8_t *root, uint64_t partitionBytes,
                                         NabuStorageLayout *out)
{
  if(!nabuCapacityValid(partitionBytes)) return false;
  static const uint8_t marker[8]={'N','A','B','U','D','Y','N','2'};
  bool dynamic=true;
  for(unsigned i=0;i<8;i++) if(root[512+i]!=marker[i]) dynamic=false;
  NabuStorageLayout next={partitionBytes,10*kNabuGiB,partitionBytes-11*kNabuGiB,
                         partitionBytes-kNabuGiB,kNabuGiB,dynamic};
  if(dynamic) {
    const uint64_t expected[]={next.partitionBytes,next.dataOffset,next.dataBytes,next.logOffset,next.logBytes};
    for(unsigned i=0;i<5;i++) if(nabuLayoutLe64(root+520+8*i)!=expected[i]) return false;
  } else {
    if(partitionBytes!=60*kNabuGiB) return false;
    // Old SHNGROOT leaves this region empty. Do not treat a damaged v2 marker
    // as authority to reinterpret a new installation as the legacy layout.
    for(unsigned i=512;i<560;i++) if(root[i]) return false;
  }
  *out=next;
  return true;
}
