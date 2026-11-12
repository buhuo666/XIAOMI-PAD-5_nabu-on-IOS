// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef NABU_CPUFREQ_H
#define NABU_CPUFREQ_H
#include <stdbool.h>
#include <stdint.h>

/* Captured nabu DT qcom,clk-cpu-osm: osm_l3_base, osm_pwrcl_base (cpu0-3),
 * osm_perfcl_base (cpu4-6) and osm_perfpcl_base (cpu7), 0x1400 bytes each.
 * Register layout: Linux qcom-cpufreq-hw.c (OSM) and interconnect osm-l3.c.
 * The OSM switches clock source and rail voltage itself for a requested row.
 * One 16 KiB-aligned mapping covers the four blocks.
 */
enum { NABU_OSM_L3, NABU_OSM_SMALL, NABU_OSM_BIG, NABU_OSM_PRIME, NABU_OSM_DOMAINS };
#define NABU_OSM_MAP_PA 0x18320000ULL
#define NABU_OSM_MAP_BYTES 0xc000
static const uint64_t nabu_osm_pa[NABU_OSM_DOMAINS] = {
    0x18321000ULL, 0x18323000ULL, 0x18325800ULL, 0x18327800ULL
};
/* Per-core request registers of a domain whose DCVS_CTRL bit 0 is set. */
static const uint8_t nabu_osm_cores[NABU_OSM_DOMAINS] = { 1, 4, 3, 1 };
/* This unit under Android: L3 devfreq max_freq and each policy's
 * cpuinfo_max_freq, kHz. No row above them is requested. */
static const uint32_t nabu_osm_stock_max_khz[NABU_OSM_DOMAINS] = {
    1612800, 1785600, 2419200, 2956800
};
#define NABU_OSM_DCVS_CTRL 0x0bc
#define NABU_OSM_FREQ_LUT 0x110
#define NABU_OSM_LUT_STRIDE 32
#define NABU_OSM_LUT_ROWS 40
#define NABU_OSM_CURRENT_VOTE 0x704
#define NABU_OSM_PERF_STATE 0x920

/* tsens@c222000 readings at 0x0c263000: sensors 1-4 cpu0-3, 5-6 CPU subsystem,
 * 7-14 cpu4-7. Linux tsens-v2.c Sn_STATUS: bit 21 valid, low 12 bits signed
 * tenths of a degree. Read only. */
#define NABU_TSENS_MAP_PA 0x0c260000ULL
#define NABU_TSENS_MAP_BYTES 0x4000
#define NABU_TSENS0_PA 0x0c263000ULL
#define NABU_TSENS_STATUS(sensor) (0xa0 + 4 * (sensor))
#define NABU_TSENS_CPU_FIRST 1
#define NABU_TSENS_CPU_COUNT 14

#define NABU_CPUFREQ_SAMPLE_MS 4
#define NABU_CPUFREQ_UP_PERCENT 25
#define NABU_CPUFREQ_DOWN_PERCENT 10
#define NABU_CPUFREQ_HOLD_SAMPLES 250    /* 1 s below DOWN before the low row */
#define NABU_THERMAL_EVERY_SAMPLES 50    /* 200 ms */
#define NABU_CPUFREQ_REPORT_SAMPLES 1250 /* 5 s */

struct NabuOsmTable {
    uint32_t khz[NABU_OSM_LUT_ROWS];
    uint8_t cores[NABU_OSM_LUT_ROWS];
    uint8_t rows, low, warm, high;
};

/* A row is [31:30] source (0: the fixed 300 MHz source), [18:16] core count,
 * [7:0] multiple of 19.2 MHz; the table ends by repeating its last frequency.
 * Rows with fewer than the table's most cores are boost rows and are not used.
 * low/high are the slowest and fastest usable rows up to the stock maximum,
 * warm the fastest usable row up to two thirds of it. */
static inline void nabu_osm_decode(const uint32_t *words, uint32_t stock_max_khz,
                                   struct NabuOsmTable *table)
{
    uint8_t most = 0;
    table->rows = 0;
    for (unsigned i = 0; i < NABU_OSM_LUT_ROWS; i++) {
        uint32_t khz = (words[i] >> 30) ? 19200 * (words[i] & 0xff) : 300000;
        uint8_t cores = (words[i] >> 16) & 7;
        if (i && khz == table->khz[i - 1]) break;
        table->khz[i] = khz;
        table->cores[i] = cores;
        table->rows = i + 1;
        if (cores > most) most = cores;
    }
    uint32_t low = UINT32_MAX, warm = 0, high = 0;
    for (unsigned i = 0; i < table->rows; i++) {
        uint32_t khz = table->khz[i];
        if (table->cores[i] != most || khz > stock_max_khz) continue;
        if (khz < low) { low = khz; table->low = i; }
        if (khz >= high) { high = khz; table->high = i; }
        if (khz <= stock_max_khz / 3 * 2 && khz >= warm) { warm = khz; table->warm = i; }
    }
}

