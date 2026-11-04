// SPDX-License-Identifier: BSD-2-Clause-Patent
// Include after the validated layout and gNabuPublished are defined. All public
// functions below require gNabuReadLock to be held by the ordinary caller.
#pragma once
#include "NabuLogFormat.h"

enum NabuLogError : uint32_t {
  kNabuLogOk = 0, kNabuLogInvalid = 1, kNabuLogLayout = 2,
  kNabuLogManifest = 3, kNabuLogRead = 4, kNabuLogNotEmpty = 5,
  kNabuLogWrite = 6, kNabuLogSyncFailed = 7, kNabuLogFull = 8,
  kNabuLogState = 9, kNabuLogCaptureLoss = 10,
};
static struct NabuLogWriterState {
  bool attempted, open, ended;
  uint32_t error, slot, nextBlock, finalStatus;
  uint64_t first, sequence, committed, finalLost;
  uint8_t uuid[16];
  SHA256_CTX stream;
} gNabuLogWriter;
static uint8_t gNabuLogHeader[kNabuLogBlock];
static uint8_t gNabuLogPayload[kNabuLogPayloadMax];
static uint8_t gNabuLogScratch[kNabuLogPayloadMax];

static bool nabuLogFail(uint32_t error, bool terminal = true)
{
  if (!gNabuLogWriter.error) gNabuLogWriter.error = error;
  if (terminal) {
    gNabuLogWriter.open = false;
    nabuLogWriteWindowClose();
  }
  return false;
}
static bool nabuLogTargetZero(uint64_t first, uint32_t blocks)
{
  while (blocks) {
    uint32_t take = blocks > kNabuLogPayloadMax / kNabuLogBlock ?
        kNabuLogPayloadMax / kNabuLogBlock : blocks;
    if (hostRead4k(0, first, take, gNabuLogScratch) != kIOReturnSuccess)
      return nabuLogFail(kNabuLogRead);
    if (!nabuLogZero(gNabuLogScratch, size_t(take) * kNabuLogBlock))
      return nabuLogFail(kNabuLogNotEmpty);
    first += take;
    blocks -= take;
  }
  return true;
}
static void nabuLogMakeRecord(unsigned kind, uint32_t bytes, const uint8_t digest[32],
                              uint64_t lost = 0, uint32_t status = 0)
{
  memset(gNabuLogHeader, 0, sizeof(gNabuLogHeader));
  memcpy(gNabuLogHeader, "NBLOGR01", 8);
  nabuLogPut32(gNabuLogHeader + 8, 1);
  nabuLogPut32(gNabuLogHeader + 12, kind);
  nabuLogPut64(gNabuLogHeader + 16, gNabuLogWriter.sequence);
  nabuLogPut64(gNabuLogHeader + 24, gNabuLogWriter.committed);
  nabuLogPut32(gNabuLogHeader + 32, bytes);
  nabuLogPut32(gNabuLogHeader + 36, 1 + (bytes + kNabuLogBlock - 1) / kNabuLogBlock);
  memcpy(gNabuLogHeader + 40, gNabuLogWriter.uuid, 16);
  memcpy(gNabuLogHeader + 56, digest, 32);
  if (kind == kNabuLogEnd) {
    nabuLogPut64(gNabuLogHeader + 88, lost);
    nabuLogPut32(gNabuLogHeader + 96, status);
    nabuLogPut32(gNabuLogHeader + 100, 1U | (lost ? 2U : 0U));
  }
  nabuLogPut32(gNabuLogHeader + 4092, nabuLogCrc(gNabuLogHeader, 4092));
}
static bool nabuLogCommitHeader(uint64_t lba)
{
  if (nabuLogWrite4k(0, lba, 1, gNabuLogHeader) != kIOReturnSuccess)
    return nabuLogFail(kNabuLogWrite);
  if (nabuLogSync() != kIOReturnSuccess) return nabuLogFail(kNabuLogSyncFailed);
  ++gNabuLogWriter.sequence;
  return true;
}

