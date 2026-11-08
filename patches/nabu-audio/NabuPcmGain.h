// SPDX-License-Identifier: BSD-2-Clause-Patent
// User-requested24dB native speaker boost; HAL attenuation remains in eighths.
#pragma once
#include <stdint.h>
namespace NabuPcmGain {
static constexpr unsigned BoostDb=24;
// round(10^(24/20)*2^24), and round(10^(-0.125/20)*2^24).
static constexpr uint32_t Maximum=265900954,Step=16537501;
inline uint32_t gain(unsigned below,bool muted) {
    if(muted)return 0;
    uint64_t g=Maximum;
    for(unsigned i=0;i<below;++i)g=(g*Step+(1u<<23))>>24;
    return uint32_t(g);
}
inline int16_t sample(int16_t value,uint32_t g,uint64_t &clipped) {
    int64_t v=int64_t(value)*g/(1<<24);
    if(v>32767) {++clipped;return 32767;}
    if(v< -32768) {++clipped;return -32768;}
    return int16_t(v);
}
}
