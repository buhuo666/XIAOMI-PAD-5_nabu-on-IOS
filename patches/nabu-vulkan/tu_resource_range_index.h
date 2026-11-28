/* SPDX-License-Identifier: MIT */
#pragma once
#include <stdlib.h>
#include <string.h>
#include <atomic>

struct tu_resource_range_import {
   uint64_t identity, revision;
};

/* Metadata only. A command stream owns the index for exactly the lifetime of
 * its resource_ranges array. Equal address/size pairs accumulate the same
 * effective access bits that the old 16-entry search accumulated locally. */
struct tu_resource_range_index {
   uint32_t *slots;
   size_t capacity;
   /* Stable only until clear/finish. A fresh populated index gets a process-wide
    * identity, so a recycled CS address never matches an old import. Recording
    * is externally synchronized; only identity allocation crosses CS threads. */
   uint64_t identity, revision;
   struct tu_resource_range_import imported[8];
   uint32_t imported_count, imported_next;
};

inline uint64_t
tu_resource_range_next_identity()
{
   static std::atomic<uint64_t> next{1};
   uint64_t value = next.load(std::memory_order_relaxed);
   /* Saturate instead of reusing an identity after wrap. Zero disables memo. */
   while (value != UINT64_MAX) {
      if (next.compare_exchange_weak(value, value + 1,
                                     std::memory_order_relaxed))
         return value;
   }
   return 0;
}

static inline void
tu_resource_range_changed(struct tu_resource_range_index *index)
{
   if (!index->identity || index->revision == UINT64_MAX) {
      index->identity = tu_resource_range_next_identity();
      index->revision = 1;
   } else {
      index->revision++;
   }
}

/* Only successful whole-list imports are remembered. The destination's ranges
 * only grow/union access until reset, so later recording cannot undo coverage. */
static inline bool
tu_resource_range_imported(const struct tu_resource_range_index *index,
                           const struct tu_resource_range_index *source)
{
   if (!source->identity)
      return false;
   for (uint32_t i = 0; i < index->imported_count; i++) {
      if (index->imported[i].identity == source->identity)
         return index->imported[i].revision == source->revision;
   }
   return false;
}

static inline void
tu_resource_range_note_import(struct tu_resource_range_index *index,
                             const struct tu_resource_range_index *source)
{
   if (!source->identity)
      return;
   for (uint32_t i = 0; i < index->imported_count; i++) {
      if (index->imported[i].identity == source->identity) {
         index->imported[i].revision = source->revision;
         return;
      }
   }
   index->imported[index->imported_next] = {source->identity, source->revision};
   index->imported_next = (index->imported_next + 1) % 8;
   if (index->imported_count < 8)
      index->imported_count++;
}

static inline uint64_t
tu_resource_range_hash(uint64_t iova, uint64_t bytes)
{
   uint64_t value = iova ^ (bytes * UINT64_C(0x9e3779b97f4a7c15));
   value = (value ^ (value >> 30)) * UINT64_C(0xbf58476d1ce4e5b9);
   value = (value ^ (value >> 27)) * UINT64_C(0x94d049bb133111eb);
   return value ^ (value >> 31);
}

static inline size_t
tu_resource_range_slot(const struct tu_resource_range_index *index,
                       const struct tu_resource_range *ranges,
                       uint64_t iova, uint64_t bytes)
{
   size_t slot = tu_resource_range_hash(iova, bytes) & (index->capacity - 1);
   while (index->slots[slot]) {
      const struct tu_resource_range *previous = &ranges[index->slots[slot] - 1];
      if (previous->iova == iova && previous->size == bytes)
         break;
      slot = (slot + 1) & (index->capacity - 1);
   }
   return slot;
}

static inline bool
tu_resource_range_index_add(struct tu_resource_range_index *index,
                            struct util_dynarray *array,
                            struct tu_resource_range value)
{
   const uint32_t count = util_dynarray_num_elements(array, struct tu_resource_range);
   struct tu_resource_range *ranges = (struct tu_resource_range *)array->data;
   size_t slot = 0;
   if (index->capacity) {
      slot = tu_resource_range_slot(index, ranges, value.iova, value.size);
      if (index->slots[slot]) {
         struct tu_resource_range *previous = &ranges[index->slots[slot] - 1];
         const uint32_t access = previous->access | value.access;
         if (previous->access != access) {
            previous->access = access;
            tu_resource_range_changed(index);
         }
         return true;
      }
   }

   /* Grow by unique pairs, not by the number of repeated references. */
   if (!index->capacity || (size_t)count * 2 >= index->capacity) {
      const size_t capacity = index->capacity ? index->capacity * 2 : 64;
      uint32_t *slots = (uint32_t *)calloc(capacity, sizeof(*slots));
      if (!slots)
         return false;
      struct tu_resource_range_index next = {};
      next.slots = slots;
      next.capacity = capacity;
      for (uint32_t i = 0; i < count; i++)
         next.slots[tu_resource_range_slot(&next, ranges, ranges[i].iova, ranges[i].size)] = i + 1;
      free(index->slots);
      index->slots = slots;
      index->capacity = capacity;
      slot = tu_resource_range_slot(index, ranges, value.iova, value.size);
   }

   struct tu_resource_range *record = (struct tu_resource_range *)
      util_dynarray_grow(array, struct tu_resource_range, 1);
   if (!record)
      return false;
   *record = value;
   index->slots[slot] = count + 1;
   tu_resource_range_changed(index);
   return true;
}

static inline void
tu_resource_range_index_clear(struct tu_resource_range_index *index)
{
   if (index->slots)
      memset(index->slots, 0, index->capacity * sizeof(*index->slots));
   index->identity = index->revision = 0;
   index->imported_count = index->imported_next = 0;
}

static inline void
tu_resource_range_index_finish(struct tu_resource_range_index *index)
{
   free(index->slots);
   *index = {};
}
