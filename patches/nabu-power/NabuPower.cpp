// SPDX-License-Identifier: BSD-2-Clause-Patent
// Pad 5 PM8150 RTC and PM8150B FG Gen4, through SPMI v5 EE0.
// Only FG MEMIF access controls are written; every SRAM request is released.
// No regulator, charger, SRAM data, SDAM or RTC counter is written.
#include <IOKit/IOLib.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/pwr_mgt/IOPMPowerSource.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/c++/OSString.h>
#include "NabuFgMemory.h"

extern "C" {
vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
void hakios_spmi_lock(void);
void hakios_spmi_unlock(void);
void clock_set_calendar_microtime(clock_sec_t, clock_usec_t);
}

static vm_offset_t arb_core, arb_config, arb_observer;
static vm_offset_t memif_write_channel;
static thread_call_t temperature_call;
static int temperature_centic = INT32_MIN;
static unsigned temperature_reads;

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

static bool write_memif(uint8_t offset, uint8_t value)
{
    uint64_t interval;
    nanoseconds_to_absolutetime(2000000, &interval);
    hakios_spmi_lock();
    uint64_t started = mach_absolute_time();
    *(volatile uint32_t *)(memif_write_channel + 0x10) = value;
    __asm__ volatile("dsb sy" ::: "memory");
    // SPMI v5 extended-register-write-long opcode is zero; one byte.
    *(volatile uint32_t *)memif_write_channel = (uint32_t)offset << 4;
    __asm__ volatile("dsb sy" ::: "memory");
    uint32_t status;
    do {
        status = mmio_read(memif_write_channel + 8);
    } while (!(status & 1) && mach_absolute_time() - started < interval);
    hakios_spmi_unlock();
    if ((status & 15) != 1)
        IOLog("NABU FG: MEMIF write offset=%#x status=%#x\n", offset, status);
    return (status & 15) == 1;
}

static void delay_temperature(unsigned microseconds)
{
    // The bus lock covers individual transfers, never the grant wait.
    if (microseconds >= 1000) IOSleep(microseconds / 1000);
    else IODelay(microseconds);
}

static void poll_temperature(thread_call_param_t, thread_call_param_t)
{
    uint16_t raw;
    NabuFgTransfer transfer;
    uint64_t started = mach_absolute_time(), elapsed;
    NabuFgResult result = nabu_read_temperature(read_registers, write_memif,
                                               delay_temperature, &raw, &transfer);
    absolutetime_to_nanoseconds(mach_absolute_time() - started, &elapsed);
    int temperature = result == kNabuFgOK ? nabu_temperature_centic(raw) : INT32_MIN;
    __atomic_store_n(&temperature_centic, temperature, __ATOMIC_RELEASE);
    if (result == kNabuFgOK) {
        if (temperature_reads++ % 6 == 0)
            IOLog("NABU FG: temperature raw=%#x centiC=%d grant-polls=%u elapsed-us=%llu arb-before=%#x intf-before=%#x dma-ctl-before=%#x; MEMIF released\n",
                  raw, temperature, transfer.grant_polls, elapsed / 1000,
                  transfer.arb_before, transfer.interface_before, transfer.dma_control_before);
    } else {
        IOLog("NABU FG: temperature unavailable result=%u grant-polls=%u irq=%#x dma=%#x elapsed-us=%llu arb-before=%#x intf-before=%#x dma-ctl-before=%#x\n",
              result, transfer.grant_polls, transfer.interrupt_status, transfer.dma_status, elapsed / 1000,
              transfer.arb_before, transfer.interface_before, transfer.dma_control_before);
        if (result == kNabuFgReleaseFailed) {
            IOLog("NABU FG: temperature reader stopped after MEMIF release failure\n");
            return;
        }
    }
    uint64_t deadline;
    clock_interval_to_deadline(5, NSEC_PER_SEC, &deadline);
    thread_call_enter_delayed(temperature_call, deadline);
}

