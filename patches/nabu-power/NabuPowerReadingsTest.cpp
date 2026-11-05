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
    puts("PASS: FG scaling/endpoints, current polarity, charger state, shadow mismatch, bus failure and RTC rollover");
}
