// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NabuCpuFreq.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

// This unit's Android tables: L3 devfreq available_frequencies and each
// policy's scaling_available_frequencies, kHz.
static const uint32_t l3_khz[] = {300000, 403200, 499200, 614400, 710400, 806400, 902400, 998400,
    1075200, 1171200, 1267200, 1344000, 1440000, 1536000, 1612800};
static const uint32_t small_khz[] = {300000, 403200, 499200, 576000, 672000, 768000, 844800, 940800,
    1036800, 1113600, 1209600, 1305600, 1382400, 1478400, 1555200, 1632000, 1708800, 1785600};
static const uint32_t big_khz[] = {710400, 825600, 940800, 1056000, 1171200, 1286400, 1401600,
    1497600, 1612800, 1708800, 1804800, 1920000, 2016000, 2131200, 2227200, 2323200, 2419200};
static const uint32_t prime_khz[] = {825600, 940800, 1056000, 1171200, 1286400, 1401600, 1497600,
    1612800, 1708800, 1804800, 1920000, 2016000, 2131200, 2227200, 2323200, 2419200, 2534400,
    2649600, 2745600, 2841600, 2956800};

static uint32_t word(uint32_t khz, unsigned cores)
{
    return khz == 300000 ? cores << 16 : 1u << 30 | cores << 16 | khz / 19200;
}

template <unsigned N>
static unsigned fill(uint32_t *words, const uint32_t (&khz)[N], unsigned cores)
{
    for (unsigned i = 0; i < NABU_OSM_LUT_ROWS; i++) words[i] = word(khz[i < N ? i : N - 1], cores);
    return N;
}

static void decode()
{
    uint32_t words[NABU_OSM_LUT_ROWS];
    struct NabuOsmTable t = {};
    unsigned rows = fill(words, small_khz, 4);
    nabu_osm_decode(words, 1785600, &t);
    assert(t.rows == rows && t.low == 0 && t.high == 17 && t.warm == 9);
    assert(t.khz[0] == 300000 && t.khz[9] == 1113600 && t.khz[17] == 1785600);

    rows = fill(words, big_khz, 4);
    nabu_osm_decode(words, 2419200, &t);
    assert(t.rows == rows && t.low == 0 && t.high == 16 && t.khz[t.warm] == 1612800);

    rows = fill(words, prime_khz, 4);
    nabu_osm_decode(words, 2956800, &t);
    assert(t.rows == rows && t.khz[t.low] == 825600 && t.high == 20 && t.khz[t.warm] == 1920000);

    rows = fill(words, l3_khz, 1);
    nabu_osm_decode(words, 1612800, &t);
    assert(t.rows == rows && t.low == 0 && t.high == 14 && t.khz[t.warm] == 1075200);

    // A single-core boost row above the full-core rows is never requested.
    fill(words, big_khz, 4);
    words[17] = word(2419200 + 19200 * 5, 1);
    for (unsigned i = 18; i < NABU_OSM_LUT_ROWS; i++) words[i] = words[17];
    nabu_osm_decode(words, 2956800, &t);
    assert(t.rows == 18 && t.high == 16);

    // A full-core row above this unit's Android maximum is not requested either.
    fill(words, prime_khz, 4);
    nabu_osm_decode(words, 2841600, &t);
    assert(t.rows == 21 && t.khz[t.high] == 2841600);

    // A slower row after a faster one still ends up as the low row.
    fill(words, big_khz, 4);
    words[0] = word(big_khz[1], 4);
    words[1] = word(big_khz[0], 4);
    nabu_osm_decode(words, 2419200, &t);
    assert(t.low == 1 && t.high == 16);
}

