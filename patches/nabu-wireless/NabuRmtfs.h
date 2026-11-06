// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#ifdef KERNEL
#include <libkern/libkern.h>
#else
#include <string.h>
#endif

struct NabuRmtfs {
    struct File { const char *path; uint8_t *data; uint32_t size; bool open; } files[4]{};
    volatile uint8_t *buffer = nullptr;
    uint32_t physical = 0, buffer_size = 0, requests = 0, reads = 0, writes = 0;
    static uint16_t u16(const uint8_t *p) { return (uint16_t)p[0] | (uint16_t)p[1] << 8; }
    static uint32_t u32(const uint8_t *p) { return (uint32_t)u16(p) | (uint32_t)u16(p+2) << 16; }
    static const uint8_t *tlv(const uint8_t *p, unsigned bytes, unsigned type, unsigned &length) {
        for (unsigned at = 7; at + 3 <= bytes;) {
            unsigned size = u16(p + at + 1); if (size > bytes - at - 3) return nullptr;
            if (p[at] == type) { length = size; return p + at + 3; } at += 3 + size;
        }
        return nullptr;
    }
    unsigned answer(const uint8_t *p, unsigned bytes, uint8_t *out) {
        if (bytes < 7 || p[0] != 0 || u16(p+5) != bytes-7) return 0;
        requests++; memset(out, 0, 64); memcpy(out+1, p+1, 4); out[0] = 2;
        unsigned msg = u16(p+3), size = 0, extra = 0, error = 0, file = 4;
        const uint8_t *value = tlv(p, bytes, 1, size);
        if (msg == 1) {
            for (unsigned i = 0; i < 4; ++i)
                if (value && files[i].data && size == strlen(files[i].path) && !memcmp(value, files[i].path, size)) file = i;
            if (file == 4) error = 1;
            else { files[file].open = true; out[14] = 0x10; out[15] = 4; out[17] = file+1; extra = 7; }
        } else if (msg == 2) {
            if (value && size == 4 && u32(value) >= 1 && u32(value) <= 4) files[u32(value)-1].open = false;
        } else if (msg == 4) {
            value = tlv(p, bytes, 2, size);
            if (!value || size != 4 || !buffer || u32(value) > buffer_size) error = 1;
            else { out[14] = 0x10; out[15] = 8; for (unsigned i = 0; i < 4; ++i) out[17+i] = physical >> (8*i); extra = 11; }
        } else if (msg == 3) {
            if (value && size == 4 && u32(value) >= 1 && u32(value) <= 4) file = u32(value)-1;
            unsigned dir_size = 0, vec_size = 0;
            const uint8_t *direction = tlv(p, bytes, 2, dir_size), *vectors = tlv(p, bytes, 3, vec_size);
            if (file == 4 || !files[file].open || !direction || dir_size != 1 || !vectors || vec_size < 1 || vec_size != 1+12*vectors[0] || !buffer) error = 2;
            else {
                for (unsigned i = 0; i < vectors[0]; ++i) {
                    const uint8_t *v = vectors+1+12*i;
                    uint64_t offset = (uint64_t)u32(v)*512, address = u32(v+4), length = (uint64_t)u32(v+8)*512;
                    if (address < physical || address-physical+length > buffer_size || offset+length > files[file].size) { error = 2; break; }
                }
                if (!error) {
                    for (unsigned i = 0; i < vectors[0]; ++i) {
                        const uint8_t *v = vectors+1+12*i; unsigned offset = u32(v)*512, shared = u32(v+4)-physical, length = u32(v+8)*512;
                        if (*direction) for (unsigned b = 0; b < length; ++b) files[file].data[offset+b] = buffer[shared+b];
                        else for (unsigned b = 0; b < length; ++b) buffer[shared+b] = files[file].data[offset+b];
                    }
                    if (*direction) writes++; else reads++;
                }
            }
        } else if (msg == 5) { out[14] = 0x10; out[15] = 1; extra = 4; }
        else error = 2;
        out[5] = 7+extra; out[7] = 2; out[8] = 4; out[10] = error ? 1 : 0; out[12] = error;
        return 14+extra;
    }
};
