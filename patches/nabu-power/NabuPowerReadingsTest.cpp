// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NabuPowerReadings.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t registers[0x30000];
static uint32_t fail_address;
static bool rtc_carry;
static unsigned rtc_reads;

static bool read_fixture(uint32_t address, uint8_t *data, unsigned size)
{
    if (address == fail_address) return false;
    if (address == 0x6048 && rtc_carry) {
        // Counter rolls from 0x01ffff to 0x020000 after the first read.
        const uint8_t before[] = {0xff, 0xff, 1, 0}, after[] = {0, 0, 2, 0};
        memcpy(data, rtc_reads++ ? after : before, size);
    } else memcpy(data, registers + address, size);
    return true;
}

static void word(uint32_t address, uint16_t value)
{
    registers[address] = value;
    registers[address + 1] = value >> 8;
}

int main()
{
    registers[0x24009] = registers[0x2400a] = 255;
    word(0x241a0, 36044); word(0x241a6, 36044); // 4.400 V
    word(0x241a2, 0xfc00); word(0x241a8, 0xfc00); // -1024 counts: +499 mA into pack
    registers[0x21310] = 0x10;
    registers[0x21006] = 3;
    NabuChargeStatus before, after;
    assert(nabu_read_charge_status(read_fixture, &before));
    registers[0x21006] = 7;
    assert(nabu_read_charge_status(read_fixture, &after));
    assert(before.external == after.external && nabu_charge_status_changed(before, after));
    registers[0x21006] = 3;
    assert(nabu_read_charge_status(read_fixture, &after));
    assert(!nabu_charge_status_changed(before, after));
    registers[0x21310] = 0;
    assert(nabu_read_charge_status(read_fixture, &after) && nabu_charge_status_changed(before, after));
    registers[0x21310] = 0x10;
    NabuPowerSample sample = {};
    assert(nabu_read_power(read_fixture, &sample));
    assert(sample.percent == 100 && sample.voltage_mv == 4399 && sample.current_ma == 499);
    assert(sample.present && sample.external && sample.charging && !sample.full);

    registers[0x24009] = registers[0x2400a] = 128;
    word(0x241a2, 2048); word(0x241a8, 2048);
    registers[0x21310] = 0;
    assert(nabu_read_power(read_fixture, &sample));
    assert(sample.percent == 50 && sample.current_ma == -999 && !sample.charging && !sample.external);
    for (unsigned raw = 0; raw <= 255; ++raw) {
        registers[0x24009] = registers[0x2400a] = raw;
        assert(nabu_read_power(read_fixture, &sample));
        assert(sample.percent <= 100);
        if (raw == 0) assert(sample.percent == 0);
        if (raw == 1) assert(sample.percent == 1);
        if (raw == 254) assert(sample.percent == 99);
    }
    NabuPowerSample saved = sample;
    registers[0x2400a]--;
    assert(!nabu_read_power(read_fixture, &sample));
    assert(memcmp(&sample, &saved, sizeof(sample)) == 0);
    registers[0x2400a]++;
    word(0x241a8, 2049);
    assert(!nabu_read_power(read_fixture, &sample));
    word(0x241a8, 2048);
    fail_address = 0x241a0;
    assert(!nabu_read_power(read_fixture, &sample));
    assert(memcmp(&sample, &saved, sizeof(sample)) == 0);
    fail_address = 0;
    registers[0x21310] = 0x10;
    registers[0x21006] = 5;
    assert(nabu_read_power(read_fixture, &sample) && sample.full && !sample.charging);

    uint32_t seconds = 7;
    word(0x6048, 0xffff); word(0x604a, 1);
    assert(nabu_read_rtc(read_fixture, &seconds) && seconds == 0x1ffff);
    rtc_carry = true;
    assert(nabu_read_rtc(read_fixture, &seconds) && seconds == 0x20000 && rtc_reads == 3);
    fail_address = 0x6048;
    assert(!nabu_read_rtc(read_fixture, &seconds) && seconds == 0x20000);
    fail_address = 0;
    NabuGaugeHistory history = {}, saved_history;
    registers[0xb180] = 0xa5;
    word(0xb191, 8688); // Android bms CHARGE_FULL=8688000 uAh on this device.
    assert(nabu_read_gauge_history(read_fixture, &history));
    assert(history.learned_capacity_mah == 8688 && history.cycle_count == 0);
    const uint16_t counts[] = {255, 256, 257, 258, 259, 260, 261, 263};
    for (unsigned i = 0; i < 8; ++i) word(0xb181 + i * 2, counts[i]);
    assert(nabu_read_gauge_history(read_fixture, &history));
    assert(history.cycle_count == 258);
    assert(memcmp(history.cycle_buckets, counts, sizeof(counts)) == 0);
    saved_history = history;
    registers[0xb180] = 0;
    assert(!nabu_read_gauge_history(read_fixture, &history));
    assert(memcmp(&history, &saved_history, sizeof(history)) == 0);
    registers[0xb180] = 0xa5;
    const uint32_t failed_reads[] = {0xb180u, 0xb181u, 0xb185u, 0xb189u, 0xb18du, 0xb191u};
    for (uint32_t address : failed_reads) {
        fail_address = address;
        assert(!nabu_read_gauge_history(read_fixture, &history));
        assert(memcmp(&history, &saved_history, sizeof(history)) == 0);
    }
    puts("PASS: FG scaling/endpoints, current polarity, charger state, shadow mismatch, bus failure, RTC rollover and SDAM capacity/cycles");
}
