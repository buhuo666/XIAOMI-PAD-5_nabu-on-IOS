// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8150 OSM row requests for L3 and the three CPU domains, by core load,
// under a TSENS cap. Only the PERF_STATE request registers are written; the
// OSM selects clock source and rail voltage for a row itself. TSENS is read.
#include <IOKit/IOLib.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>
#include "NabuCpuFreq.h"

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" bool ml_cpu_idle_time(int, uint64_t *);

static struct NabuCpuFreq freq;
static const char *const domain_names[NABU_OSM_DOMAINS] = { "l3", "small", "big", "prime" };

static uint32_t current_core(void)
{
    return (uint32_t)(__builtin_arm_rsr64("MPIDR_EL1") >> 8) & 0xff;
}

/* Iterations per millisecond of a fixed loop on whichever core runs it. */
static uint32_t loop_speed(void)
{
    volatile uint64_t sink = 0;
    uint64_t start = mach_absolute_time(), ns;
    for (uint32_t i = 0; i < 1000000; i++) sink += i;
    absolutetime_to_nanoseconds(mach_absolute_time() - start, &ns);
    return (uint32_t)(1000000000000ULL / ns);
}

/* Linux qcom-cpufreq-hw.c reads the frequency in force as this L value. */
static uint32_t voted_khz(volatile uint32_t *regs)
{
    return (regs[NABU_OSM_CURRENT_VOTE / 4] & 0x3ff) * 19200;
}

static int32_t hottest_cpu(volatile uint32_t *tsens)
{
    uint32_t status[NABU_TSENS_CPU_COUNT];
    for (unsigned i = 0; i < NABU_TSENS_CPU_COUNT; i++)
        status[i] = tsens[NABU_TSENS_STATUS(NABU_TSENS_CPU_FIRST + i) / 4];
    return nabu_tsens_hottest(status, NABU_TSENS_CPU_COUNT);
}