static void request()
{
    static uint32_t regs[0x1400 / 4];
    regs[NABU_OSM_DCVS_CTRL / 4] = 1;
    nabu_osm_request(regs, 3, 16);
    assert(regs[0x920 / 4] == 16 && regs[0x924 / 4] == 16 && regs[0x928 / 4] == 16 && regs[0x92c / 4] == 0);
    memset(regs, 0, sizeof(regs));
    nabu_osm_request(regs, 4, 9);
    assert(regs[0x920 / 4] == 9 && regs[0x924 / 4] == 0);
    assert(nabu_cpu_domain(0x000) == NABU_OSM_SMALL && nabu_cpu_domain(0x300) == NABU_OSM_SMALL);
    assert(nabu_cpu_domain(0x400) == NABU_OSM_BIG && nabu_cpu_domain(0x600) == NABU_OSM_BIG);
    assert(nabu_cpu_domain(0x700) == NABU_OSM_PRIME);
    assert(nabu_cpu_busy_percent(100, 25) == 75 && nabu_cpu_busy_percent(100, 0) == 100);
    assert(nabu_cpu_busy_percent(100, 100) == 0 && nabu_cpu_busy_percent(100, 130) == 0);
}

static void demand()
{
    struct NabuCpuDemand d = {};
    nabu_cpu_demand(&d, 24);
    assert(!d.high);
    nabu_cpu_demand(&d, 25);
    assert(d.high);
    for (unsigned i = 0; i < NABU_CPUFREQ_HOLD_SAMPLES - 1; i++) nabu_cpu_demand(&d, 9);
    assert(d.high);
    nabu_cpu_demand(&d, 10); // Neither up nor quiet: the hold starts again.
    for (unsigned i = 0; i < NABU_CPUFREQ_HOLD_SAMPLES - 1; i++) nabu_cpu_demand(&d, 0);
    assert(d.high);
    nabu_cpu_demand(&d, 0);
    assert(!d.high && !d.quiet);
    nabu_cpu_demand(&d, 100);
    assert(d.high);
}

static void thermal()
{
    const uint32_t valid = 1u << 21;
    uint32_t status[4] = {valid | 251, 0xfff, valid | 903, valid | (uint32_t(-55) & 0xfff)};
    assert(nabu_tsens_hottest(status, 4) == 903);
    assert(nabu_tsens_hottest(status + 3, 1) == -55);
    assert(nabu_tsens_hottest(status + 1, 1) == -2730);

    assert(nabu_thermal_level(NABU_THERMAL_NORMAL, 949) == NABU_THERMAL_NORMAL);
    assert(nabu_thermal_level(NABU_THERMAL_NORMAL, 950) == NABU_THERMAL_WARM);
    assert(nabu_thermal_level(NABU_THERMAL_WARM, 850) == NABU_THERMAL_WARM);
    assert(nabu_thermal_level(NABU_THERMAL_WARM, 849) == NABU_THERMAL_NORMAL);
    assert(nabu_thermal_level(NABU_THERMAL_WARM, 1050) == NABU_THERMAL_HOT);
    assert(nabu_thermal_level(NABU_THERMAL_NORMAL, 1100) == NABU_THERMAL_HOT);
    assert(nabu_thermal_level(NABU_THERMAL_HOT, 950) == NABU_THERMAL_HOT);
    assert(nabu_thermal_level(NABU_THERMAL_HOT, 949) == NABU_THERMAL_WARM);
    assert(nabu_thermal_level(NABU_THERMAL_NORMAL, -2730) == NABU_THERMAL_NORMAL);
}

