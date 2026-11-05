// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuPowerReadings.h"

// Only the MEMIF peripheral is writable. Values are register offsets within
// PM8150B slave 2, 0x4300. No write targets the SRAM data aperture.
typedef bool (*NabuMemifWrite)(uint8_t, uint8_t);
typedef void (*NabuFgDelay)(unsigned);

enum NabuFgResult {
    kNabuFgOK, kNabuFgReadFailed, kNabuFgWriteFailed, kNabuFgBusy,
    kNabuFgGrantTimeout, kNabuFgDmaError, kNabuFgReleaseFailed
};

struct NabuFgTransfer {
    unsigned grant_polls;
    uint8_t interrupt_status, dma_status;
};

static int nabu_temperature_centic(uint16_t raw)
{
    // qpnp-fg-gen4: signed 10-bit temperature, 0.25 degrees C per count.
    int counts = raw & 0x3ff;
    if (counts & 0x200) counts -= 1024;
    // AppleSmartBattery.cpp publishes centi C for iOS, unlike macOS's SBS unit.
    return counts * 25;
}

static NabuFgResult nabu_read_temperature(NabuRegisterRead read,
                                         NabuMemifWrite write,
                                         NabuFgDelay delay,
                                         uint16_t *raw,
                                         NabuFgTransfer *transfer)
{
    uint8_t arb, interface, dma_control, bytes[2];
    *transfer = {};
    if (!read(0x24340, &arb, 1) || !read(0x24350, &interface, 1) ||
        !read(0x24371, &dma_control, 1) ||
        !read(0x24370, &transfer->dma_status, 1)) return kNabuFgReadFailed;
    // An existing memory request is not ours to release.
    if ((arb & 1) || (interface & 0x80)) return kNabuFgBusy;
    if (transfer->dma_status & 6) return kNabuFgDmaError;

    bool changed_address_mode = !(dma_control & 2);
    NabuFgResult result = kNabuFgWriteFailed;
    bool mode_ready = !changed_address_mode || write(0x71, dma_control | 2);
    if (mode_ready) {
        // fg-memif.c: request arbiter, select DMA, wait 40 us, then poll the
        // Gen4 grant bit at 10 ms intervals (50 attempts maximum).
        if (write(0x40, arb | 1) && write(0x50, (interface & ~0xa0) | 0x80)) {
            delay(40);
            result = kNabuFgGrantTimeout;
            for (unsigned attempt = 0; attempt < 50; ++attempt) {
                ++transfer->grant_polls;
                if (!read(0x24310, &transfer->interrupt_status, 1)) {
                    result = kNabuFgReadFailed;
                    break;
                }
                if (transfer->interrupt_status & 8) {
                    // Gen4 word 328 is in the 300..405 partition:
                    // 0x4800 + 0x20 + (328 - 300) * 2 = 0x4858.
                    if (!read(0x24858, bytes, 2) ||
                        !read(0x24370, &transfer->dma_status, 1))
                        result = kNabuFgReadFailed;
                    else result = (transfer->dma_status & 6) ? kNabuFgDmaError : kNabuFgOK;
                    break;
                }
                delay(10000);
            }
        }
        // Release the interface before the arbiter, including failed requests.
        // Restore the saved idle settings without changing other configuration.
        bool interface_released = write(0x50, interface);
        bool arbiter_released = write(0x40, arb);
        if (!interface_released || !arbiter_released) result = kNabuFgReleaseFailed;
    }
    if (changed_address_mode && !write(0x71, dma_control)) result = kNabuFgReleaseFailed;
    // A sample is usable only after its memory access has been released.
    if (result == kNabuFgOK) *raw = nabu_le16(bytes);
    return result;
}
