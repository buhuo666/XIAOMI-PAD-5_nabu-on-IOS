// SPDX-License-Identifier: BSD-2-Clause-Patent
// Nabu SM8150 wireless foundation. The Android board FDT and UART firmware
// response identify a WCN3991-compatible radio, not Redwood's WCN6750.
// nabu-wireless=1 surveys only. No radio, regulator or pin is written.
#include <IOKit/IOLib.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <pexpert/pexpert.h>
#include "NabuSmem.h"
#include "NabuWirelessLog.h"
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" void hakios_spmi_lock(void);
extern "C" void hakios_spmi_unlock(void);

static thread_call_t wireless_call;
static uint32_t wireless_level;
static char wireless_report[32768];
static unsigned report_length;
static IOLock *report_lock;

void nabu_wireless_log(const char *format, ...)
{
    char line[1024];
    va_list args;
    va_start(args, format);
    vsnprintf(line, sizeof(line), format, args);
    va_end(args);
    IOLog("%s", line);
    unsigned bytes = strlen(line);
    IOLockLock(report_lock);
    if (bytes < sizeof(wireless_report) - report_length) {
        memcpy(wireless_report + report_length, line, bytes + 1);
        report_length += bytes;
    }
    IOLockUnlock(report_lock);
}

static uint32_t rd(vm_offset_t at) { return *(volatile uint32_t *)at; }

static void smem_survey()
{
    NabuSmem smem{(const volatile uint8_t *)ml_io_map(0x86000000, 0x200000), 0x200000};
    if (!smem.data) return;
    nabu_wireless_log("NABU WIRELESS: SMEM SBL=%#x initialized=%u\n", smem.u32(64 + 7 * 4), smem.u32(192));
    uint16_t hosts[] = {1, 0xfffe};
    for (unsigned h = 0; h < 2; ++h) {
        uint32_t base, line;
        if (smem.partition(hosts[h], &base, &line))
            nabu_wireless_log("NABU WIRELESS: SMEM host=%u offset=%#x size=%#x uncached=%#x cached=%#x line=%u\n",
                hosts[h], base, smem.u32(base + 8), smem.u32(base + 12), smem.u32(base + 16), line);
        else nabu_wireless_log("NABU WIRELESS: SMEM host=%u partition absent\n", hosts[h]);
    }
    const uint16_t ids[] = {421, 428, 435, 478, 479, 480};
    for (unsigned i = 0; i < sizeof(ids) / sizeof(ids[0]); ++i) {
        NabuSmemItem item;
        if (!smem.find(ids[i], &item)) {
            nabu_wireless_log("NABU WIRELESS: SMEM item=%u absent\n", ids[i]); continue;
        }
        nabu_wireless_log("NABU WIRELESS: SMEM item=%u offset=%#x bytes=%u\n", ids[i], item.offset, item.size);
        // Only protocol state; never print arbitrary shared-memory payloads.
        if ((ids[i] == 428 || ids[i] == 435 || ids[i] == 478) && item.size >= 20)
            nabu_wireless_log("NABU WIRELESS: SMEM item=%u header=%#x,%#x,%#x,%#x,%#x\n", ids[i],
                smem.u32(item.offset), smem.u32(item.offset + 4), smem.u32(item.offset + 8),
                smem.u32(item.offset + 12), smem.u32(item.offset + 16));
    }
}