static void step()
{
    struct NabuCpuFreq f = {};
    uint32_t words[NABU_OSM_LUT_ROWS];
    fill(words, l3_khz, 1);
    nabu_osm_decode(words, nabu_osm_stock_max_khz[NABU_OSM_L3], &f.table[NABU_OSM_L3]);
    fill(words, small_khz, 4);
    nabu_osm_decode(words, nabu_osm_stock_max_khz[NABU_OSM_SMALL], &f.table[NABU_OSM_SMALL]);
    fill(words, big_khz, 4);
    nabu_osm_decode(words, nabu_osm_stock_max_khz[NABU_OSM_BIG], &f.table[NABU_OSM_BIG]);
    fill(words, prime_khz, 4);
    nabu_osm_decode(words, nabu_osm_stock_max_khz[NABU_OSM_PRIME], &f.table[NABU_OSM_PRIME]);
    auto khz = [&](unsigned d) { return f.table[d].khz[f.row[d]]; };
    const unsigned all = 15, fast = 1u << NABU_OSM_L3 | 1u << NABU_OSM_BIG | 1u << NABU_OSM_PRIME;
    uint32_t idle[NABU_OSM_DOMAINS] = {};

    // Firmware rows (big and prime at their lowest) to the startup high rows.
    f.row[NABU_OSM_L3] = 8;
    f.row[NABU_OSM_SMALL] = 12;
    f.small.high = f.fast.high = true;
    assert(nabu_cpufreq_step(&f, idle) == all);
    assert(khz(NABU_OSM_L3) == 1612800 && khz(NABU_OSM_SMALL) == 1785600);
    assert(khz(NABU_OSM_BIG) == 2419200 && khz(NABU_OSM_PRIME) == 2956800);
    for (unsigned i = 0; i < NABU_CPUFREQ_HOLD_SAMPLES - 2; i++) assert(!nabu_cpufreq_step(&f, idle));
    assert(nabu_cpufreq_step(&f, idle) == all);
    assert(khz(NABU_OSM_L3) == 300000 && khz(NABU_OSM_SMALL) == 300000);
    assert(khz(NABU_OSM_BIG) == 710400 && khz(NABU_OSM_PRIME) == 825600);

    // One busy big core raises big, prime and L3 in the same sample.
    uint32_t big[NABU_OSM_DOMAINS] = {};
    big[NABU_OSM_BIG] = 60;
    assert(nabu_cpufreq_step(&f, big) == fast);
    assert(khz(NABU_OSM_BIG) == 2419200 && khz(NABU_OSM_PRIME) == 2956800 && khz(NABU_OSM_L3) == 1612800);
    assert(khz(NABU_OSM_SMALL) == 300000);
    uint32_t prime[NABU_OSM_DOMAINS] = {};
    prime[NABU_OSM_PRIME] = 100;
    assert(!nabu_cpufreq_step(&f, prime));

    f.thermal = NABU_THERMAL_WARM;
    assert(nabu_cpufreq_step(&f, big) == fast);
    assert(khz(NABU_OSM_BIG) == 1612800 && khz(NABU_OSM_PRIME) == 1920000 && khz(NABU_OSM_L3) == 1075200);
    f.thermal = NABU_THERMAL_HOT;
    assert(nabu_cpufreq_step(&f, big) == fast);
    assert(khz(NABU_OSM_BIG) == 710400 && khz(NABU_OSM_PRIME) == 825600 && khz(NABU_OSM_L3) == 300000);
    f.thermal = NABU_THERMAL_NORMAL;
    assert(nabu_cpufreq_step(&f, big) == fast);

    // nabu-cpufreq=2 keeps every domain high through quiet, under the same cap.
    f.pinned = true;
    assert(nabu_cpufreq_step(&f, idle) == 1u << NABU_OSM_SMALL);
    for (unsigned i = 0; i < 2 * NABU_CPUFREQ_HOLD_SAMPLES; i++) assert(!nabu_cpufreq_step(&f, idle));
    assert(khz(NABU_OSM_SMALL) == 1785600 && khz(NABU_OSM_PRIME) == 2956800);
    f.thermal = NABU_THERMAL_HOT;
    assert(nabu_cpufreq_step(&f, idle) == all && khz(NABU_OSM_PRIME) == 825600);
}

int main()
{
    decode();
    request();
    demand();
    thermal();
    step();
    puts("{\"passed\":true,\"groups\":[\"decode\",\"request\",\"demand\",\"thermal\",\"step\"]}");
}
