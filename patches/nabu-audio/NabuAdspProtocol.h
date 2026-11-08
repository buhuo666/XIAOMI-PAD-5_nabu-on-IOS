// SPDX-License-Identifier: BSD-2-Clause-Patent
// Nabu ADSP control contracts. Primary source provenance: audio-v139/adsp-resource-review.md.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include "../nabu-wireless/NabuSmem.h"

namespace NabuAdsp {
enum : uint32_t { MemoryBase = 0x8be00000, MemorySize = 0x02200000,
    MemoryEnd = 0x8e000000, MetadataLimit = 16384, SmemSize = 0x200000,
    Host = 2, Incoming = 443, Outgoing = 429, Smp2pBytes = 340,
    Smp2pDoorbell = 10, GlinkDoorbell = 8, MaxSegments = 32 };

inline uint16_t le16(const uint8_t *p) { return uint16_t(p[0]) | uint16_t(p[1]) << 8; }
inline uint32_t le32(const uint8_t *p) { return uint32_t(le16(p)) | uint32_t(le16(p + 2)) << 16; }

struct Segment { uint32_t index, physical, file_bytes, memory_bytes; const uint8_t *file; };
struct Image { const uint8_t *metadata; uint32_t metadata_bytes, count; Segment segments[MaxSegments]; };

inline bool parse_image(const uint8_t *data, uint64_t bytes, Image &image) {
    image = {};
    if (!data || bytes < 52 || bytes > MetadataLimit || le32(data) != 0x464c457f ||
        data[4] != 1 || data[5] != 1 || le16(data + 40) != 52 || le16(data + 42) != 32) return false;
    uint32_t offset = le32(data + 28), count = le16(data + 44);
    if (!count || count > MaxSegments || offset < 52 || offset > bytes || count * 32 > bytes - offset) return false;
    for (uint32_t i = 0; i < count; ++i) {
        const uint8_t *ph = data + offset + i * 32;
        uint32_t physical = le32(ph + 12), file_bytes = le32(ph + 16), memory_bytes = le32(ph + 20);
        if (le32(ph) != 1 || !memory_bytes || ((le32(ph + 24) >> 24) & 7) == 2) continue;
        if (physical < MemoryBase || physical >= MemoryEnd || memory_bytes > MemoryEnd - physical ||
            file_bytes > memory_bytes) return false;
        image.segments[image.count++] = {i, physical, file_bytes, memory_bytes, nullptr};
    }
    if (!image.count) return false;
    image.metadata = data; image.metadata_bytes = uint32_t(bytes);
    return true;
}

// Match Linux qcom_smem_get/alloc: use common only when this host has no partition.
// An absent item in an existing host-2 partition must never resolve another edge's item.
inline bool partition(const NabuSmem &smem, uint32_t &base, uint32_t &line) {
    return smem.partition(Host, &base, &line) || smem.partition(0xfffe, &base, &line);
}
inline bool find(const NabuSmem &smem, uint16_t id, NabuSmemItem &item) {
    uint32_t base, line;
    return partition(smem, base, line) && smem.item_in(base, line, id, &item);
}

// Caller holds both the APPS allocation mutex and SMEM hardware spinlock 3.
// Writer.put publishes each 32-bit store with the platform's memory barrier.
template<class Writer>
bool allocate(const NabuSmem &smem, Writer &writer, uint16_t id, uint32_t bytes, uint32_t &offset) {
    uint32_t base, line;
    if (!partition(smem, base, line)) return false;
    NabuSmemItem item;
    if (smem.item_in(base, line, id, &item)) { offset = item.offset; return item.size == bytes; }
    uint32_t size = (bytes + 7) & ~7u, free = smem.u32(base + 12), limit = smem.u32(base + 16);
    if (free < 32 || limit < free || limit - free < 16 + size) return false;
    uint32_t header = base + free;
    writer.put(header, 0xa5a5 | (uint32_t(id) << 16)); writer.put(header + 4, size);
    writer.put(header + 8, size - bytes); writer.put(header + 12, 0);
    offset = header + 16;
    for (uint32_t i = 0; i < size; i += 4) writer.put(offset + i, 0);
    writer.put(base + 12, free + 16 + size);
    return true;
}

template<class Writer>
void publish_smp2p(Writer &writer, uint32_t offset) {
    writer.put(offset, 0x504d5324);
    writer.put(offset + 8, Host << 16); // local APPS 0, remote ADSP 2
    writer.put(offset + 12, 16 | (1u << 16));
    writer.put(offset + 16, 0);
    const char name[16] = "master-kernel";
    for (unsigned i = 0; i < 16; i += 4) writer.put(offset + 20 + i, le32((const uint8_t *)name + i));
    writer.put(offset + 36, 0);
    writer.put(offset + 4, 0x101); // version is published last; SSR_ACK feature 1
}

struct Peer { bool valid; uint32_t features, flags, state; };
inline Peer peer(const NabuSmem &smem) {
    NabuSmemItem item;
    if (!find(smem, Incoming, item) || item.size < Smp2pBytes || smem.u32(item.offset) != 0x504d5324 ||
        (smem.u32(item.offset + 4) & 255) != 1 || smem.u32(item.offset + 8) != Host ||
        smem.u16(item.offset + 14) > 16) return {};
    Peer result{true, smem.u32(item.offset + 4) >> 8, smem.u32(item.offset + 16), 0};
    const char expected[16] = "slave-kernel";
    for (unsigned i = 0; i < smem.u16(item.offset + 14); ++i) {
        unsigned at = item.offset + 20 + i * 20, j = 0;
        for (; j < 16 && smem.data[at + j] == uint8_t(expected[j]); ++j) {}
        if (j == 16) { result.state = smem.u32(at + 16); return result; }
    }
    return result;
}

struct Outcome {
    bool prepared, aop_attempted, aop_on, proxy, pas_requested, init, memory, copied;
    bool auth, ready, stop_ack, shutdown, off, retained;
};

// This is the production start/unwind sequence; host tests inject failures at every step.
template<class Operations>
Outcome run(Operations &ops) {
    Outcome result{};
    result.prepared = ops.prepare();
    if (result.prepared) {
        result.aop_attempted = true;
        result.aop_on = ops.aop_vote(true);
        if (result.aop_on && (result.proxy = ops.proxy_vote())) {
            result.pas_requested = true; // even failed PAS_INIT may have reached secure firmware
            result.init = ops.init_image();
            if (result.init && (result.memory = ops.memory_setup()) && (result.copied = ops.copy_segments())) {
                result.auth = ops.auth_reset();
                if (result.auth) {
                    result.ready = ops.wait_ready();
                    ops.observe();
                    if (result.ready) {
                        ops.probe();
                        result.stop_ack = ops.request_stop();
                    }
                }
            }
        }
    }
    if (result.pas_requested) {
        result.shutdown = ops.shutdown();
        if (!result.shutdown) { result.retained = true; return result; }
    }
    if (result.aop_attempted) result.off = ops.aop_vote(false);
    ops.release();
    return result;
}
} // namespace NabuAdsp
