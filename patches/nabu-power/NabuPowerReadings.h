// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

// Register addresses include the SPMI slave in bits 19:16.
// MiCode nabu-r-oss fg-util.c / smb5-reg.h / qpnp-rtc.c, and this board's FDT.
typedef bool (*NabuRegisterRead)(uint32_t, uint8_t *, unsigned);

struct NabuPowerSample {
    unsigned percent, voltage_mv;
    int current_ma; // Darwin: positive into the battery, negative discharge.
    bool present, external, charging, full;
    uint8_t raw_soc, charger_state;
};

struct NabuChargeStatus {
    bool external;
    uint8_t charger_state;
};

struct NabuGaugeHistory {
    unsigned learned_capacity_mah, cycle_count;
    uint16_t cycle_buckets[8];
};

static bool nabu_read_charge_status(NabuRegisterRead read, NabuChargeStatus *out)
{
    uint8_t usb, charger;
    if (!read(0x21310, &usb, 1) || !read(0x21006, &charger, 1)) return false;
    out->external = (usb & 0x10) != 0;
    out->charger_state = charger & 7;
    return true;
}

static bool nabu_charge_status_changed(const NabuChargeStatus &a, const NabuChargeStatus &b)
{
    return a.external != b.external || a.charger_state != b.charger_state;
}

static uint16_t nabu_le16(const uint8_t *p)
{
    return p[0] | (uint16_t)p[1] << 8;
}

static bool nabu_read_gauge_history(NabuRegisterRead read, NabuGaugeHistory *out)
{
    // This board's fg_sdam phandle points to PM8150 slave 0, SDAM@b100.
    // qpnp-fg-gen4 stores the cookie at +0x80, eight little-endian cycle
    // buckets at +0x81, and learned capacity (mAh) at +0x91.
    uint8_t cookie, buckets[16], capacity[2];
    if (!read(0x0b180, &cookie, 1) || cookie != 0xa5) return false;
    for (unsigned i = 0; i < sizeof(buckets); i += 4)
        if (!read(0x0b181 + i, buckets + i, 4)) return false;
    if (!read(0x0b191, capacity, 2)) return false;
    NabuGaugeHistory history = {};
    history.learned_capacity_mah = nabu_le16(capacity);
    for (unsigned i = 0; i < 8; ++i) {
        history.cycle_buckets[i] = nabu_le16(buckets + i * 2);
        history.cycle_count += history.cycle_buckets[i];
    }
    // fg-alg.c get_cycle_count() normalizes the eight SOC buckets.
    history.cycle_count /= 8;
    *out = history;
    return true;
}

static bool nabu_read_rtc(NabuRegisterRead read, uint32_t *seconds)
{
    uint8_t bytes[4], low;
    if (!read(0x06048, bytes, 4) || !read(0x06048, &low, 1)) return false;
    // The Qualcomm RTC requires rereading the whole counter on low-byte carry.
    if (low < bytes[0] && !read(0x06048, bytes, 4)) return false;
    *seconds = (uint32_t)bytes[0] | (uint32_t)bytes[1] << 8 |
               (uint32_t)bytes[2] << 16 | (uint32_t)bytes[3] << 24;
    return true;
}

static bool nabu_read_power(NabuRegisterRead read, NabuPowerSample *out)
{
    uint8_t soc[2], adc[4], shadow[4], battery, usb, charger;
    // FG's primary and copy registers must agree before publishing a sample.
    bool coherent = false;
    for (unsigned attempt = 0; attempt < 3; ++attempt) {
        if (!read(0x24009, soc, 2) || !read(0x241a0, adc, 4) ||
            !read(0x241a6, shadow, 4)) return false;
        coherent = soc[0] == soc[1] && nabu_le16(adc) == nabu_le16(shadow) &&
                   nabu_le16(adc + 2) == nabu_le16(shadow + 2);
        if (coherent) break;
    }
    if (!coherent || !read(0x21210, &battery, 1) ||
        !read(0x21310, &usb, 1) || !read(0x21006, &charger, 1)) return false;

    NabuPowerSample sample = {};
    sample.raw_soc = soc[0];
    // Hardware MSOC, with the endpoint mapping from fg_get_msoc().
    sample.percent = soc[0] == 255 ? 100 : soc[0] == 0 ? 0 :
                     ((soc[0] - 1) * 98 + 126) / 253 + 1;
    sample.voltage_mv = (uint64_t)nabu_le16(adc) * 122070 / 1000000;
    sample.current_ma = -((int64_t)(int16_t)nabu_le16(adc + 2) * 488281 / 1000000);
    sample.present = (battery & 0x30) == 0;
    sample.external = (usb & 0x10) != 0;
    sample.charger_state = charger & 7;
    sample.charging = sample.external && sample.charger_state >= 1 && sample.charger_state <= 4;
    sample.full = sample.external && sample.charger_state == 5;
    *out = sample;
    return true;
}