static void cmd_db_survey()
{
    // This address is inside the board's xbl_aop_mem reservation. The Linux
    // Nabu DTS identifies its command database at 0x85f20000.
    NabuSmem db{(const volatile uint8_t *)ml_io_map(0x85f20000, 0x20000), 0x20000};
    if (!db.data) return;
    nabu_wireless_log("NABU WIRELESS: command database version=%u magic=%#x\n", db.u32(0), db.u32(4));
    if (db.u32(4) != 0x0c0330db) return;
    const char *names[] = {"ldoa1", "ldoa7", "ldoc2", "ldoc11", "cx.lvl", "mss.lvl", "rfclka2"};
    for (unsigned s = 0; s < 8; ++s) {
        uint32_t slave = 8 + 16 * s;
        uint32_t first = 144 + db.u16(slave + 2), count = db.u16(slave + 6);
        if (!db.u16(slave) || !db.span(first, count * 24)) continue;
        for (uint32_t e = 0; e < count; ++e) {
            uint32_t at = first + e * 24;
            char name[9] = {};
            for (unsigned b = 0; b < 8; ++b) name[b] = db.data[at + b];
            for (unsigned n = 0; n < sizeof(names) / sizeof(names[0]); ++n)
                if (!strcmp(name, names[n]))
                    nabu_wireless_log("NABU WIRELESS: resource=%s address=%#x aux-bytes=%u\n", name, db.u32(at + 16), db.u16(at + 20));
        }
    }
}

static void rpmh_survey()
{
    vm_offset_t rsc = ml_io_map(0x18220000, 0x4000);
    if (!rsc) return;
    nabu_wireless_log("NABU WIRELESS: RPMh apps DRV2 id=%#x config=%#x IRQ=%#x\n", rd(rsc), rd(rsc + 0xc), rd(rsc + 0xd04));
    // Android DT: two active, three sleep, three wake, one control TCS.
    for (unsigned i = 0; i < 2; ++i) {
        vm_offset_t tcs = rsc + 0xd00 + 672 * i;
        nabu_wireless_log("NABU WIRELESS: active TCS%u control=%#x status=%#x enabled=%#x wait=%#x\n",
            i, rd(tcs + 0x14), rd(tcs + 0x18), rd(tcs + 0x1c), rd(tcs + 0x10));
    }
    vm_offset_t aop = ml_io_map(0x0c300000, 0x1000);
    if (aop) nabu_wireless_log("NABU WIRELESS: AOP descriptor=%#x,%#x,%#x,%#x\n", rd(aop), rd(aop + 4), rd(aop + 8), rd(aop + 12));
}

static bool pmic_read(vm_offset_t core, vm_offset_t config, vm_offset_t observers,
                      uint32_t address, uint8_t *value)
{
    int selected = -1;
    for (unsigned i = 0; i < 512; ++i) {
        uint32_t map = rd(core + 0x900 + i * 4);
        if (map && ((map >> 8) & 0xfff) == (address >> 8) &&
            (selected < 0 || (rd(config + 0x700 + i * 4) & 7) == 0)) selected = i;
    }
    if (selected < 0) return false;
    vm_offset_t channel = observers + 0x80UL * selected;
    hakios_spmi_lock();
    // The observer issues only an extended-register READ command.
    *(volatile uint32_t *)channel = (1u << 27) | ((address & 255) << 4);
    __asm__ volatile("dsb sy" ::: "memory");
    uint32_t status = 0;
    for (unsigned i = 0; i < 200; ++i) {
        status = rd(channel + 8);
        if (status & 1) break;
        IODelay(10);
    }
    if ((status & 15) == 1) *value = rd(channel + 0x18);
    hakios_spmi_unlock();
    return (status & 15) == 1;
}

static void regulator_survey()
{
    vm_offset_t core = ml_io_map(0x0c440000, 0x2000), config = ml_io_map(0x0c40a000, 0x2000);
    vm_offset_t observers = ml_io_map(0x0e600000, 0x10000);
    if (!core || !config || !observers) return;
    // PM8150 slave0 L1/L7; PM8150L slave4 L2/L11. Register offsets are
    // PMIC5 LDO STATUS / VOLTAGE_CTRL1,2 / MODE_CTL / EN_CTL.
    const uint32_t bases[] = {0x04000, 0x04600, 0x44100, 0x44a00};
    const char *names[] = {"ldoa1", "ldoa7", "ldoc2", "ldoc11"};
    const uint8_t offsets[] = {0x08, 0x40, 0x41, 0x45, 0x46};
    for (unsigned i = 0; i < 4; ++i) {
        uint8_t values[5] = {};
        bool complete = true;
        for (unsigned r = 0; r < 5; ++r)
            if (!pmic_read(core, config, observers, bases[i] + offsets[r], &values[r])) { complete = false; break; }
        nabu_wireless_log("NABU WIRELESS: PMIC %s read=%u status=%#x voltage=%#x,%#x mode=%#x enable=%#x\n",
            names[i], complete, values[0], values[1], values[2], values[3], values[4]);
    }
}

