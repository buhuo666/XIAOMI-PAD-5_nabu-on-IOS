// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef NABU_HALL_H
#define NABU_HALL_H
#include <stdbool.h>
#include <stdint.h>

/* Captured nabu DT: hall_key GPIO9, active low, debounce 15 ms, SW_LID.
 * Live TLMM base 0x03000000 + vendor NORTH offset 0x00900000,
 * GPIO stride 0x1000. WEST is 0x03100000 and does not own GPIO9.
 */
#define NABU_HALL_GPIO_PA 0x03909000ULL
#define NABU_HALL_POLL_MS 16
#define NABU_HALL_PROPERTY "nabu-hall-closed"
#define NABU_HALL_HID_PAGE 0xff09
#define NABU_HALL_HID_USAGE 1

struct NabuHallState {
    bool sampled, previous, ready, closed;
};

static inline uint32_t nabu_hall_input_config(uint32_t config)
{
    return config & ~((15u << 2) | (1u << 9));
}

/* Two equal pin samples separated by 16 ms; publish the initial state too. */
static inline bool nabu_hall_sample(struct NabuHallState *state, uint32_t inout)
{
    bool closed = !(inout & 1);
    bool steady = state->sampled && state->previous == closed;
    state->sampled = true;
    state->previous = closed;
    if (!steady || (state->ready && state->closed == closed)) return false;
    state->ready = true;
    state->closed = closed;
    return true;
}
#endif
