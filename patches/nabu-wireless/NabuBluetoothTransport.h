// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

// One producer and one serialized consumer, both protected by the driver's RX lock.
// No HCI parsing: ACL/event headers and payloads may span any number of reads.
struct NabuBluetoothRx {
    static constexpr unsigned capacity = 65536;
    uint8_t data[capacity]{};
    unsigned head = 0, count = 0;
    uint32_t generation = 0;

    bool push_word(uint32_t word, unsigned bytes) {
        if (bytes > capacity - count) return false;
        for (unsigned i = 0; i < bytes; ++i)
            data[(head + count++) % capacity] = word >> (8 * i);
        return true;
    }
    unsigned peek(uint8_t *out, unsigned bytes) const {
        if (bytes > count) bytes = count;
        for (unsigned i = 0; i < bytes; ++i) out[i] = data[(head + i) % capacity];
        return bytes;
    }
    void consume(unsigned bytes) { head = (head + bytes) % capacity; count -= bytes; }
    void clear() { head = count = 0; ++generation; }
};