static void uart_survey()
{
    // GPIO43 CTS,44 RTS,45 TX,46 RX belong to TLMM EAST, +0x00500000.
    vm_offset_t pins = ml_io_map(0x0352b000, 0x4000);
    if (pins) for (unsigned i = 0; i < 4; ++i)
        nabu_wireless_log("NABU WIRELESS: BT gpio%u config=%#x io=%#x\n", 43 + i, rd(pins + i * 0x1000), rd(pins + i * 0x1000 + 4));
    vm_offset_t gcc = ml_io_map(0x00100000, 0x60000);
    if (!gcc) return;
    uint32_t master = rd(gcc + 0x1e004), slave = rd(gcc + 0x1e008), serial = rd(gcc + 0x1e4d4);
    nabu_wireless_log("NABU WIRELESS: BT clocks vote=%#x master=%#x slave=%#x serial=%#x rcg=%#x cfg=%#x m=%#x n=%#x d=%#x\n",
        rd(gcc + 0x52014), master, slave, serial, rd(gcc + 0x1e4d8), rd(gcc + 0x1e4dc),
        rd(gcc + 0x1e4e0), rd(gcc + 0x1e4e4), rd(gcc + 0x1e4e8));
    if ((master | slave | serial) & 0x80000000) {
        nabu_wireless_log("NABU WIRELESS: BT UART register read deferred: clock halted\n"); return;
    }
    vm_offset_t uart = ml_io_map(0x00c8c000, 0x4000);
    if (uart) nabu_wireless_log("NABU WIRELESS: BT UART firmware=%#x status=%#x ios=%#x tx-clock=%#x rx-clock=%#x\n",
        rd(uart + 0x68), rd(uart + 0x40), rd(uart + 0x908), rd(uart + 0x48), rd(uart + 0x4c));
}

static void wireless_survey(thread_call_param_t, thread_call_param_t)
{
    nabu_wireless_log("NABU WIRELESS: survey begin; SM8150 SNOC Wi-Fi + WCN3991-compatible UART Bluetooth\n");
    smem_survey();
    cmd_db_survey();
    rpmh_survey();
    regulator_survey();
    uart_survey();
    nabu_wireless_log("NABU WIRELESS: survey complete; radios not started\n");
    if (wireless_level >= 2 && nabu_wireless_power_on()) {
        // v116 ruled out early BT startup as the cause of the first WLAN PFR.
        // Keep the working BT service available while WLAN runs persistently.
        nabu_bluetooth_version_trial();
        if (wireless_level >= 4) nabu_modem_start_trial();
    }
    nabu_wireless_publish();
}

void nabu_wireless_publish()
{
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    if (chosen) {
        IOLockLock(report_lock);
        chosen->setProperty("nabu-wireless-report", wireless_report);
        IOLockUnlock(report_lock);
        chosen->release();
    }
}

extern "C" void nabu_wireless_start(void)
{
    uint32_t level = 0;
    if (!PE_parse_boot_argn("nabu-wireless", &level, sizeof(level)) || level < 1 || level > 5) return;
    wireless_level = level;
    report_lock = IOLockAlloc();
    if (!report_lock) return;
    wireless_call = thread_call_allocate(wireless_survey, nullptr);
    uint64_t deadline;
    clock_interval_to_deadline(5, NSEC_PER_SEC, &deadline);
    thread_call_enter_delayed(wireless_call, deadline);
}