static bool nabuLogStart(unsigned slot)
{
  if (gNabuLogWriter.attempted) return false;
  gNabuLogWriter.attempted = true;
  gNabuLogWriter.slot = slot;
  if (slot >= kNabuLogSlots) return nabuLogFail(kNabuLogInvalid);
  if (!gNabuPublished || gNabuLayout.userdataLast < gNabuLayout.userdataFirst ||
      gNabuLayout.userdataLast >= gHost.blocks ||
      gNabuLayout.userdataLast - gNabuLayout.userdataFirst + 1 != kNabuLogPartitionBytes / kNabuLogBlock)
    return nabuLogFail(kNabuLogLayout);
  // The fixed slot arithmetic is bounded by the already validated partition.
  uint64_t first = gNabuLayout.userdataFirst + kNabuLogReservedOffset / kNabuLogBlock +
      uint64_t(slot) * kNabuLogSlotBlocks;
  if (first <= gNabuLayout.userdataFirst || first > gNabuLayout.userdataLast ||
      kNabuLogSlotBlocks - 1 > gNabuLayout.userdataLast - first ||
      first > UINT32_MAX || kNabuLogSlotBlocks - 1 > UINT32_MAX - first)
    return nabuLogFail(kNabuLogLayout);
  if (hostRead4k(0, first, 1, gNabuLogHeader) != kIOReturnSuccess)
    return nabuLogFail(kNabuLogRead);
  if (!nabuLogManifestValid(gNabuLogHeader, slot)) return nabuLogFail(kNabuLogManifest);
  memcpy(gNabuLogWriter.uuid, gNabuLogHeader + 56, 16);
  gNabuLogWriter.first = first;
  // The host checked this before preparation. Recheck now before claiming it,
  // including records left by a torn earlier boot whose BEGIN is still zero.
  if (!nabuLogTargetZero(first + 1, kNabuLogSlotBlocks - 1)) return false;
  if (!nabuLogWriteWindowOpen(first)) return nabuLogFail(kNabuLogLayout);
  SHA256_Init(&gNabuLogWriter.stream);
  SHA256_CTX empty = gNabuLogWriter.stream;
  uint8_t digest[32];
  SHA256_Final(digest, &empty);
  gNabuLogWriter.nextBlock = 1;
  nabuLogMakeRecord(kNabuLogBegin, 0, digest);
  if (!nabuLogCommitHeader(first + 1)) return false;
  gNabuLogWriter.nextBlock = 2;
  gNabuLogWriter.open = true;
  return true;
}

static bool nabuLogAppend(const void *data, uint32_t bytes)
{
  if (!gNabuLogWriter.open) return false;
  if (!data || !bytes || bytes > kNabuLogPayloadMax)
    return nabuLogFail(kNabuLogInvalid, false);
  uint32_t payloadBlocks = (bytes + kNabuLogBlock - 1) / kNabuLogBlock;
  uint32_t recordBlocks = 1 + payloadBlocks;
  if (gNabuLogWriter.nextBlock >= kNabuLogSlotBlocks ||
      recordBlocks >= kNabuLogSlotBlocks - gNabuLogWriter.nextBlock)
    return nabuLogFail(kNabuLogFull, false); // Keep the final block for END.
  if (bytes > UINT64_MAX - gNabuLogWriter.committed || gNabuLogWriter.sequence == UINT64_MAX)
    return nabuLogFail(kNabuLogInvalid, false);
  uint64_t lba = gNabuLogWriter.first + gNabuLogWriter.nextBlock;
  if (!nabuLogTargetZero(lba, recordBlocks)) return false;
  memset(gNabuLogPayload, 0, payloadBlocks * kNabuLogBlock);
  memcpy(gNabuLogPayload, data, bytes);
  SHA256_CTX payload;
  uint8_t digest[32];
  SHA256_Init(&payload); SHA256_Update(&payload, gNabuLogPayload, bytes); SHA256_Final(digest, &payload);
  nabuLogMakeRecord(kNabuLogData, bytes, digest);
  if (nabuLogWrite4k(0, lba + 1, payloadBlocks, gNabuLogPayload) != kIOReturnSuccess)
    return nabuLogFail(kNabuLogWrite);
  if (nabuLogSync() != kIOReturnSuccess) return nabuLogFail(kNabuLogSyncFailed);
  if (!nabuLogCommitHeader(lba)) return false;
  SHA256_Update(&gNabuLogWriter.stream, gNabuLogPayload, bytes);
  gNabuLogWriter.committed += bytes;
  gNabuLogWriter.nextBlock += recordBlocks;
  return true;
}

static bool nabuLogEnd(uint64_t lost, uint32_t status)
{
  if (!gNabuLogWriter.open) return false;
  if (gNabuLogWriter.nextBlock >= kNabuLogSlotBlocks || gNabuLogWriter.sequence == UINT64_MAX)
    return nabuLogFail(kNabuLogState);
  uint64_t lba = gNabuLogWriter.first + gNabuLogWriter.nextBlock;
  if (!nabuLogTargetZero(lba, 1)) return false;
  if (!status) status = gNabuLogWriter.error;
  if (lost && !status) status = kNabuLogCaptureLoss;
  SHA256_CTX stream = gNabuLogWriter.stream;
  uint8_t digest[32];
  SHA256_Final(digest, &stream);
  nabuLogMakeRecord(kNabuLogEnd, 0, digest, lost, status);
  if (!nabuLogCommitHeader(lba)) return false;
  ++gNabuLogWriter.nextBlock;
  gNabuLogWriter.finalStatus = status;
  gNabuLogWriter.finalLost = lost;
  gNabuLogWriter.ended = true;
  gNabuLogWriter.open = false;
  nabuLogWriteWindowClose();
  return true;
}

static bool nabuLogIsOpen(void) { return gNabuLogWriter.open; }
static bool nabuLogHasEnded(void) { return gNabuLogWriter.ended; }
static uint64_t nabuLogCommittedBytes(void) { return gNabuLogWriter.committed; }
static uint64_t nabuLogCommittedRecords(void) { return gNabuLogWriter.sequence; }
static uint32_t nabuLogLastError(void) { return gNabuLogWriter.error; }
static uint32_t nabuLogFinalStatus(void) { return gNabuLogWriter.finalStatus; }
static uint64_t nabuLogFinalLost(void) { return gNabuLogWriter.finalLost; }
