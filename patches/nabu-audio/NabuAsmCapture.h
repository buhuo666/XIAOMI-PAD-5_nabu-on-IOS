// SPDX-License-Identifier: BSD-2-Clause-Patent
// Original AFE SLIMBUS0_TX -> live ADM -> ASM2/1 mono48k/S16 capture.
// Uses the second16KiB of the caller's shared32KiB map; never owns/unmaps it.
#pragma once
#include <stdint.h>
namespace NabuAsmCapture {
static constexpr uint16_t AfePort=0x4001,StreamPort=0x201;
static constexpr uint32_t Offset=16384,PeriodBytes=4096,SampleBytes=1920,Periods=4;
inline uint16_t u16(const uint8_t *p){return uint16_t(p[0])|uint16_t(p[1])<<8;}
inline uint32_t u32(const uint8_t *p){return uint32_t(u16(p))|uint32_t(u16(p+2))<<16;}
inline void p16(uint8_t *p,uint16_t v){p[0]=uint8_t(v);p[1]=uint8_t(v>>8);}
inline void p32(uint8_t *p,uint32_t v){p16(p,uint16_t(v));p16(p+2,uint16_t(v>>16));}
struct Descriptor {uint32_t address,type,mask;uint16_t scale;};
// Original wcd934x.c audio_reg_cfg: one20-byte descriptor per16-byte parameter header.
static constexpr Descriptor Registers[]={
    {0xa81,4,1,0},{0xa85,7,15,0},{0xa86,10,1,0},{0xc01,13,2,0},
    {0xc24,18,1,0},{0xc2c,23,1,0},{0xc34,28,1,0},
    {0x850,33,0x1e,1},{0x850,34,1,1},{0x840,35,0x1e,1},{0x840,36,1,1},
    {0x120b,41,4,0},{0x120b,42,8,0},{0x120e,43,0xff,0},
    {0x900,37,0xff,4},{0x901,38,0xff,4},{0x980,39,0xff,4},{0x981,40,0xff,4}};
struct Result {
    uint32_t phase=0,registers=0,commands=0,reads=0,completed=0,bytes=0,pending=0;
    uint32_t copp=0xffff,failed_opcode=0,status=0,ignored=0,starts=0,stops=0;
    bool configured=false,asm_sent=false,asm_open=false,formatted=false,adm_open=false,routed=false;
    bool port_sent=false,port_on=false,run=false,closed=false,copp_closed=false,port_stopped=false;
    bool failed=false,timeout=false,mapping_retained=false;
};
template<class IO>class Stream {
    enum Phase {Idle,RegistersConfig,PageConfig,SlaveConfig,RegistersInit,Ready,
        AsmOpen,Format,AdmOpen,Route,Island,PortConfig,PortStart,Run,Data,Close,CoppClose,PortStop,Failed};
    IO &io;Result r{};uint64_t address=0;uint32_t handle=0,now=0,since=0,last_read=0;
    uint32_t next=0x60000001,command=0,token=0,read_token[Periods]{};
    uint16_t port=0;uint8_t service=0;bool waiting=false,stopping=false,timing=false;
    void phase(Phase p) {r.phase=p;waiting=false;timing=false;}
    bool cleaning()const{return r.phase==Close||r.phase==CoppClose||r.phase==PortStop;}
    void stopped() {r.run=false;r.pending=0;++r.stops;phase(r.failed?Failed:Ready);}
    void after_copp() {
        if(r.port_sent&&!r.port_stopped)phase(PortStop);
        else stopped();
    }
    void after_close() {
        if(r.adm_open&&!r.copp_closed)phase(CoppClose);
        else after_copp();
    }
    void close() {if(r.asm_sent&&!r.closed)phase(Close);else after_close();}
    void fail(uint32_t opcode,uint32_t status,bool timeout=false) {
        if(!r.failed) {r.failed=true;r.failed_opcode=opcode;r.status=status;}
        r.timeout|=timeout;
        if(r.phase==Close) {r.mapping_retained=true;after_close();}
        else if(r.phase==CoppClose)after_copp();
        else if(r.phase==PortStop)stopped();
        else if(r.phase<Ready)phase(Failed);
        else close();
    }
    static uint8_t *param(uint8_t *p,bool per_port,uint32_t module,uint32_t id,uint32_t bytes) {
        if(per_port) {p16(p,AfePort);p32(p+16,16+bytes);p+=20;}
        else {p32(p+12,16+bytes);p+=16;}
        p32(p,module);p32(p+8,id);p32(p+12,bytes);return p+16;
    }
    void control() {
        uint8_t payload[64]{};uint8_t *p=payload;uint32_t bytes=0;
        service=4;port=0;command=0x100fc;
        switch(r.phase) {
        case RegistersConfig: {
            const auto &d=Registers[r.registers];bytes=52;p=param(payload,false,0x10234,0x10236,20);
            p32(p,1);p32(p+4,d.address);p32(p+8,d.type);p32(p+12,d.mask);p16(p+16,8);p16(p+18,d.scale);break;
        }
        case PageConfig:
            bytes=44;p=param(payload,false,0x10234,0x10296,12);p32(p,1);p32(p+4,1);p32(p+8,1);break;
        case SlaveConfig:
            bytes=48;p=param(payload,false,0x10234,0x10235,16);p32(p,1);p32(p+4,0x02500100);p32(p+8,0x217);p16(p+14,16);break;
        case RegistersInit:bytes=32;param(payload,false,0x10234,0x10237,0);break;
        case AsmOpen:
            service=7;port=StreamPort;command=0x10db4;bytes=20;
            p32(p+8,0x10c68);p32(p+12,0x10da5);p16(p+16,16);break;
        case Format:
            service=7;port=StreamPort;command=0x10c10;bytes=36;
            p32(p,0x10da3);p32(p+4,28);p32(p+12,20);p16(p+16,1);p16(p+18,16);
            p32(p+20,48000);p16(p+24,1);p[28]=3;break;
        case AdmOpen:
            service=8;port=AfePort;command=0x10326;bytes=28;
            p16(p+2,2);p16(p+4,AfePort);p16(p+6,0xffff);p32(p+8,0x10312);
            p16(p+12,1);p16(p+14,16);p32(p+16,48000);p[20]=3;break;
        case Route:
            service=8;command=0x10325;bytes=16;p32(p,1);p32(p+4,1);p16(p+8,2);p16(p+10,1);p16(p+12,uint16_t(r.copp));break;
        case Island:
            command=0x100fa;bytes=44;p=param(payload,true,0x1020c,0x102b4,8);p32(p,1);break;
        case PortConfig:
            command=0x100fa;bytes=60;p=param(payload,true,0x1020c,0x10212,24);
            p32(p,1);p16(p+6,16);p16(p+10,1);p[12]=134;p32(p+20,48000);break;
        case PortStart:command=0x100e5;bytes=4;p16(p,AfePort);break;
        case Run:service=7;port=StreamPort;command=0x10daa;bytes=12;break;
        case Close:service=7;port=StreamPort;command=0x10bcd;break;
        case CoppClose:service=8;port=uint16_t(r.copp);command=0x10327;break;
        case PortStop:command=0x100e6;bytes=4;p16(p,AfePort);break;
        default:return;
        }
        if(!io.capture_send(service,port,command,next,payload,bytes))return;
        token=next++;waiting=true;++r.commands;
        if(r.phase==AsmOpen)r.asm_sent=true;
        if(r.phase==PortStart)r.port_sent=true;
    }
    void reads() {
        for(unsigned i=0;i<Periods;++i)if(!(r.pending&(1u<<i))) {
            uint64_t at=address+i*PeriodBytes;uint8_t p[20]{};
            p32(p,uint32_t(at));p32(p+4,uint32_t(at>>32));p32(p+8,handle);p32(p+12,SampleBytes);p32(p+16,r.reads+1);
            uint32_t t=0x40000000u|((r.reads+1)&0x0fffffff);
            if(!io.capture_send(7,StreamPort,0x10dac,t,p,sizeof(p)))return;
            read_token[i]=t;r.pending|=1u<<i;++r.reads;
        }
    }
public:
    constexpr explicit Stream(IO &owner):io(owner) {}
    void prepare(uint64_t base,uint32_t mapped,uint32_t ms) {address=base+Offset;handle=mapped;now=ms;phase(RegistersConfig);}
    void start() {
        if(r.phase!=Ready)return;
        r.asm_sent=r.asm_open=r.formatted=r.adm_open=r.routed=false;
        r.port_sent=r.port_on=r.run=r.closed=r.copp_closed=r.port_stopped=false;
        r.copp=0xffff;r.pending=0;stopping=false;++r.starts;phase(AsmOpen);
    }
    void finish() {stopping=true;if(!waiting&&r.phase>=AsmOpen&&r.phase<=Data)close();}
    bool receive(const uint8_t *data,uint32_t bytes,uint32_t ms) {
        if(bytes<20)return false;
        uint32_t t=u32(data+12);
        if((t&0xf0000000u)!=0x60000000u&&(t&0xf0000000u)!=0x40000000u)return false;
        now=ms;uint16_t field=u16(data);uint32_t h=((field>>4)&15)*4,total=u16(data+2);
        if((field&15)>1||h<20||total<h||total>bytes||data[4]!=data[8]||data[5]!=4||data[9]!=5) {++r.ignored;return true;}
        uint32_t op=u32(data+16),n=total-h;const uint8_t *p=data+h;
        uint16_t src=u16(data+6),dst=u16(data+10);
        if(data[4]==7&&src==StreamPort&&dst==StreamPort&&(t&0xf0000000u)==0x40000000u) {
            for(unsigned i=0;i<Periods;++i)if((r.pending&(1u<<i))&&read_token[i]==t) {
                uint64_t at=address+i*PeriodBytes;
                if(op==0x110e8&&n>=8&&u32(p)==0x10dac&&u32(p+4)) {if(!cleaning())fail(op,u32(p+4));return true;}
                if(op!=0x10d9a||n<44||u32(p+4)!=uint32_t(at)||u32(p+8)!=uint32_t(at>>32)||u32(p+12)!=handle) {++r.ignored;return true;}
                r.pending&=~(1u<<i);
                if(u32(p)) {if(!cleaning())fail(op,u32(p));return true;}
                uint32_t size=u32(p+16),offset=u32(p+20);
                if(offset>SampleBytes||size>SampleBytes-offset||(size&1)||(offset&1)||(u32(p+32)&0x40000000)) {if(!cleaning())fail(op,0xfffffffe);return true;}
                ++r.completed;r.bytes+=size;last_read=now;
                if(!stopping&&r.phase==Data)io.capture_data(i,offset,size);
                return true;
            }
            ++r.ignored;return true;
        }
        if(!waiting||t!=token||data[4]!=service||dst!=port||(r.phase!=AdmOpen&&src!=port)) {++r.ignored;return true;}
        if(r.phase==AdmOpen&&op==0x10329&&n>=8) {
            if(u32(p))fail(command,u32(p));else {r.copp=u16(p+4);r.adm_open=true;phase(Route);}return true;
        }
        if(op!=0x110e8||n<8||u32(p)!=command) {++r.ignored;return true;}
        if(u32(p+4)) {fail(command,u32(p+4));return true;}
        switch(r.phase) {
        case RegistersConfig:if(++r.registers==18)phase(PageConfig);else phase(RegistersConfig);break;
        case PageConfig:phase(SlaveConfig);break;
        case SlaveConfig:phase(RegistersInit);break;
        case RegistersInit:r.configured=true;phase(Ready);break;
        case AsmOpen:r.asm_open=true;phase(Format);break;
        case Format:r.formatted=true;phase(AdmOpen);break;
        case AdmOpen:break;
        case Route:r.routed=true;phase(Island);break;
        case Island:phase(PortConfig);break;
        case PortConfig:phase(PortStart);break;
        case PortStart:r.port_on=true;phase(Run);break;
        case Run:r.run=true;last_read=now;phase(Data);break;
        case Close:r.closed=true;r.asm_open=false;r.pending=0;after_close();break;
        case CoppClose:r.copp_closed=true;r.adm_open=false;after_copp();break;
        case PortStop:r.port_stopped=true;r.port_on=false;stopped();break;
        default:break;
        }
        return true;
    }
    void step(uint32_t ms) {
        now=ms;
        if(r.phase==Idle||r.phase==Ready||r.phase==Failed)return;
        if(stopping&&!waiting&&!cleaning()&&r.phase>=AsmOpen)close();
        if(r.phase==Ready||r.phase==Failed)return;
        if(!timing) {since=now;timing=true;}
        if(r.phase==Data) {
            if(now-last_read>=2000)fail(0x10dac,0xffffffff,true);else reads();return;
        }
        if(now-since>=1000) {fail(command,0xffffffff,true);return;}
        if(!waiting)control();
    }
    bool ready()const{return r.phase==Ready;}
    bool busy()const{return r.phase>=AsmOpen&&r.phase<=PortStop;}
    const Result &result()const{return r;}
};
}
