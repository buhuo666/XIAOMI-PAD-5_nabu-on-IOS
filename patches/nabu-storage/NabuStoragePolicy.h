// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include <stddef.h>

// All offsets are byte offsets inside one published window.
static inline int nabuStorageRange(uint64_t size, uint64_t offset, uint64_t bytes)
{
  return offset <= size && bytes <= size - offset;
}

static inline int nabuStorageRequest(uint64_t size, uint64_t block, uint32_t blockBytes,
                                    uint64_t bytes, uint64_t *offset, uint64_t *take)
{
  if (!offset || !take || blockBytes < 512 || blockBytes > 4096 ||
      (blockBytes & (blockBytes - 1)) || block > UINT64_MAX / blockBytes) return 0;
  *offset = block * blockBytes;
  if (*offset > size) return 0;
  *take = bytes > size - *offset ? size - *offset : bytes;
  return 1;
}
