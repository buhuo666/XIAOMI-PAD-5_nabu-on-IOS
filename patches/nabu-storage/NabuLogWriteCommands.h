// SPDX-License-Identifier: BSD-2-Clause-Patent
// Include before RootCommands.h inside the transport namespace. This adds one
// selected log-slot capability; no generic Data/store write API is restored.
#pragma once
#include "NabuLogFormat.h"

static bool gNabuLogWriteOpen;
static uint64_t gNabuLogWriteFirst, gNabuLogWriteBlocks;
static IOReturn hostScsiDir(uint8_t, const uint8_t *, unsigned, unsigned,
                          uint32_t, uint32_t, uint32_t *);

static bool nabuLogWriteRange(uint64_t lba, uint32_t blocks)
{
  return gNabuLogWriteOpen && blocks && blocks <= kNabuLogPayloadMax / kNabuLogBlock &&
      lba >= gNabuLogWriteFirst && lba - gNabuLogWriteFirst < gNabuLogWriteBlocks &&
      blocks <= gNabuLogWriteBlocks - (lba - gNabuLogWriteFirst) &&
      lba <= UINT32_MAX && blocks - 1 <= UINT32_MAX - lba &&
      lba < gHost.blocks && blocks <= gHost.blocks - lba;
}

static bool nabuLogWriteWindowOpen(uint64_t slotFirst, uint32_t extentBlocks = kNabuLogSlotBlocks)
{
  if (gNabuLogWriteOpen || !slotFirst || slotFirst > UINT32_MAX ||
      !extentBlocks || extentBlocks % kNabuLogSlotBlocks ||
      extentBlocks > kNabuLogSlots * kNabuLogSlotBlocks ||
      slotFirst >= gHost.blocks || extentBlocks > gHost.blocks - slotFirst ||
      extentBlocks - 1 > UINT32_MAX - slotFirst) return false;
  // Block zero is an immutable host-created manifest.
  gNabuLogWriteFirst = slotFirst + 1;
  gNabuLogWriteBlocks = extentBlocks - 1;
  gNabuLogWriteOpen = true;
  return true;
}
static void nabuLogWriteWindowClose(void) { gNabuLogWriteOpen = false; }

// RootCommands hostScsiDir must call this for direction 1 before hostClearUcd.
// The exact WRITE(10), LUN, FUA, reserved fields and transfer length all matter.
static bool nabuLogWriteCommandAllowed(uint8_t lun, const uint8_t *cdb,
                                       unsigned length, uint32_t bytes)
{
  if (!cdb || lun || length != 10 || cdb[0] != 0x2a || cdb[1] != 0x08 ||
      cdb[6] || cdb[9] || !bytes || bytes > kNabuLogPayloadMax || (bytes & 4095)) return false;
  uint64_t lba = (uint32_t(cdb[2]) << 24) | (uint32_t(cdb[3]) << 16) |
      (uint32_t(cdb[4]) << 8) | cdb[5];
  uint32_t blocks = (uint32_t(cdb[7]) << 8) | cdb[8];
  return blocks == bytes / kNabuLogBlock && nabuLogWriteRange(lba, blocks);
}

// Must be called with the transport lock held, BEFORE touching any DMA byte.
static bool nabuLogTransportIdleLocked(void)
{
  if (!gHost.ready || gHost.poisoned) return false;
  if (read32(gHost.hc, 0x58) || read32(gHost.hc, 0x78) ||
      (read32(gHost.hc, 0x20) & kUfsFatalStatus)) {
    gHost.poisoned = true;
    gHost.ready = false;
    return false;
  }
  return true;
}

static IOReturn nabuLogWrite4k(uint8_t lun, uint64_t lba, uint32_t blocks, const void *source)
{
  if (lun || !source || !gHost.lock || !nabuLogWriteRange(lba, blocks)) return kIOReturnBadArgument;
  IOLockLock(gHost.lock);
  IOReturn result = kIOReturnNotReady;
  // Revalidate after acquiring the lock: a preceding read can quarantine DMA
  // while this writer was waiting for it. Never copy into quarantined storage.
  if (nabuLogWriteRange(lba, blocks) && nabuLogTransportIdleLocked()) {
    uint8_t cdb[10] = {0x2a, 0x08, uint8_t(lba >> 24), uint8_t(lba >> 16),
        uint8_t(lba >> 8), uint8_t(lba), 0, uint8_t(blocks >> 8), uint8_t(blocks), 0};
    memcpy(gHost.virt + kDataOffset, source, blocks * kNabuLogBlock);
    gRootDiagnostic.lba = lba;
    uint32_t scsi = 0;
    result = hostScsiDir(0, cdb, 10, 1, blocks * kNabuLogBlock, 2000000, &scsi);
  }
  IOLockUnlock(gHost.lock);
  return result;
}

static IOReturn nabuLogSync(void)
{
  if (!gNabuLogWriteOpen || !gHost.lock) return kIOReturnNotReady;
  IOLockLock(gHost.lock);
  IOReturn result = kIOReturnNotReady;
  if (gNabuLogWriteOpen && nabuLogTransportIdleLocked()) {
    const uint8_t cdb[10] = {0x35};
    uint32_t scsi = 0;
    result = hostScsiDir(0, cdb, 10, 0, 0, 10000000, &scsi);
  }
  IOLockUnlock(gHost.lock);
  return result;
}
