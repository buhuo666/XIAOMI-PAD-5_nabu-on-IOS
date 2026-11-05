// SPDX-License-Identifier: BSD-2-Clause-Patent
// NT36523 point packets -> the existing hakios-touch queue, in panel coordinates.
#pragma once
#include <stdint.h>
#ifdef KERNEL
#include <libkern/libkern.h>
#else
#include <string.h>
#endif

struct NabuContacts {
    uint16_t active;
    uint16_t x[10], y[10];
};

static int nabu_decode_contacts(const uint8_t packet[80], uint32_t width,
                               uint32_t height, struct NabuContacts *contacts)
{
    int watchdog = 1, esd = 1;
    for (unsigned i = 0; i < 6; ++i) {
        watchdog &= packet[i] == 0xfd || packet[i] == 0xfe;
        esd &= packet[i] == 0x77;
    }
    if (watchdog) return -2;
    if (esd) return -3;
    uint8_t checksum = 0;
    for (unsigned i = 0; i <= 64; ++i) checksum += packet[i];
    if (checksum || width < 2 || height < 2) return -1;
    memset(contacts, 0, sizeof(*contacts));
    for (unsigned i = 0; i < 10; ++i) {
        const uint8_t *point = packet + i * 6;
        unsigned id = point[0] >> 3, state = point[0] & 7;
        if (id < 1 || id > 10 || (state != 1 && state != 2)) continue;
        unsigned x = (point[1] << 4) | (point[3] >> 4);
        unsigned y = (point[2] << 4) | (point[3] & 15);
        if (x >= width || y >= height) continue;
        --id;
        contacts->active |= (uint16_t)(1u << id);
        contacts->x[id] = (uint16_t)(x * 65535u / (width - 1));
        contacts->y[id] = (uint16_t)(y * 65535u / (height - 1));
    }
    return 0;
}

// Call only after a complete valid packet; a bad read must not release fingers.
static void nabu_publish_contacts(struct NabuContacts *previous,
                                 const struct NabuContacts *current,
                                 void (*post)(uint32_t, uint32_t, uint32_t, uint32_t))
{
    for (unsigned id = 0; id < 10; ++id) {
        unsigned mask = 1u << id;
        if (current->active & mask) {
            if (!(previous->active & mask))
                post(1, id, current->x[id], current->y[id]);
            else if (previous->x[id] != current->x[id] || previous->y[id] != current->y[id])
                post(2, id, current->x[id], current->y[id]);
        } else if (previous->active & mask) {
            post(3, id, previous->x[id], previous->y[id]);
        }
    }
    *previous = *current;
}
