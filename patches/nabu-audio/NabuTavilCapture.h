// SPDX-License-Identifier: GPL-2.0-only
// Nabu main microphone: ADC1/DEC6, SLIM port6/channel134, original1.1 setup.
#pragma once
#include "NabuTavilData.h"
namespace NabuTavilCapture {
struct Result {
    uint32_t phase=0,index=0,error=0,reg=0,value=0,operations=0,starts=0,stops=0;
    bool initialized=false,active=false,stopped=false;
};
template<class Codec,class Bus> class Route {
    enum Phase {Idle,Initialize,Ready,Starting,Active,Stopping,Failed};
    Codec &codec;Bus &bus;Result r{};
    const NabuTavilData::Op *ops=nullptr;unsigned count=0;
    uint32_t due=0;bool waiting=false;
    template<unsigned N>void sequence(Phase p,const NabuTavilData::Op(&items)[N]) {
        r.phase=p;r.index=0;ops=items;count=N;waiting=false;due=0;
    }
    bool issue(const NabuTavilData::Op &o) {
        using namespace NabuTavilData;
        uint8_t pgd=codec.result().pgd;uint8_t p[6]{};
        switch(o.kind) {
        case Update:return codec.modify(o.reg,o.mask,uint8_t(o.value));
        case Read:return codec.modify(o.reg,0,0,true);
        case Word:return codec.write_word(o.reg,o.value);
        case Interface:return bus.write_element(codec.result().ifd,uint16_t(0x800+o.reg),uint8_t(o.value));
        case Connect:p[0]=pgd;p[1]=6;p[2]=134;return bus.user(0x2c,p,4,3);
        case Define:
            p[0]=pgd&31;p[1]=0x24;p[2]=0x20;p[3]=0x83;p[5]=134;
            return bus.user(0x21,p,6,4); //48k=4000*3*2^2, HARD_ISO,16bits
        case Reconfigure:p[1]=pgd;return bus.user(0x24,p,2,0);
        case Remove:p[0]=uint8_t(0x80|(pgd&31));p[2]=134;return bus.user(0x23,p,3,1);
        case Disconnect:p[0]=pgd;p[1]=6;return bus.user(0x2e,p,3,2);
        }
        return false;
    }
public:
    constexpr Route(Codec &c,Bus &b):codec(c),bus(b) {}
    void begin() {sequence(Initialize,NabuTavilData::Initialize);}
    void start() {if(r.phase==Ready) {r.stopped=false;sequence(Starting,NabuTavilData::Start);}}
    void stop() {if(r.phase==Active||r.phase==Starting)sequence(Stopping,NabuTavilData::Stop);}
    void step(uint32_t now) {
        if(r.phase==Idle||r.phase==Ready||r.phase==Active||r.phase==Failed)return;
        if(codec.result().error||bus.result().error) {r.error=codec.result().error?codec.result().error:bus.result().error;r.phase=Failed;return;}
        if(waiting) {
            const auto &o=ops[r.index];
            bool finished=o.kind<=NabuTavilData::Read?codec.operation_done():bus.done();
            if(!finished)return;
            r.reg=o.reg;r.value=o.kind==NabuTavilData::Read?codec.value():o.value;
            if(o.kind==NabuTavilData::Read&&(r.value&o.mask)!=(o.value&o.mask)) {r.error=0x201;r.phase=Failed;return;}
            waiting=false;due=now+o.delay;++r.index;++r.operations;
        }
        if(now<due)return;
        if(r.index==count) {
            if(r.phase==Initialize) {r.initialized=true;r.phase=Ready;}
            else if(r.phase==Starting) {r.active=true;++r.starts;r.phase=Active;}
            else {r.active=false;r.stopped=true;++r.stops;r.phase=Ready;}
            return;
        }
        waiting=issue(ops[r.index]);
    }
    bool ready()const {return r.phase==Ready;}
    const Result &result()const{return r;}
};
}