static void start_temperature(unsigned pmic_major)
{
    uint8_t subtype;
    if (pmic_major != 2 || !read_registers(0x24305, &subtype, 1) || subtype != 0x0d) {
        IOLog("NABU FG: temperature requires this board's PM8150B v2 MEMIF\n");
        return;
    }
    int channel = -1;
    for (unsigned i = 0; i < 512; ++i) {
        uint32_t map = mmio_read(arb_core + 0x900 + i * 4);
        if (map && ((map >> 8) & 0xfff) == 0x243 &&
            (mmio_read(arb_config + 0x700 + i * 4) & 7) == 0)
            channel = i;
    }
    if (channel < 0) {
        IOLog("NABU FG: no EE0-owned MEMIF write channel\n");
        return;
    }
    memif_write_channel = ml_io_map(0x0c600000UL + 0x10000UL * channel, 0x1000);
    if (!memif_write_channel) return;
    temperature_call = thread_call_allocate_with_priority(poll_temperature, nullptr, THREAD_CALL_PRIORITY_KERNEL);
    IOLog("NABU FG: PM8150B v2 MEMIF channel=%d; independent temperature poll=5s\n", channel);
    thread_call_enter(temperature_call);
}

class NabuBattery : public IOPMPowerSource {
    OSDeclareDefaultStructors(NabuBattery);
public:
    void report(const NabuPowerSample &sample, const NabuGaugeHistory *history, int temperature);
};
OSDefineMetaClassAndStructors(NabuBattery, IOPMPowerSource);

void NabuBattery::report(const NabuPowerSample &s, const NabuGaugeHistory *history, int temperature)
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
    // The board's battery profile specifies 8720 mAh. Keep MSOC-based display
    // capacity normalized to 100 and publish stored learned mAh separately.
    key = OSSymbol::withCString("DesignCapacity");
    OSNumber *capacity = OSNumber::withNumber(8720, 32);
    setPSProperty(key, capacity);
    key->release();
    capacity->release();
    if (history) {
        setCycleCount(history->cycle_count);
        key = OSSymbol::withCString("AppleRawMaxCapacity");
        capacity = OSNumber::withNumber(history->learned_capacity_mah, 32);
        setPSProperty(key, capacity);
        key->release();
        capacity->release();
    }
    key = OSSymbol::withCString("Temperature");
    if (temperature != INT32_MIN) {
        OSNumber *value = OSNumber::withNumber((uint32_t)temperature, 32);
        setPSProperty(key, value);
        value->release();
    } else if (properties->getObject(key)) {
        properties->removeObject(key);
        removeProperty(key);
        settingsChangedSinceUpdate = true;
    }
    key->release();
    updateStatus();
}

static NabuBattery *battery;
static thread_call_t poll_call;
static unsigned samples;
static unsigned polls;
static bool have_sample;
static int usb_present = -1;
extern "C" int nabu_power_usb_present(void)
{ return __atomic_load_n(&usb_present, __ATOMIC_ACQUIRE); }
static int reported_temperature = INT32_MIN;
static NabuChargeStatus previous_status;
static uint32_t previous_rtc;
static uint64_t rtc_offset;