static inline void nabu_osm_request(volatile uint32_t *regs, unsigned cores, uint32_t row)
{
    unsigned requests = (regs[NABU_OSM_DCVS_CTRL / 4] & 1) ? cores : 1;
    for (unsigned i = 0; i < requests; i++) regs[NABU_OSM_PERF_STATE / 4 + i] = row;
}

static inline unsigned nabu_cpu_domain(uint32_t phys_id)
{
    uint32_t core = (phys_id >> 8) & 0xff;
    return core < 4 ? NABU_OSM_SMALL : core < 7 ? NABU_OSM_BIG : NABU_OSM_PRIME;
}

static inline uint32_t nabu_cpu_busy_percent(uint64_t elapsed, uint64_t idle)
{
    return idle < elapsed ? (uint32_t)((elapsed - idle) * 100 / elapsed) : 0;
}

/* One sample of the busiest core. Up at once, down after a held quiet. */
struct NabuCpuDemand {
    bool high;
    uint16_t quiet;
};

static inline void nabu_cpu_demand(struct NabuCpuDemand *demand, uint32_t busiest_percent)
{
    if (busiest_percent >= NABU_CPUFREQ_UP_PERCENT) {
        demand->high = true;
        demand->quiet = 0;
    } else if (busiest_percent >= NABU_CPUFREQ_DOWN_PERCENT) {
        demand->quiet = 0;
    } else if (demand->high && ++demand->quiet >= NABU_CPUFREQ_HOLD_SAMPLES) {
        demand->high = false;
        demand->quiet = 0;
    }
}

/* The hottest of the sensors that hold a reading; a sensor between two
 * conversions has its valid bit clear for a moment. */
static inline int32_t nabu_tsens_hottest(const uint32_t *status, unsigned count)
{
    int32_t hottest = -2730;
    for (unsigned i = 0; i < count; i++) {
        int32_t tenths = (int32_t)(status[i] << 20) >> 20;
        if ((status[i] & (1u << 21)) && tenths > hottest) hottest = tenths;
    }
    return hottest;
}

/* Android's passive trips on these sensors are 110 and 125 degrees. Cap at the
 * warm row from 95, the low row from 105; release 10 degrees lower. */
enum { NABU_THERMAL_NORMAL, NABU_THERMAL_WARM, NABU_THERMAL_HOT };

static inline unsigned nabu_thermal_level(unsigned level, int32_t tenths)
{
    if (tenths >= 1050) return NABU_THERMAL_HOT;
    if (level == NABU_THERMAL_HOT) return tenths >= 950 ? NABU_THERMAL_HOT : NABU_THERMAL_WARM;
    if (tenths >= 950) return NABU_THERMAL_WARM;
    return level == NABU_THERMAL_WARM && tenths >= 850 ? NABU_THERMAL_WARM : NABU_THERMAL_NORMAL;
}

static inline uint32_t nabu_osm_row(const struct NabuOsmTable *table, bool high, unsigned thermal)
{
    if (!high || thermal == NABU_THERMAL_HOT) return table->low;
    return thermal == NABU_THERMAL_WARM ? table->warm : table->high;
}

/* The small cores follow their own busiest core. The scheduler moves a thread
 * between the big cores and the prime core, so those two domains share one
 * demand. L3 is high while either demand is. pinned (nabu-cpufreq=2) keeps
 * every domain high; the thermal cap applies in both modes. */
struct NabuCpuFreq {
    struct NabuOsmTable table[NABU_OSM_DOMAINS];
    struct NabuCpuDemand small, fast;
    unsigned thermal;
    uint32_t row[NABU_OSM_DOMAINS];
    bool pinned;
};

/* busiest[d]: this sample's busiest core of CPU domain d, percent. Returns
 * bit d for each domain whose row[d] is now a different request. */
static inline unsigned nabu_cpufreq_step(struct NabuCpuFreq *freq, const uint32_t *busiest)
{
    uint32_t fast = busiest[NABU_OSM_BIG] > busiest[NABU_OSM_PRIME] ?
        busiest[NABU_OSM_BIG] : busiest[NABU_OSM_PRIME];
    nabu_cpu_demand(&freq->small, busiest[NABU_OSM_SMALL]);
    nabu_cpu_demand(&freq->fast, fast);
    bool high[NABU_OSM_DOMAINS];
    high[NABU_OSM_SMALL] = freq->pinned || freq->small.high;
    high[NABU_OSM_BIG] = high[NABU_OSM_PRIME] = freq->pinned || freq->fast.high;
    high[NABU_OSM_L3] = high[NABU_OSM_SMALL] || high[NABU_OSM_BIG];
    unsigned changed = 0;
    for (unsigned d = 0; d < NABU_OSM_DOMAINS; d++) {
        uint32_t row = nabu_osm_row(&freq->table[d], high[d], freq->thermal);
        if (row != freq->row[d]) {
            freq->row[d] = row;
            changed |= 1u << d;
        }
    }
    return changed;
}
#endif
