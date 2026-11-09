// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <IOKit/IORegistryEntry.h>
#include <IOKit/IODeviceTreeSupport.h>
#include "NabuBacklight.h"

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);

namespace {
IOLock *power_lock;
bool nabu;
struct Pins {
    volatile uint32_t *base;
    uint32_t config[2], output[2];
    uint32_t read(unsigned pin, unsigned reg) { return base[(pin * 0x1000 + reg) / 4]; }
    void write(unsigned pin, unsigned reg, uint32_t value) {
        base[(pin * 0x1000 + reg) / 4] = value;
        __asm__ volatile("dsb sy" ::: "memory");
    }
    void take() {
        for (unsigned i = 0; i < 2; ++i) { config[i] = read(i, 0); output[i] = read(i, 4) & 2; }
    }
    void restore() {
        for (unsigned i = 0; i < 2; ++i) write(i, 4, output[i]);
        for (unsigned i = 0; i < 2; ++i) write(i, 0, config[i]);
    }
    void line(bool scl, bool high) {
        unsigned pin = scl ? 1 : 0;
        write(pin, 4, 0);
        write(pin, 0, 3 | (high ? 0 : 0x200)); // input releases; output drives LOW only
    }
    bool level(bool scl) { return (read(scl ? 1 : 0, 4) & 1) != 0; }
    void delay_us(unsigned us) { IODelay(us); }
} pins;
}

extern "C" void nabu_backlight_init(void) {
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    nabu = chosen && chosen->getProperty("nabu-panel-size-um");
    if (chosen) chosen->release();
    if (!nabu) return;
    // Live nabu DT: I2C at 0x880000, address 0x11; GPIO0 SDA / GPIO1 SCL.
    // SM8150 pinctrl places GPIO0/1 in the SOUTH tile at 0x03d00000.
    pins.base = reinterpret_cast<volatile uint32_t *>(ml_io_map(0x03d00000, 0x2000));
    power_lock = IOLockAlloc();
    IOLog("NABU BACKLIGHT: KTZ8866 GPIO0/1 control %s; firmware brightness retained\n",
        pins.base && power_lock ? "ready" : "unavailable");
}

extern "C" IOReturn nabu_backlight_set_power(bool on) {
    if (!nabu) return kIOReturnSuccess;
    if (!pins.base || !power_lock) return kIOReturnNotReady;
    IOLockLock(power_lock);
    NabuBacklight::Bus<Pins> bus(pins);
    uint8_t before = 0, after = 0;
    bool ok = NabuBacklight::set_power(bus, on, before, after);
    IOLog("NABU BACKLIGHT: request=%s BL_EN=%#x->%#x result=%s bus-error=%u\n",
        on ? "on" : "off", before, after, ok ? "verified" : "failed", unsigned(bus.error()));
    IOLockUnlock(power_lock);
    return ok ? kIOReturnSuccess : kIOReturnIOError;
}
