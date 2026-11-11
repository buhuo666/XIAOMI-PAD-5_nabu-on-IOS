// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>

// Fixed records shared by the kernel recorder and host reader. The caller owns
// storage and serializes all methods. No allocation, clock read, logging or
// hardware action occurs here; an IRQ-safe wrapper supplies those boundaries.
namespace NabuFrameTrace {
constexpr uint32_t SchemaVersion = 1;
struct Record {
    uint64_t timeUs, identity, a, b, c;
    uint32_t event, window;
};
static_assert(sizeof(Record) == 48, "Trace wire record changed");
struct Metadata {
    uint64_t startUs = 0, endUs = 0, deadlineUs = 0, dropped = 0;
    uint32_t window = 0, count = 0, capacity = 0, exportedThrough = 0;
    bool active = false;
    bool acknowledged = false;
};
enum Status { Ok, Invalid, Busy, NotStopped };

class Recorder final {
    Record *records_ = nullptr;
    Metadata metadata_{};
public:
    Status initialize(Record *records, uint32_t capacity) {
        if (!records || !capacity || records_) return Invalid;
        records_ = records; metadata_.capacity = capacity; return Ok;
    }
    Status start(uint64_t now, uint32_t durationMs) {
        if (!records_ || !durationMs || durationMs > 600000 ||
            now > UINT64_MAX - uint64_t(durationMs) * 1000) return Invalid;
        if (metadata_.active || (metadata_.count && !metadata_.acknowledged)) return Busy;
        uint32_t next = metadata_.window + 1;
        if (!next) next = 1;
        const uint32_t capacity = metadata_.capacity;
        metadata_ = {};
        metadata_.window = next; metadata_.capacity = capacity;
        metadata_.startUs = now; metadata_.deadlineUs = now + uint64_t(durationMs) * 1000;
        metadata_.active = true;
        return Ok;
    }
    void expire(uint64_t now) {
        if (metadata_.active && now >= metadata_.deadlineUs) {
            metadata_.active = false; metadata_.endUs = metadata_.deadlineUs;
        }
    }
    void stop(uint64_t now) {
        expire(now);
        if (metadata_.active) {
            metadata_.active = false;
            metadata_.endUs = now < metadata_.startUs ? metadata_.startUs : now;
        }
    }
    bool append(uint64_t now, uint32_t event, uint64_t identity,
                uint64_t a = 0, uint64_t b = 0, uint64_t c = 0) {
        expire(now);
        // A timestamp obtained before the window opened is not part of it.
        if (!metadata_.active || now < metadata_.startUs) return false;
        if (metadata_.count == metadata_.capacity) { ++metadata_.dropped; return false; }
        records_[metadata_.count++] = {now, identity, a, b, c, event, metadata_.window};
        return true;
    }
    Status read(uint32_t offset, Record *out, uint32_t limit, uint32_t *copied) {
        if (!copied) return Invalid;
        *copied = 0;
        if (metadata_.active) return NotStopped;
        if (!records_ || !out || !limit || offset > metadata_.count) return Invalid;
        const uint32_t remaining = metadata_.count - offset;
        const uint32_t count = remaining < limit ? remaining : limit;
        for (uint32_t i = 0; i < count; ++i) out[i] = records_[offset + i];
        *copied = count;
        // Track contiguous delivery, but do not unlock reuse until the host
        // explicitly acknowledges its durably saved complete export.
        if (offset <= metadata_.exportedThrough && offset + count > metadata_.exportedThrough)
            metadata_.exportedThrough = offset + count;
        return Ok;
    }
    Status acknowledge(uint32_t count) {
        if (metadata_.active) return NotStopped;
        if (!metadata_.window || count != metadata_.count || metadata_.exportedThrough != count)
            return Invalid;
        metadata_.acknowledged = true;
        return Ok;
    }
    const Metadata &metadata() const { return metadata_; }
};
}
