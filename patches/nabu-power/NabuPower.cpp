// SPDX-License-Identifier: BSD-2-Clause-Patent
// Pad 5 PM8150 RTC and PM8150B FG Gen4, through SPMI v5 EE0 observer reads.
// No regulator, charger, fuel-gauge SRAM or RTC register is written.
#include <IOKit/IOLib.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/pwr_mgt/IOPMPowerSource.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSSymbol.h>
#include "NabuPowerReadings.h"

extern "C" {
vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
void hakios_spmi_lock(void);
void hakios_spmi_unlock(void);
void clock_set_calendar_microtime(clock_sec_t, clock_usec_t);
}

static vm_offset_t arb_core, arb_config, arb_observer;

static uint32_t mmio_read(vm_offset_t address)
{
    return *(volatile uint32_t *)address;
}

static bool read_registers(uint32_t address, uint8_t *bytes, unsigned count)
{
    int channel = -1;
    for (unsigned i = 0; i < 512; ++i) {
        uint32_t map = mmio_read(arb_core + 0x900 + i * 4);
        if (map && ((map >> 8) & 0xfff) == (address >> 8) &&
            (channel < 0 || (mmio_read(arb_config + 0x700 + i * 4) & 7) == 0))
            channel = i;
    }
    if (channel < 0) {
        IOLog("NABU PMIC: no observer channel for address=%#x\n", address);
        return false;
    }
    vm_offset_t observer = arb_observer + 0x80UL * channel;
    uint64_t interval;
    nanoseconds_to_absolutetime(2000000, &interval);
    hakios_spmi_lock();
    uint64_t started = mach_absolute_time();
    *(volatile uint32_t *)observer = (1u << 27) | ((address & 255) << 4) | (count - 1);
    __asm__ volatile("dsb sy" ::: "memory");
    uint32_t status;
    do {
        status = mmio_read(observer + 8);
    } while (!(status & 1) && mach_absolute_time() - started < interval);
    bool ok = (status & 15) == 1;
    if (ok) {
        uint32_t data = mmio_read(observer + 0x18);
        for (unsigned i = 0; i < count; ++i) bytes[i] = data >> (i * 8);
    }
    hakios_spmi_unlock();
    if (!ok) IOLog("NABU PMIC: read address=%#x channel=%d status=%#x\n", address, channel, status);
    return ok;
}

class NabuBattery : public IOPMPowerSource {
    OSDeclareDefaultStructors(NabuBattery);
public:
    void report(const NabuPowerSample &sample);
};
OSDefineMetaClassAndStructors(NabuBattery, IOPMPowerSource);

void NabuBattery::report(const NabuPowerSample &s)
{
    setBatteryInstalled(s.present);
    setExternalConnected(s.external);
    setExternalChargeCapable(s.external);
    setIsCharging(s.charging);
    setCurrentCapacity(s.percent);
    setMaxCapacity(100);
    setVoltage(s.voltage_mv);
    setAmperage(s.current_ma);
    setTimeRemaining(-1);
    const OSSymbol *key = OSSymbol::withCString("FullyCharged");
    setPSProperty(key, s.full ? kOSBooleanTrue : kOSBooleanFalse);
    key->release();
    key = OSSymbol::withCString("AppleRawExternalConnected");
    setPSProperty(key, s.external ? kOSBooleanTrue : kOSBooleanFalse);
    key->release();
    // The board's battery profile specifies 8720 mAh. Learned capacity and
    // temperature require FG SRAM access; do not manufacture those values.
    key = OSSymbol::withCString("DesignCapacity");
    OSNumber *capacity = OSNumber::withNumber(8720, 32);
    setPSProperty(key, capacity);
    key->release();
    capacity->release();
    updateStatus();
}

static NabuBattery *battery;
static thread_call_t poll_call;
static unsigned samples;
static uint32_t previous_rtc;
static uint64_t rtc_offset;