static void cpufreq_thread(void *, wait_result_t)
{
    const ml_topology_info_t *topology = ml_get_topology_info();
    vm_offset_t osm = ml_io_map(NABU_OSM_MAP_PA, NABU_OSM_MAP_BYTES);
    volatile uint32_t *tsens = (volatile uint32_t *)(ml_io_map(NABU_TSENS_MAP_PA,
        NABU_TSENS_MAP_BYTES) + (NABU_TSENS0_PA - NABU_TSENS_MAP_PA));
    volatile uint32_t *regs[NABU_OSM_DOMAINS];
    for (unsigned d = 0; d < NABU_OSM_DOMAINS; d++) {
        regs[d] = (volatile uint32_t *)(osm + (nabu_osm_pa[d] - NABU_OSM_MAP_PA));
        uint32_t words[NABU_OSM_LUT_ROWS];
        for (unsigned i = 0; i < NABU_OSM_LUT_ROWS; i++)
            words[i] = regs[d][(NABU_OSM_FREQ_LUT + NABU_OSM_LUT_STRIDE * i) / 4];
        struct NabuOsmTable *table = &freq.table[d];
        nabu_osm_decode(words, nabu_osm_stock_max_khz[d], table);
        freq.row[d] = regs[d][NABU_OSM_PERF_STATE / 4];
        IOLog("NABU CPUFREQ: %s pa=%#llx per-core=%u rows=%u firmware-row=%u vote=%u kHz "
              "low=%u warm=%u high=%u kHz\n", domain_names[d], nabu_osm_pa[d],
              regs[d][NABU_OSM_DCVS_CTRL / 4] & 1, table->rows, freq.row[d], voted_khz(regs[d]),
              table->khz[table->low], table->khz[table->warm], table->khz[table->high]);
        for (unsigned i = 0; i < table->rows; i += 8) {
            const uint32_t *khz = &table->khz[i];
            const uint8_t *cores = &table->cores[i];
            IOLog("NABU CPUFREQ: %s rows %u.. kHz/cores %u/%u %u/%u %u/%u %u/%u %u/%u %u/%u %u/%u %u/%u\n",
                  domain_names[d], i, khz[0], cores[0], khz[1], cores[1], khz[2], cores[2],
                  khz[3], cores[3], khz[4], cores[4], khz[5], cores[5], khz[6], cores[6], khz[7], cores[7]);
        }
    }
    /* Startup is busy: begin at the high rows and let the quiet hold lower them. */
    freq.small.high = freq.fast.high = true;
    const uint32_t core_before = current_core(), speed_before = loop_speed();

    uint64_t idle_before[8] = {}, then = mach_absolute_time();
    for (unsigned i = 0; i < topology->num_cpus; i++) ml_cpu_idle_time((int)i, &idle_before[i]);
    uint32_t peak[NABU_OSM_DOMAINS] = {}, switches = 0;
    int32_t tenths = 0;
    for (unsigned sample = 0;; sample++) {
        if (sample % NABU_THERMAL_EVERY_SAMPLES == 0) {
            const unsigned level = freq.thermal;
            tenths = hottest_cpu(tsens);
            freq.thermal = nabu_thermal_level(level, tenths);
            if (level != freq.thermal)
                IOLog("NABU CPUFREQ: thermal level %u->%u hottest=%d tenths\n", level, freq.thermal, tenths);
        }
        uint32_t busiest[NABU_OSM_DOMAINS] = {};
        const uint64_t now = mach_absolute_time();
        for (unsigned i = 0; i < topology->num_cpus; i++) {
            uint64_t idle;
            ml_cpu_idle_time((int)i, &idle);
            const uint32_t busy = nabu_cpu_busy_percent(now - then, idle - idle_before[i]);
            const unsigned d = nabu_cpu_domain(topology->cpus[i].phys_id);
            idle_before[i] = idle;
            if (busy > busiest[d]) busiest[d] = busy;
            if (busy > peak[d]) peak[d] = busy;
        }
        then = now;
        const unsigned changed = nabu_cpufreq_step(&freq, busiest);
        for (unsigned d = 0; d < NABU_OSM_DOMAINS; d++) {
            if (!(changed & (1u << d))) continue;
            nabu_osm_request(regs[d], nabu_osm_cores[d], freq.row[d]);
            switches++;
        }
        if (changed) __asm__ volatile("dsb sy" ::: "memory");
        if (sample == 0) {
            IOSleep(20);
            IOLog("NABU CPUFREQ: mode=%u first requests=%#x loop/ms before=%u on core %u after=%u on core %u\n",
                  freq.pinned ? 2 : 1, changed, speed_before, core_before, loop_speed(), current_core());
        }
        if (sample % NABU_CPUFREQ_REPORT_SAMPLES == NABU_CPUFREQ_REPORT_SAMPLES - 1) {
            IOLog("NABU CPUFREQ: request l3/small/big/prime=%u/%u/%u/%u vote=%u/%u/%u/%u kHz "
                  "peak-busy small/big/prime=%u/%u/%u%% thermal=%u hottest=%d tenths switches=%u\n",
                  freq.table[0].khz[freq.row[0]], freq.table[1].khz[freq.row[1]],
                  freq.table[2].khz[freq.row[2]], freq.table[3].khz[freq.row[3]],
                  voted_khz(regs[0]), voted_khz(regs[1]), voted_khz(regs[2]), voted_khz(regs[3]),
                  peak[NABU_OSM_SMALL], peak[NABU_OSM_BIG], peak[NABU_OSM_PRIME],
                  freq.thermal, tenths, switches);
            for (unsigned d = 0; d < NABU_OSM_DOMAINS; d++) peak[d] = 0;
        }
        IOSleep(NABU_CPUFREQ_SAMPLE_MS);
    }
}

/* nabu-cpufreq=1: rows follow core load; 2: every domain kept at its high row. */
extern "C" void nabu_cpufreq_start(void)
{
    uint32_t mode = 0;
    if (!PE_parse_boot_argn("nabu-cpufreq", &mode, sizeof(mode)) || !mode) return;
    freq.pinned = mode == 2;
    thread_t thread;
    kernel_thread_start(cpufreq_thread, NULL, &thread);
    thread_deallocate(thread);
}
