// SPDX-License-Identifier: MIT
#pragma once
#include "bridge/NativeMetalObjects.h"
typedef struct NmbRateMap NmbRateMap;
struct NmbRateLayer { const float *horizontal,*vertical; size_t horizontal_count,vertical_count; };
extern "C" {
NmbRateMap *nmb_rate_map_new(NmbDevice *,uint64_t,uint64_t,const NmbRateLayer *,size_t,const char *);
void nmb_rate_map_release(NmbRateMap *);
bool nmb_rate_map_query(const NmbRateMap *,uint32_t,uint64_t,uint64_t [3]);
bool nmb_rate_map_coordinates(const NmbRateMap *,bool,const float [2],uint64_t,float [2]);
bool nmb_rate_map_copy(const NmbRateMap *,NmbBuffer *,uint64_t);
}
