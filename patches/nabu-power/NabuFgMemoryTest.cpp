// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NabuFgMemory.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static uint8_t registers[0x30000];
static unsigned reads, writes, fail_read, fail_write;
static unsigned grant_after, grant_polls, dma_reads, slept_us;
static bool dma_error_after_read;

static void reset_fixture(bool partition_mode = false)
{
    memset(registers, 0, sizeof(registers));
    // Keep unrelated bits and an idle IMA selection set to test restoration.
    registers[0x24340] = 0x0a;
    registers[0x24350] = 0x24;
    registers[0x24371] = partition_mode ? 0x82 : 0x80;
    registers[0x24858] = 98; // 24.50 C.
    reads = writes = fail_read = fail_write = grant_polls = dma_reads = slept_us = 0;
    grant_after = 1;
    dma_error_after_read = false;
}

static bool read_fixture(uint32_t address, uint8_t *data, unsigned size)
{
    if (++reads == fail_read) return false;
    assert(size <= 4);
    if (address == 0x24310) {
        assert(registers[0x24340] & 1);
        assert((registers[0x24350] & 0xa0) == 0x80);
        ++grant_polls;
        *data = grant_polls >= grant_after ? 8 : 0;
    } else if (address == 0x24858) {
        assert(grant_polls >= grant_after); // Never read data without a grant.
        assert(registers[0x24371] & 2);
        ++dma_reads;
        memcpy(data, registers + address, size);
    } else if (address == 0x24370 && dma_reads && dma_error_after_read) {
        *data = 4;
    } else memcpy(data, registers + address, size);
    return true;
}

static bool write_fixture(uint8_t offset, uint8_t value)
{
    assert(offset == 0x40 || offset == 0x50 || offset == 0x71);
    if (++writes == fail_write) return false;
    registers[0x24300 + offset] = value;
    return true;
}

static void delay_fixture(unsigned us)
{
    assert(us == 40 || us == 10000);
    assert(registers[0x24340] & 1);
    assert((registers[0x24350] & 0xa0) == 0x80);
    slept_us += us;
}

static NabuFgResult sample(uint16_t *raw, NabuFgTransfer *transfer)
{
    return nabu_read_temperature(read_fixture, write_fixture, delay_fixture, raw, transfer);
}

static void assert_released(bool partition_mode = false)
{
    assert(registers[0x24340] == 0x0a);
    assert(registers[0x24350] == 0x24);
    assert(registers[0x24371] == (partition_mode ? 0x82 : 0x80));
}

int main()
{
    for (int count = -512; count <= 511; ++count) {
        uint16_t raw = (uint16_t)count & 0x3ff;
        assert(nabu_temperature_centic(raw) == count * 25);
        assert(nabu_temperature_centic(raw | 0xfc00) == count * 25);
    }
    assert(nabu_temperature_centic(100) == 2500);
    assert(nabu_temperature_centic(1023) == -25);

    uint16_t raw = 0xbeef;
    NabuFgTransfer transfer;
    const bool address_modes[] = {false, true};
    for (bool partition : address_modes) {
        reset_fixture(partition);
        assert(sample(&raw, &transfer) == kNabuFgOK && raw == 98);
        assert(grant_polls == 1 && dma_reads == 1 && slept_us == 40);
        assert_released(partition);
    }

    reset_fixture();
    grant_after = 4;
    assert(sample(&raw, &transfer) == kNabuFgOK);
    assert(grant_polls == 4 && slept_us == 30040 && dma_reads == 1);
    assert_released();

    reset_fixture();
    grant_after = 51;
    raw = 0xbeef;
    assert(sample(&raw, &transfer) == kNabuFgGrantTimeout);
    assert(grant_polls == 50 && slept_us == 500040 && dma_reads == 0 && raw == 0xbeef);
    assert_released();

    for (unsigned failure = 1; failure <= 7; ++failure) {
        reset_fixture(); fail_read = failure; raw = 0xbeef;
        assert(sample(&raw, &transfer) == kNabuFgReadFailed && raw == 0xbeef);
        assert_released();
    }
    for (unsigned failure = 1; failure <= 6; ++failure) {
        reset_fixture(); fail_write = failure; raw = 0xbeef;
        NabuFgResult result = sample(&raw, &transfer);
        assert(result == (failure >= 4 ? kNabuFgReleaseFailed : kNabuFgWriteFailed));
        assert(raw == 0xbeef);
        if (failure < 4) assert_released();
    }

    reset_fixture(); registers[0x24340] |= 1;
    assert(sample(&raw, &transfer) == kNabuFgBusy && writes == 0 && dma_reads == 0);
    reset_fixture(); registers[0x24350] |= 0x80;
    assert(sample(&raw, &transfer) == kNabuFgBusy && writes == 0 && dma_reads == 0);
    reset_fixture(); registers[0x24370] = 4;
    assert(sample(&raw, &transfer) == kNabuFgDmaError && writes == 0);
    reset_fixture(); dma_error_after_read = true; raw = 0xbeef;
    assert(sample(&raw, &transfer) == kNabuFgDmaError && raw == 0xbeef);
    assert_released();
    puts("PASS: signed temperature/iOS units, grant ordering, delayed/timeout grants, configuration restoration, bus failures, busy ownership and DMA errors");
}
