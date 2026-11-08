// SPDX-License-Identifier: BSD-2-Clause-Patent
// Original WCD934x SLIM addresses, paged registers and digital bring-up.
#pragma once
#include <stdint.h>

namespace NabuTavil {
struct Result {
    uint32_t phase=0,step=0,error=0;
    uint16_t major=0,minor=0;
    uint8_t pgd=0,ifd=0;
    bool identified=false;
};
template<class Bus> class Codec {
    enum Phase { Idle, Pgd, Ifd, Program, Page, Write, Delay, Minor, Major, Ready, Failed };
    struct Setting {uint16_t reg;uint8_t value,delay_ms;};
    static constexpr Setting setup[]={{0x0009,1,0},{0x071b,0x19,0},{0x071c,0x15,1},
        {0x0011,5,0},{0x0011,7,0},{0x0009,3,0},{0x0009,7,0},{0x0011,3,0}};
    Bus &bus;Result r{};uint16_t page=0xffff;uint32_t due=0;
    void phase(Phase p) {r.phase=p;}
public:
    constexpr explicit Codec(Bus &owner):bus(owner) {}
    void begin() {
        const uint8_t ea[]={0,1,0x50,2,0x17,2};phase(Pgd);bus.address(ea);
    }
    void step(uint32_t now) {
        if(r.phase==Idle||r.phase==Ready||r.phase==Failed)return;
        if(bus.result().error) {r.error=bus.result().error;phase(Failed);return;}
        switch(r.phase) {
        case Pgd:
            if(bus.done()) {r.pgd=bus.data()[0];const uint8_t ea[]={0,0,0x50,2,0x17,2};bus.address(ea);phase(Ifd);}break;
        case Ifd:
            if(bus.done()) {r.ifd=bus.data()[0];phase(Program);}break;
        case Program:
            if(r.step==sizeof(setup)/sizeof(setup[0])) {bus.read_element(r.pgd,0x821,2);phase(Minor);}
            else if(page!=(setup[r.step].reg>>8)) {bus.write_element(r.pgd,0x800,uint8_t(setup[r.step].reg>>8));phase(Page);}
            else {bus.write_element(r.pgd,uint16_t(0x800+(setup[r.step].reg&255)),setup[r.step].value);phase(Write);}
            break;
        case Page:
            if(bus.done()) {page=setup[r.step].reg>>8;phase(Program);}break;
        case Write:
            if(bus.done()) {due=now+setup[r.step].delay_ms;++r.step;phase(Delay);}break;
        case Delay:
            if(now>=due)phase(Program);break;
        case Minor:
            if(bus.done()) {r.minor=uint16_t(bus.data()[0])|uint16_t(bus.data()[1])<<8;bus.read_element(r.pgd,0x823,2);phase(Major);}break;
        case Major:
            if(bus.done()) {
                r.major=uint16_t(bus.data()[0])|uint16_t(bus.data()[1])<<8;r.identified=r.major==0x108;
                if(!r.identified)r.error=0x100;
                phase(r.identified?Ready:Failed);
            }break;
        default:break;
        }
    }
    bool done() const {return r.phase==Ready||r.phase==Failed;}
    const Result &result() const {return r;}
};
} // namespace NabuTavil
