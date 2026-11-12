// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include "NabuDataContract.h"
#include "NabuStorageLayout.h"

static uint32_t nabuDataLe32(const uint8_t *p)
{ return uint32_t(p[0]) | (uint32_t(p[1])<<8) | (uint32_t(p[2])<<16) | (uint32_t(p[3])<<24); }
static uint64_t nabuDataLe64(const uint8_t *p)
{ return uint64_t(nabuDataLe32(p)) | (uint64_t(nabuDataLe32(p+4))<<32); }

static bool nabuDataIdentity(const uint8_t *block)
{
  if (memcmp(block+32,"NXSB",4) || nabuDataLe32(block+36)!=4096 ||
      nabuDataLe64(block+40)!=gNabuCapacity.dataBytes/4096 ||
      memcmp(block+72,nabu_data_uuid,16)) return false;
  uint64_t sum1=0, sum2=0;
  for (unsigned i=8;i<4096;i+=4) {
    sum1=(sum1+nabuDataLe32(block+i))%UINT32_MAX;
    sum2=(sum2+sum1)%UINT32_MAX;
  }
  uint32_t low=UINT32_MAX-(sum1+sum2)%UINT32_MAX;
  uint32_t high=UINT32_MAX-(sum1+low)%UINT32_MAX;
  return nabuDataLe64(block)==(uint64_t(high)<<32|low);
}
