// SPDX-License-Identifier: MIT
#pragma once
#include <cstddef>
#include <cstdint>

namespace NabuTexturePattern {
constexpr std::size_t Width = 256, Height = 256, RowBytes = 1280;
constexpr std::size_t FrameCount = 64, Prefix = 256, Suffix = 256;
constexpr std::size_t StorageBytes = Prefix + RowBytes * Height + Suffix;
constexpr uint8_t Guard = 0x6c;
struct Pixel { uint8_t b, g, r, a; };
static_assert(sizeof(Pixel) == 4, "Packed BGRA input");

inline Pixel expected(std::size_t x, std::size_t y, std::size_t frame) {
    if (y < 16 && x < 192)
        return (frame >> (x / 32)) & 1 ? Pixel{0, 255, 0, 255} : Pixel{255, 0, 0, 255};
    const std::size_t phase = frame % 32;
    const std::size_t left = 8 * (phase <= 16 ? phase : 32 - phase);
    if (x >= left && x < left + 128 && y >= 64 && y < 192) return {255, 0, 255, 255};
    return {uint8_t(x + frame * 3), uint8_t(y + frame * 5), uint8_t((x ^ y) + frame * 7), 255};
}
} // namespace NabuTexturePattern
