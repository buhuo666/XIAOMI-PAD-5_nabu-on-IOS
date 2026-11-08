// SPDX-License-Identifier: BSD-2-Clause-Patent
// Serialized SLIM NGD register messages. QMI ACTIVE must precede begin().
// RX uses the vendor's RX_MSG register path, with RX-message status enabled.
#pragma once
#include <stdint.h>

namespace NabuSlimNgd {
enum Error { Ok, Hardware, BadMessage, Timeout, Busy, AddressMissing };
struct Result {
    uint32_t version=0,bank=0,status=0,interrupt=0,tx=0,rx=0;
    uint32_t last_tx0=0,last_rx0=0,ie=0,ve=0;
    bool capability=false,reported=false,ready=false,stopped=false;
    Error error=Ok;
};
template<class IO> class Bus {
    IO &io;Result r{};
    uint32_t saved_cfg=0,saved_irq=0,saved_timeout=0,now=0,started=0,sent_at=0;
    uint8_t next_tid=1,tid=0,reply_code=0,expected=0,ea[6]{},reply[16]{};
    bool running=false,busy=false,tx_done=false,rx_done=false,completed=false,reporting=false;
    uint32_t read(uint32_t reg) {return io.read(r.bank+reg);}
    void write(uint32_t reg,uint32_t value) {io.write(r.bank+reg,value);}
    void fail(Error error) {if(r.error==Ok)r.error=error;busy=false;completed=false;}
    static uint32_t word(const uint8_t *p) {return uint32_t(p[0])|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;}
    bool send(uint8_t *p,uint32_t bytes,uint8_t code=0,uint8_t length=0) {
        if(busy) {fail(Busy);return false;}
        if(r.error!=Ok)return false;
        busy=true;tx_done=false;rx_done=code==0;completed=false;
        reply_code=code;expected=length;sent_at=now;
        r.last_tx0=word(p);
        for(unsigned i=0;i<(bytes+3)/4;++i)write(0x30+i*4,word(p+i*4));
        ++r.tx;return true;
    }
    void receive(const uint8_t *p,uint32_t bytes) {
        if(bytes<3) {fail(BadMessage);return;}
        uint8_t type=p[0]>>5,code=p[1];
        if(type==6&&code==0) {r.capability=true;return;}
        if(!busy||bytes<4||p[3]!=tid||code!=reply_code)return;
        if(code==0x0e&&type==6) {
            if(bytes<11) {fail(BadMessage);return;}
            bool nonzero=false;for(unsigned i=0;i<6;++i)nonzero|=p[4+i]!=0;
            if(!nonzero) {fail(AddressMissing);return;}
            for(unsigned i=0;i<6;++i)if(p[4+i]!=ea[i]) {fail(BadMessage);return;}
            reply[0]=p[10];rx_done=true;
        } else if(code==0x64&&type==0) {
            if(bytes<4+expected) {fail(BadMessage);return;}
            for(unsigned i=0;i<expected;++i)reply[i]=p[4+i];
            rx_done=true;
        }
    }
public:
    constexpr explicit Bus(IO &owner):io(owner) {}
    void begin(uint32_t ms) {
        now=started=ms;r.version=io.read(0)>>16;r.bank=r.version?0x1000:0x800;
        saved_cfg=read(0);saved_irq=read(0x10);saved_timeout=read(8);
        write(0x18,read(0x14));write(0x10,0xfe000000);write(8,saved_timeout|0x10000);
        write(0,1);running=true;r.status=read(4);
        // A retained logical address is a usable already-enumerated NGD.
        // It is kept distinct from a new observed capability exchange.
        r.ready=(r.status&2)!=0;
    }
    void step(uint32_t ms) {
        if(!running||r.error!=Ok)return;
        now=ms;r.status=read(4);r.interrupt=read(0x14);
        if(r.interrupt&0x2e000000) {
            r.ie=read(0xf0);r.ve=read(0x100);write(0x18,r.interrupt);fail(Hardware);return;
        }
        if(r.interrupt&0x80000000) {write(0x18,0x80000000);tx_done=true;}
        if(r.interrupt&0x40000000) {
            uint8_t p[32]{};r.last_rx0=read(0x70);uint32_t bytes=r.last_rx0&31;
            for(unsigned i=0;i<(bytes+3)/4;++i) {
                uint32_t v=i?read(0x70+i*4):r.last_rx0;
                for(unsigned j=0;j<4;++j)p[i*4+j]=uint8_t(v>>(j*8));
            }
            write(0x18,0x40000000);++r.rx;receive(p,bytes);
        }
        if(busy&&tx_done&&rx_done) {
            busy=false;completed=true;
            if(reporting) {reporting=false;r.reported=true;r.ready=true;}
        }
        if(busy&&now-sent_at>=1000) {fail(Timeout);return;}
        if(r.capability&&!r.reported&&!busy&&!completed) {
            uint8_t p[8]={0xc7,1,0xff,0xd9,0xc5,1,1,0};
            reporting=send(p,7);
        }
        if(!r.ready&&now-started>=1000)fail(Timeout);
    }
    bool address(const uint8_t *address) {
        tid=next_tid++;uint8_t p[12]={0x4a,0x0d,0xff,tid};
        for(unsigned i=0;i<6;++i)ea[i]=p[4+i]=address[i];
        return send(p,10,0x0e,1);
    }
    bool read_element(uint8_t la,uint16_t offset,uint8_t bytes) {
        // The codec control path uses byte and little-endian word elements.
        if(bytes!=1&&bytes!=2) {fail(BadMessage);return false;}
        tid=next_tid++;uint16_t ec=uint16_t((offset<<4)|8|(bytes-1));
        uint8_t p[8]={6,0x60,la,tid,uint8_t(ec),uint8_t(ec>>8)};
        return send(p,6,0x64,bytes);
    }
    bool write_element(uint8_t la,uint16_t offset,uint8_t value) {
        uint16_t ec=uint16_t((offset<<4)|8);
        uint8_t p[8]={6,0x68,la,uint8_t(ec),uint8_t(ec>>8),value};return send(p,6);
    }
    bool idle() const {return !busy;}
    bool done() const {return completed;}
    const uint8_t *data() const {return reply;}
    const Result &result() const {return r;}
    void stop() {
        if(!running)return;
        write(0,0);write(0x10,saved_irq);write(8,saved_timeout);write(0,saved_cfg);
        running=false;r.stopped=true;
    }
};
} // namespace NabuSlimNgd
