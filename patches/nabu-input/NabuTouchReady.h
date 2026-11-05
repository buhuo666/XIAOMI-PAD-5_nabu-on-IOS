// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8150 GPIO39: NORTH tile, rising-edge latch, polled without a GIC handler.
#pragma once
#include <stdint.h>

template <typename Registers> static void nabu_touch_ready_init(Registers &gpio)
{
    // GPIO input, preserve pull/drive settings. GPIO39 belongs to NORTH.
    gpio.w(0, gpio.r(0) & ~((15u << 2) | (1u << 9)));
    // KPSS target=3, raw status enabled, rising edge. Keep IRQ output masked.
    gpio.w(8, (gpio.r(8) & ~0xffu) | (3u << 5) | (1u << 4) | (1u << 2) | 2u);
    // Enabling raw status can set a spurious edge; clear before firmware boot.
    gpio.w(12, gpio.r(12) & ~1u);
}

template <typename Registers> static bool nabu_touch_take_ready(Registers &gpio)
{
    uint32_t status = gpio.r(12);
    if (!(status & 1)) return false;
    // Acknowledge before SPI: a new edge during transfer remains pending.
    gpio.w(12, status & ~1u);
    return true;
}
