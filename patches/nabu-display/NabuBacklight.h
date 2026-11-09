// SPDX-License-Identifier: BSD-2-Clause-Patent
// KTZ8866 byte-register control, using the existing nabu open-drain I2C protocol.
#pragma once
#include <stdint.h>

namespace NabuBacklight {
enum Error { Ok, BusNotIdle, ClockHeldLow, AddressNack, RegisterNack, ReadAddressNack, DataNack };
template<class Pins> class Bus {
    Pins &pins;
    Error failure = Ok;
    void delay() { pins.delay_us(5); }
    bool clock_high() {
        pins.line(true, true);
        for (unsigned i = 0; i < 100; ++i) {
            if (pins.level(true)) return true;
            delay();
        }
        failure = ClockHeldLow;
        return false;
    }
    bool start() {
        pins.line(false, true); delay();
        if (!clock_high()) return false;
        delay(); pins.line(false, false); delay(); pins.line(true, false); delay();
        return true;
    }
    bool stop() {
        pins.line(true, false); pins.line(false, false); delay();
        bool ok = clock_high(); delay(); pins.line(false, true); delay();
        return ok;
    }
    bool bit(bool out, bool &in) {
        pins.line(false, out); delay();
        if (!clock_high()) return false;
        delay(); in = pins.level(false); pins.line(true, false); delay();
        return true;
    }
    bool write(uint8_t value, Error nack) {
        bool sample;
        for (int i = 7; i >= 0; --i)
            if (!bit((value >> i) & 1, sample)) return false;
        if (!bit(true, sample)) return false;
        if (sample) { failure = nack; return false; }
        return true;
    }
    bool read(uint8_t &value) {
        value = 0;
        bool sample;
        for (unsigned i = 0; i < 8; ++i) {
            if (!bit(true, sample)) return false;
            value = uint8_t(value << 1) | sample;
        }
        return bit(true, sample); // final byte: NACK, then STOP
    }
    bool begin() {
        failure = Ok;
        pins.take(); pins.line(false, true); pins.line(true, true); delay();
        if (!pins.level(false) || !pins.level(true)) {
            failure = BusNotIdle; pins.restore(); return false;
        }
        return true;
    }
    bool finish(bool ok) {
        bool stopped = stop(); pins.restore(); return ok && stopped;
    }
public:
    explicit Bus(Pins &io) : pins(io) {}
    bool read_register(uint8_t reg, uint8_t &value) {
        if (!begin()) return false;
        bool ok = start() && write(0x22, AddressNack) && write(reg, RegisterNack)
            && start() && write(0x23, ReadAddressNack) && read(value);
        return finish(ok);
    }
    bool write_register(uint8_t reg, uint8_t value) {
        if (!begin()) return false;
        bool ok = start() && write(0x22, AddressNack) && write(reg, RegisterNack)
            && write(value, DataNack);
        return finish(ok);
    }
    Error error() const { return failure; }
};

// BL_EN bit 6 gates the LED output independently of LCD bias and brightness.
// Read-modify-write preserves the firmware's current-sink selection. Leave
// 0x04/0x05 intact so repeated off/on cycles restore the exact previous level.
template<class Registers>
bool set_power(Registers &io, bool on, uint8_t &before, uint8_t &after) {
    if (!io.read_register(0x08, before)) return false;
    uint8_t wanted = on ? (before | 0x40) : (before & ~0x40);
    if (wanted != before && !io.write_register(0x08, wanted)) return false;
    return io.read_register(0x08, after) && after == wanted;
}
} // namespace NabuBacklight
