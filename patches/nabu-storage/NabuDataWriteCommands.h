// SPDX-License-Identifier: BSD-2-Clause-Patent
// Include after NabuLogWriteCommands.h. Only the installed Data window is writable.
#pragma once
#include "NabuDataContract.h"

static bool gNabuDataWriteOpen;
static uint64_t gNabuDataFirst;

static bool nabuDataWriteRange(uint64_t lba, uint32_t blocks)
{
  return gNabuDataWriteOpen && blocks && blocks <= kDataMax / 4096 &&
      lba >= gNabuDataFirst && lba - gNabuDataFirst < NABU_DATA_BYTES / 4096 &&
      blocks <= NABU_DATA_BYTES / 4096 - (lba - gNabuDataFirst) &&
      lba <= UINT32_MAX && blocks - 1 <= UINT32_MAX - lba &&
      lba < gHost.blocks && blocks <= gHost.blocks - lba;
}

static bool nabuDataWriteCommandAllowed(uint8_t lun, const uint8_t *cdb,
                                       unsigned length, uint32_t bytes)
{
  if (!cdb || lun || length != 10 || cdb[0] != 0x2a || cdb[1] != 0x08 ||
      cdb[6] || cdb[9] || !bytes || bytes > kDataMax || (bytes & 4095)) return false;
  uint64_t lba = (uint32_t(cdb[2]) << 24) | (uint32_t(cdb[3]) << 16) |
      (uint32_t(cdb[4]) << 8) | cdb[5];
  uint32_t blocks = (uint32_t(cdb[7]) << 8) | cdb[8];
  return blocks == bytes / 4096 && nabuDataWriteRange(lba, blocks);
}

static IOReturn nabuDataWrite4k(uint64_t lba, uint32_t blocks, const void *source)
{
  if (!source || !gHost.lock || !nabuDataWriteRange(lba, blocks)) return kIOReturnBadArgument;
  IOLockLock(gHost.lock);
  IOReturn result = kIOReturnNotReady;
  if (nabuDataWriteRange(lba, blocks) && nabuLogTransportIdleLocked()) {
    uint8_t cdb[10] = {0x2a, 0x08, uint8_t(lba >> 24), uint8_t(lba >> 16),
        uint8_t(lba >> 8), uint8_t(lba), 0, uint8_t(blocks >> 8), uint8_t(blocks), 0};
    memcpy(gHost.virt + kDataOffset, source, blocks * 4096);
    uint32_t scsi = 0;
    result = hostScsiDir(0, cdb, 10, 1, blocks * 4096, 2000000, &scsi);
  }
  IOLockUnlock(gHost.lock);
  return result;
}

static IOReturn nabuDataSync(void)
{
  if (!gNabuDataWriteOpen || !gHost.lock) return kIOReturnNotReady;
  IOLockLock(gHost.lock);
  IOReturn result = kIOReturnNotReady;
  if (nabuLogTransportIdleLocked()) {
    const uint8_t cdb[10] = {0x35};
    uint32_t scsi = 0;
    result = hostScsiDir(0, cdb, 10, 0, 0, 10000000, &scsi);
  }
  IOLockUnlock(gHost.lock);
  return result;
}
