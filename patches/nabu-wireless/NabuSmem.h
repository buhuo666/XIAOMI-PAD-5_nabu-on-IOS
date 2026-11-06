// SPDX-License-Identifier: BSD-2-Clause-Patent
// Qualcomm SMEM v12 wire format; Linux drivers/soc/qcom/smem.c.
#pragma once
#include <stdint.h>
#include <stddef.h>

struct NabuSmemItem { uint32_t offset, size; };

struct NabuSmem {
    const volatile uint8_t *data;
    uint32_t length;

    uint16_t u16(uint32_t at) const {
        return (uint16_t)data[at] | (uint16_t)data[at + 1] << 8;
    }
    uint32_t u32(uint32_t at) const {
        return (uint32_t)u16(at) | (uint32_t)u16(at + 2) << 16;
    }
    bool span(uint32_t at, uint32_t bytes) const {
        return at <= length && bytes <= length - at;
    }
    bool partition(uint16_t host, uint32_t *offset, uint32_t *cacheline) const {
        if (length < 4096) return false;
        uint32_t toc = length - 4096;
        if (u32(toc) != 0x434f5424 || u32(toc + 4) != 1) return false;
        uint32_t count = u32(toc + 8);
        if (count > (4096 - 32) / 48) return false;
        for (uint32_t i = 0; i < count; ++i) {
            uint32_t entry = toc + 32 + 48 * i;
            uint16_t first = u16(entry + 12), second = u16(entry + 14);
            bool match = host == 0xfffe ? first == host && second == host :
                (first == 0 && second == host) || (first == host && second == 0);
            if (!match) continue;
            uint32_t base = u32(entry), bytes = u32(entry + 4);
            if (bytes < 32 || base > toc || bytes > toc - base ||
                u32(base) != 0x54525024 || u32(base + 8) != bytes) return false;
            *offset = base; *cacheline = u32(entry + 16);
            return true;
        }
        return false;
    }
    bool item_in(uint32_t base, uint32_t cacheline, uint16_t id, NabuSmemItem *item) const {
        uint32_t bytes = u32(base + 8), uncached = u32(base + 12), cached = u32(base + 16);
        if (uncached < 32 || uncached > cached || cached > bytes) return false;
        uint32_t at = 32;
        while (at + 16 <= uncached) {
            uint32_t hdr = base + at, size = u32(hdr + 4);
            uint16_t pad = u16(hdr + 8), header_pad = u16(hdr + 10);
            if (u16(hdr) != 0xa5a5 || pad > size || header_pad > uncached - at - 16 ||
                size > uncached - at - 16 - header_pad) return false;
            if (u16(hdr + 2) == id) {
                *item = {hdr + 16 + header_pad, size - pad}; return true;
            }
            at += 16 + header_pad + size;
        }
        if (!cacheline || (cacheline & (cacheline - 1)) || cacheline > bytes) return false;
        uint32_t header_size = (16 + cacheline - 1) & ~(cacheline - 1);
        at = bytes - header_size;
        while (at > cached) {
            uint32_t hdr = base + at, size = u32(hdr + 4);
            uint16_t pad = u16(hdr + 8);
            if (u16(hdr) != 0xa5a5 || pad > size || size > at - cached) return false;
            if (u16(hdr + 2) == id) {
                *item = {hdr - size, size - pad}; return true;
            }
            if (header_size > at - size) return false;
            at -= size + header_size;
        }
        return false;
    }
    bool find(uint16_t id, NabuSmemItem *item) const {
        const uint16_t hosts[] = {1, 0xfffe};
        for (unsigned h = 0; h < 2; ++h) {
            uint32_t base, line;
            if (partition(hosts[h], &base, &line) && item_in(base, line, id, item)) return true;
        }
        return false;
    }
};