static void poll_power(thread_call_param_t, thread_call_param_t)
{
    NabuPowerSample sample;
    if (nabu_read_power(read_registers, &sample)) {
        if (!battery) {
            NabuBattery *made = new NabuBattery;
            IOService *platform = IOService::getPlatform();
            if (made && made->init() && made->attach(platform) && made->start(platform)) {
                made->setName("NabuBattery");
                made->report(sample);
                made->registerService();
                battery = made;
                IOLog("NABU BATTERY: IOPMPowerSource published from FG Gen4\n");
            } else {
                IOLog("NABU BATTERY: service start failed\n");
                if (made) {
                    if (made->getProvider()) made->detach(platform);
                    made->release();
                }
            }
        } else battery->report(sample);
        if (samples++ % 6 == 0)
            IOLog("NABU BATTERY: sample=%u MSOC=%u percent=%u voltage=%umV current=%dmA present=%u USB=%u charging=%u full=%u state=%u\n",
                  samples, sample.raw_soc, sample.percent, sample.voltage_mv, sample.current_ma,
                  sample.present, sample.external, sample.charging, sample.full, sample.charger_state);
    } else IOLog("NABU BATTERY: no coherent hardware sample; no values published\n");

    uint32_t raw;
    if (nabu_read_rtc(read_registers, &raw)) {
        if (samples <= 2 || samples % 6 == 1)
            IOLog("NABU RTC: counter=%u delta=%u calibrated-UTC=%llu\n", raw, raw - previous_rtc, raw + rtc_offset);
        previous_rtc = raw;
    }
    uint64_t deadline;
    clock_interval_to_deadline(5, NSEC_PER_SEC, &deadline);
    thread_call_enter_delayed(poll_call, deadline);
}

extern "C" void nabu_power_start(void)
{
    arb_core = ml_io_map(0x0c440000, 0x1100);
    arb_config = ml_io_map(0x0c40a000, 0x1000);
    arb_observer = ml_io_map(0x0e600000, 0x10000);
    if (!arb_core || !arb_config || !arb_observer) {
        IOLog("NABU PMIC: arbiter mapping failed\n");
        return;
    }
    uint32_t version = mmio_read(arb_core);
    IOLog("NABU PMIC: observer arbiter=%#x EE0\n", version);
    if (version < 0x50000000 || version >= 0x70000000) return;
    for (unsigned sid = 0; sid <= 4; sid += 2) {
        uint8_t revision[4];
        if (read_registers((sid << 16) | 0x0102, revision, 4))
            IOLog("NABU PMIC: slave=%u revision=%u.%u type=%#x subtype=%#x\n",
                  sid, revision[1], revision[0], revision[2], revision[3]);
    }

    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    OSData *offset = chosen ? OSDynamicCast(OSData, chosen->getProperty("nabu-rtc-offset")) : nullptr;
    uint32_t raw;
    if (offset && offset->getLength() == sizeof(rtc_offset) && nabu_read_rtc(read_registers, &raw)) {
        memcpy(&rtc_offset, offset->getBytesNoCopy(), sizeof(rtc_offset));
        // The existing calendar was initialized by bsd_init before vfsinit
        // loads this kmod. The kernel API updates both calendar and platform.
        clock_set_calendar_microtime(raw + rtc_offset, 0);
        previous_rtc = raw;
        IOLog("NABU RTC: system calendar set from PM8150 counter=%u offset=%llu UTC=%llu\n",
              raw, rtc_offset, raw + rtc_offset);
    } else IOLog("NABU RTC: calendar not set: calibration or hardware read missing\n");
    if (chosen) chosen->release();

    uint8_t subtype;
    if (!read_registers(0x24005, &subtype, 1) || subtype != 0x10) {
        IOLog("NABU BATTERY: FG Gen4 SOC peripheral not available\n");
        return;
    }
    poll_call = thread_call_allocate_with_priority(poll_power, nullptr, THREAD_CALL_PRIORITY_KERNEL);
    thread_call_enter(poll_call);
}
