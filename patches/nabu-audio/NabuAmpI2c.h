// SPDX-License-Identifier: BSD-2-Clause-Patent
// Nabu CS35L41 control transactions: GPIO98 SDA, GPIO99 SCL, open drain.
#pragma once
#include <stdint.h>

namespace NabuAmpI2c {
enum Error { Ok, BusNotIdle, ClockHeldLow, AddressNack, RegisterNack, ReadAddressNack };
template<class Pins> class Bus {
    Pins &pins;
    Error failure=Ok;
    void delay() {pins.delay_us(5);}
    bool clock_high() {
        pins.line(true,true);
        for(unsigned i=0;i<100;++i) {if(pins.level(true))return true;delay();}
        failure=ClockHeldLow;return false;
    }
    bool start() {
        pins.line(false,true);delay();
        if(!clock_high())return false;
        delay();pins.line(false,false);delay();pins.line(true,false);delay();return true;
    }
    bool stop() {
        pins.line(true,false);pins.line(false,false);delay();
        bool ok=clock_high();delay();pins.line(false,true);delay();return ok;
    }
    bool bit(bool out,bool &in) {
        pins.line(false,out);delay();
        if(!clock_high())return false;
        delay();in=pins.level(false);pins.line(true,false);delay();return true;
    }
    bool write(uint8_t value,Error nack) {
        bool sample;
        for(int i=7;i>=0;--i)if(!bit((value>>i)&1,sample))return false;
        if(!bit(true,sample))return false;
        if(sample) {failure=nack;return false;}
        return true;
    }
    bool read(uint8_t &value,bool more) {
        value=0;bool sample;
        for(unsigned i=0;i<8;++i) {
            if(!bit(true,sample))return false;
            value=uint8_t(value<<1)|sample;
        }
        return bit(!more,sample);
    }
public:
    explicit Bus(Pins &io):pins(io) {}
    bool read_register(uint8_t address,uint32_t reg,uint32_t &value) {
        failure=Ok;value=0;pins.take();
        pins.line(false,true);pins.line(true,true);delay();
        if(!pins.level(false)||!pins.level(true)) {failure=BusNotIdle;pins.restore();return false;}
        bool ok=start()&&write(uint8_t(address<<1),AddressNack);
        for(int shift=24;ok&&shift>=0;shift-=8)ok=write(uint8_t(reg>>shift),RegisterNack);
        if(ok)ok=start()&&write(uint8_t((address<<1)|1),ReadAddressNack);
        for(unsigned i=0;ok&&i<4;++i) {uint8_t byte;ok=read(byte,i<3);if(ok)value=(value<<8)|byte;}
        bool stopped=stop();pins.restore();return ok&&stopped;
    }
    Error error() const {return failure;}
};
} // namespace NabuAmpI2c
