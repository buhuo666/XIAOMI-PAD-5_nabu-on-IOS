// SPDX-License-Identifier: BSD-2-Clause-Patent
// Portable on-media helpers for docs/NABU-PERSISTENT-LOG-FORMAT.md.
#pragma once
#include <stdint.h>
#include <stddef.h>

enum : uint32_t {
  kNabuLogBlock = 4096, kNabuLogPayloadMax = 65536,
  kNabuLogSlots = 16, kNabuLogSlotBlocks = 16384,
  kNabuLogBegin = 1, kNabuLogData = 2, kNabuLogEnd = 3,
};
static constexpr uint64_t kNabuLogSlotBytes = 67108864ULL;
static constexpr uint64_t kNabuLogPartitionBytes = 64424509440ULL;
static constexpr uint64_t kNabuLogReservedOffset = 63350767616ULL;
static constexpr uint64_t kNabuLogReservedBytes = 1073741824ULL;

static inline uint32_t nabuLogLe32(const uint8_t *p)
{ return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24); }
static inline uint64_t nabuLogLe64(const uint8_t *p)
{ return uint64_t(nabuLogLe32(p)) | (uint64_t(nabuLogLe32(p + 4)) << 32); }
static inline void nabuLogPut32(uint8_t *p, uint32_t n)
{ for (unsigned i = 0; i < 4; ++i) p[i] = uint8_t(n >> (8 * i)); }
static inline void nabuLogPut64(uint8_t *p, uint64_t n)
{ nabuLogPut32(p, uint32_t(n)); nabuLogPut32(p + 4, uint32_t(n >> 32)); }
static inline bool nabuLogZero(const uint8_t *p, size_t n)
{ for (size_t i = 0; i < n; ++i) if (p[i]) return false; return true; }
static inline bool nabuLogEqual(const uint8_t *p, const uint8_t *q, size_t n)
{ for (size_t i = 0; i < n; ++i) if (p[i] != q[i]) return false; return true; }
static inline uint32_t nabuLogCrc(const uint8_t *p, size_t n)
{
  uint32_t crc = 0xffffffffU;
  for (size_t i = 0; i < n; ++i) {
    crc ^= p[i];
    for (unsigned bit = 0; bit < 8; ++bit)
      crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
  }
  return ~crc;
}
static inline bool nabuLogManifestValid(const uint8_t *p, unsigned slot)
{
  static const uint8_t magic[8] = {'N','A','B','U','L','G','0','1'};
  return slot < kNabuLogSlots && nabuLogEqual(p, magic, 8) &&
      nabuLogLe32(p + 8) == 1 && nabuLogLe32(p + 12) == slot &&
      nabuLogLe64(p + 16) == kNabuLogSlotBytes &&
      nabuLogLe64(p + 24) == kNabuLogPartitionBytes &&
      nabuLogLe64(p + 32) == kNabuLogReservedOffset &&
      nabuLogLe64(p + 40) == kNabuLogReservedBytes &&
      nabuLogLe32(p + 48) == kNabuLogBlock && nabuLogLe32(p + 52) == kNabuLogPayloadMax &&
      nabuLogZero(p + 112, 4092 - 112) && nabuLogLe32(p + 4092) == nabuLogCrc(p, 4092);
}

// Header validation independent of transport. Payload hashes and the running
// stream digest are additionally checked by the recovering host reader.
static inline bool nabuLogRecordValid(const uint8_t *p, const uint8_t uuid[16],
                                     uint64_t sequence, uint64_t offset)
{
  static const uint8_t magic[8] = {'N','B','L','O','G','R','0','1'};
  uint32_t kind = nabuLogLe32(p + 12), bytes = nabuLogLe32(p + 32);
  uint32_t flags = nabuLogLe32(p + 100), status = nabuLogLe32(p + 96);
  uint64_t lost = nabuLogLe64(p + 88);
  if (!nabuLogEqual(p, magic, 8) || nabuLogLe32(p + 8) != 1 ||
      nabuLogLe64(p + 16) != sequence || nabuLogLe64(p + 24) != offset ||
      !nabuLogEqual(p + 40, uuid, 16) || !nabuLogZero(p + 104, 4092 - 104) ||
      nabuLogLe32(p + 4092) != nabuLogCrc(p, 4092) ||
      nabuLogLe32(p + 36) != 1 + (bytes + uint64_t(kNabuLogBlock - 1)) / kNabuLogBlock)
    return false;
  if (kind == kNabuLogBegin)
    return !sequence && !offset && !bytes && !lost && !status && !flags;
  if (kind == kNabuLogData)
    return sequence && bytes && bytes <= kNabuLogPayloadMax && !lost && !status && !flags;
  if (kind == kNabuLogEnd)
    return sequence && !bytes && (flags & 1U) && !(flags & ~3U) &&
        bool(flags & 2U) == bool(lost) && (!lost || status);
  return false;
}
