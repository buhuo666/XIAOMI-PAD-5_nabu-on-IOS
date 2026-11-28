/* SPDX-License-Identifier: MIT */
#pragma once
#include <stdlib.h>
#include <string.h>

/* Metadata only. A command stream owns the index for exactly the lifetime of
 * its resource_ranges array. Equal address/size pairs accumulate the same
 * effective access bits that the old 16-entry search accumulated locally. */
struct tu_resource_range_index {
   uint32_t *slots;
   size_t capacity;
};

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
         ranges[index->slots[slot] - 1].access |= value.access;
         return true;
      }
   }

   /* Grow by unique pairs, not by the number of repeated references. */
   if (!index->capacity || (size_t)count * 2 >= index->capacity) {
      const size_t capacity = index->capacity ? index->capacity * 2 : 64;
      uint32_t *slots = (uint32_t *)calloc(capacity, sizeof(*slots));
      if (!slots)
         return false;
      struct tu_resource_range_index next = {slots, capacity};
      for (uint32_t i = 0; i < count; i++)
         next.slots[tu_resource_range_slot(&next, ranges, ranges[i].iova, ranges[i].size)] = i + 1;
      free(index->slots);
      *index = next;
      slot = tu_resource_range_slot(index, ranges, value.iova, value.size);
   }

   struct tu_resource_range *record = (struct tu_resource_range *)
      util_dynarray_grow(array, struct tu_resource_range, 1);
   if (!record)
      return false;
   *record = value;
   index->slots[slot] = count + 1;
   return true;
}

static inline void
tu_resource_range_index_clear(struct tu_resource_range_index *index)
{
   if (index->slots)
      memset(index->slots, 0, index->capacity * sizeof(*index->slots));
}

static inline void
tu_resource_range_index_finish(struct tu_resource_range_index *index)
{
   free(index->slots);
   *index = {};
}
