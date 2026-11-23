// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include "NabuBacklightRemapData.h"

namespace NabuBrightness {
static const uint32_t kOne = 65536;
static const uint32_t kMinNits = 2 * kOne;
static const uint32_t kMaxNits = 500 * kOne;
// Active Android LinearSpline: 2 nits -> 0.005376344 (= 1/186), 500 -> 1.
// Round the normalized request to the panel's 0..2047 software level.
inline uint32_t indexFromNits(uint32_t nits) {
    if (!nits) return 0;
    if (nits <= kMinNits) return 11;
    if (nits >= kMaxNits) return 2047;
    const uint64_t denominator = uint64_t(186) * 498 * kOne;
    const uint64_t numerator = uint64_t(2047) * (uint64_t(498) * kOne + uint64_t(nits - kMinNits) * 185);
    return uint32_t((numerator + denominator / 2) / denominator);
}
inline uint16_t levelFromNits(uint32_t nits) {
    return uint16_t(nabu_backlight_remap[indexFromNits(nits)]);
}
inline uint32_t nitsFromIndex(uint32_t index) {
    if (!index) return 0;
    if (index <= 11) return kMinNits;
    if (index >= 2047) return kMaxNits;
    const uint64_t denominator = uint64_t(2047) * 185;
    const uint64_t numerator = uint64_t(index * 186 - 2047) * 498 * kOne;
    return kMinNits + uint32_t((numerator + denominator / 2) / denominator);
}
inline uint32_t nitsFromLevel(uint16_t level) {
    if (!level) return 0;
    if (level == 2047) return kMaxNits;
    uint32_t lo = 0, hi = 2047;
    while (lo < hi) {
        uint32_t mid = (lo + hi) / 2;
        if (nabu_backlight_remap[mid] < level) lo = mid + 1;
        else hi = mid;
    }
    if (lo && nabu_backlight_remap[lo] - level > level - nabu_backlight_remap[lo - 1]) --lo;
    return nitsFromIndex(lo);
}
inline uint32_t effectiveNits(uint32_t request, uint32_t cap) {
    uint32_t value = request < cap ? request : cap;
    return value < kMaxNits ? value : kMaxNits;
}
}