static void poll_power(thread_call_param_t, thread_call_param_t)
{
    // Check USB insertion and the SMB5 charging phase at 4 Hz. The charger
    // can stay disabled briefly after USB insertion before starting charge.
    // Read the gauge on either transition or
    // every 5 seconds, so the faster icon response does not poll all ADCs.
    int temperature = __atomic_load_n(&temperature_centic, __ATOMIC_ACQUIRE);
    bool refresh = !have_sample || polls % 20 == 0 || temperature != reported_temperature;
    NabuChargeStatus status;
    if (!refresh && nabu_read_charge_status(read_registers, &status)) {
        __atomic_store_n(&usb_present, status.external ? 1 : 0, __ATOMIC_RELEASE);
        refresh = nabu_charge_status_changed(status, previous_status);
    }
    NabuPowerSample sample;
    if (refresh && nabu_read_power(read_registers, &sample)) {
        __atomic_store_n(&usb_present, sample.external ? 1 : 0, __ATOMIC_RELEASE);
        NabuGaugeHistory history;
        bool history_valid = nabu_read_gauge_history(read_registers, &history);
        NabuChargeStatus next_status = {sample.external, sample.charger_state};
        bool transition = have_sample && nabu_charge_status_changed(next_status, previous_status);
        if (!battery) {
            NabuBattery *made = new NabuBattery;
            IOService *platform = IOService::getPlatform();
            if (made && made->init() && made->attach(platform) && made->start(platform)) {
                made->setName("NabuBattery");
                made->report(sample, history_valid ? &history : nullptr, temperature);
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
        } else battery->report(sample, history_valid ? &history : nullptr, temperature);
        if (battery && temperature != reported_temperature) {
            if (temperature != INT32_MIN)
                IOLog("NABU BATTERY: Temperature=%d centiC published\n", temperature);
            else IOLog("NABU BATTERY: Temperature removed after failed sample\n");
            reported_temperature = temperature;
        }
        if (transition)
            IOLog("NABU BATTERY: transition USB=%u->%u charger=%u->%u; power-source status updated\n",
                  previous_status.external, sample.external, previous_status.charger_state, sample.charger_state);
        if (samples++ % 6 == 0 || transition) {
            IOLog("NABU BATTERY: sample=%u MSOC=%u percent=%u voltage=%umV current=%dmA present=%u USB=%u charging=%u full=%u state=%u\n",
                  samples, sample.raw_soc, sample.percent, sample.voltage_mv, sample.current_ma,
                  sample.present, sample.external, sample.charging, sample.full, sample.charger_state);
            if (history_valid)
                IOLog("NABU FG: SDAM learned=%umAh cycles=%u buckets=%u,%u,%u,%u,%u,%u,%u,%u; power-source history published\n",
                      history.learned_capacity_mah, history.cycle_count,
                      history.cycle_buckets[0], history.cycle_buckets[1], history.cycle_buckets[2], history.cycle_buckets[3],
                      history.cycle_buckets[4], history.cycle_buckets[5], history.cycle_buckets[6], history.cycle_buckets[7]);
            else IOLog("NABU FG: SDAM read failed or initialization cookie absent; history not updated\n");
        }
        previous_status = next_status;
        have_sample = true;
    } else if (refresh) IOLog("NABU BATTERY: no coherent hardware sample; no values published\n");

    uint32_t raw;
    if (polls % 20 == 0 && nabu_read_rtc(read_registers, &raw)) {
        if (polls == 20 || polls % 120 == 0)
            IOLog("NABU RTC: counter=%u delta=%u calibrated-UTC=%llu\n", raw, raw - previous_rtc, raw + rtc_offset);
        previous_rtc = raw;
    }
    ++polls;
    uint64_t deadline;
    clock_interval_to_deadline(250, NSEC_PER_MSEC, &deadline);
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
    unsigned pmic_major = 0;
    for (unsigned sid = 0; sid <= 4; sid += 2) {
        uint8_t revision[4];
        if (read_registers((sid << 16) | 0x0102, revision, 4)) {
            IOLog("NABU PMIC: slave=%u revision=%u.%u type=%#x subtype=%#x\n",
                  sid, revision[1], revision[0], revision[2], revision[3]);
            if (sid == 2) pmic_major = revision[1];
        }
    }

    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    OSData *identity = chosen ? OSDynamicCast(OSData, chosen->getProperty("nabu-platform-uuid")) : nullptr;
    if (identity && identity->getLength() == 37) {
        // The generic ARM platform only derives UUIDs from Apple chip fields.
        // Use this port's UUID, derived from the actual Qualcomm SoC identity,
        // for the standard property and resource consumed by gethostuuid().
        OSString *uuid = OSString::withCString((const char *)identity->getBytesNoCopy());
        IOService::getPlatform()->getProvider()->setProperty("IOPlatformUUID", uuid);
        IOService::publishResource("IOPlatformUUID", uuid);
        uuid->release();
        IOLog("NABU PLATFORM: host UUID published from Qualcomm SoC identity\n");
    }
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
    start_temperature(pmic_major);
    poll_call = thread_call_allocate_with_priority(poll_power, nullptr, THREAD_CALL_PRIORITY_KERNEL);
    IOLog("NABU BATTERY: USB+charger poll=250ms; gauge poll=5s or state transition\n");
    thread_call_enter(poll_call);
}
