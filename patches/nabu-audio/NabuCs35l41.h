// SPDX-License-Identifier: GPL-2.0-only
// Nabu B2 CS35L41 protection preload only. No reset, PLL, HALO start or output.
// Protocol: MiCode audio-kernel d41f8e1a6827294af6a61adbe18544518e750166,
// cs35l41_v2/{cs35l41.c,wm_adsp.c,wmfw.h}; original code by Cirrus Logic.
#pragma once
#include <stdint.h>
#include "NabuCs35l41Data.h"

namespace NabuCs35l41 {
struct Position {
    const char *name,*coefficients;
    uint8_t address;
    uint32_t cal_r,ch_bal;
};
static constexpr Position Positions[] = {
    {"TL","TL-cs35l41-dsp1-spk-prot.bin",0x43,9301,0},
    {"TR","TR-cs35l41-dsp1-spk-prot.bin",0x41,9342,0x400000},
    {"BL","BL-cs35l41-dsp1-spk-prot.bin",0x42,9630,0},
    {"BR","BR-cs35l41-dsp1-spk-prot.bin",0x40,9717,0x400000},
};
enum Error { Ok, InvalidPosition, Io, ChipIdentity, OtpNotReady, OtpMapMissing,
    MissingFirmware, ProgramFormat, CoefficientFormat, RuntimeIdentity,
    ControlMissing, ReadbackMismatch };
enum Phase { Idle, Quiet, Probe, Trim, Configure, Program, Identity, Coefficients,
    Calibration, Verify, Complete };
struct Result {
    Error error=Ok;
    Phase phase=Idle;
    uint32_t failed_reg=0,detail=0,devid=0,revid=0,otp_id=0,devid_otp=0;
    uint32_t otp_map=0,otp_writes=0,firmware_id=0,firmware_version=0,algorithm_count=0;
    uint32_t cspl_xm=0,cspl_ym=0,pwr1=0,pwr2=0,core=0;
    uint32_t program_bytes=0,coefficient_bytes=0,program_blocks=0,coefficient_blocks=0;
    uint32_t cal_r=0,cal_status=0,cal_checksum=0,ch_bal=0;
    bool identity_verified=false,quiet=false,complete=false;
};
inline uint16_t le16(const uint8_t *p) {return uint16_t(p[0])|uint16_t(p[1])<<8;}
inline uint32_t le32(const uint8_t *p) {return uint32_t(le16(p))|uint32_t(le16(p+2))<<16;}
inline uint32_t be32(const uint8_t *p) {return uint32_t(p[0])<<24|uint32_t(p[1])<<16|uint32_t(p[2])<<8|p[3];}

// Backend owns one already selected chip and the shared-reset lifecycle:
// bool read(uint32_t reg,uint32_t &host_value), write(reg,host_value),
// raw_write(reg,const uint8_t *bus_bytes,uint32_t bytes); void delay_us(uint32_t);
// const uint8_t *firmware(const char *name,uint32_t &bytes) (borrowed bytes).
// raw_write receives at most60 bytes, preserving packed12/20-byte boundaries.
template<class Backend> class Preloader {
    Backend &io;
    Result r{};
    struct Control {uint32_t offset=0,reg=0;bool present=false;};
    Control controls[4]{};
    bool unlocked=false;
    uint32_t lock1=0xcc,lock2=0x33;
    bool fail(Error e,uint32_t reg=0,uint32_t detail=0) {
        if(r.error==Ok) {r.error=e;r.failed_reg=reg;r.detail=detail;}
        return false;
    }
    bool read(uint32_t reg,uint32_t &value) {
        return io.read(reg,value)||fail(Io,reg);
    }
    bool write(uint32_t reg,uint32_t value) {
        return io.write(reg,value)||fail(Io,reg);
    }
    bool update(uint32_t reg,uint32_t mask,uint32_t value) {
        uint32_t old;
        return read(reg,old)&&write(reg,(old&~mask)|(value&mask));
    }
    bool quiet() {
        // Each register is attempted even if an earlier bus operation fails.
        bool ok=true;
        const uint32_t regs[]={0x2014,0x2018,0x02bc1000};
        uint32_t *outputs[]={&r.pwr1,&r.pwr2,&r.core};unsigned i=0;
        for(uint32_t reg:regs) {
            uint32_t value=0,after=0;
            if(!io.read(reg,value)||!io.write(reg,value&~1u)||!io.read(reg,after)) {
                fail(Io,reg);ok=false;
            } else if(after&1) {fail(ReadbackMismatch,reg,after);ok=false;}
            *outputs[i++]=after;
        }
        if(unlocked) {
            bool first=io.write(0x40,lock1),second=io.write(0x40,lock2);
            if(!first||!second)fail(Io,0x40);
            ok=first&&second&&ok;unlocked=false;
        }
        r.quiet=ok;return ok;
    }
    static bool same(const uint8_t *data,uint32_t n,const char *name) {
        uint32_t i=0;for(;i<n&&name[i];++i)if(data[i]!=uint8_t(name[i]))return false;
        return i==n&&name[i]==0;
    }
    static bool string(const uint8_t *data,uint32_t size,uint32_t &pos,
        unsigned prefix,const uint8_t *&value,uint32_t &length) {
        if(pos>size||prefix>size-pos)return false;
        length=prefix==1?data[pos]:le16(data+pos);
        uint32_t step=(prefix+length+3)&~3u;
        if(step>size-pos)return false;
        value=data+pos+prefix;pos+=step;return true;
    }
    bool descriptors(const uint8_t *data,uint32_t n) {
        if(n<4)return fail(ProgramFormat);
        uint32_t alg=le32(data),pos=4,len;const uint8_t *text;
        if(!string(data,n,pos,1,text,len)||!string(data,n,pos,2,text,len)||
            n-pos<4)return fail(ProgramFormat);
        uint32_t count=le32(data+pos);pos+=4;
        for(uint32_t i=0;i<count;++i) {
            if(n-pos<8)return fail(ProgramFormat);
            uint32_t off=le16(data+pos),type=le16(data+pos+2),size=le32(data+pos+4);
            if(size>n-pos-8)return fail(ProgramFormat);
            uint32_t end=pos+8+size,q=pos+8,name_len;const uint8_t *name;
            if(!string(data,end,q,1,name,name_len)||!string(data,end,q,1,text,len)||
                !string(data,end,q,2,text,len)||end-q<8)return fail(ProgramFormat);
            uint32_t control_bytes=le32(data+q+4);
            if(alg==0xcd) {
                const char *names[]={"CAL_R","CAL_STATUS","CAL_CHECKSUM","CH_BAL"};
                for(unsigned k=0;k<4;++k)if(same(name,name_len,names[k])) {
                    if(type!=5||control_bytes!=4||off>=0x4d||controls[k].present)
                        return fail(ProgramFormat,0,off);
                    controls[k].offset=off;controls[k].present=true;
                }
            }
            pos=end;
        }
        return pos==n||fail(ProgramFormat);
    }
    static uint32_t memory(uint32_t type,uint32_t word) {
        switch(type) {
        case 5:return 0x02800000+word*4;
        case 6:return 0x03400000+word*4;
        case 0x10:return 0x03800000+word*5;
        case 0x11:return (0x02000000+word*3)&~3u;
        case 0x12:return (0x02c00000+word*3)&~3u;
        default:return 0;
        }
    }
    bool raw(uint32_t reg,const uint8_t *data,uint32_t n,uint32_t multiple,
        uint32_t &bytes,Error format) {
        if(n%multiple)return fail(format,reg,n);
        while(n) {
            uint32_t chunk=n<60?n:60;
            if(!io.raw_write(reg,data,chunk))return fail(Io,reg,chunk);
            reg+=chunk;data+=chunk;n-=chunk;bytes+=chunk;
        }
        return true;
    }
    bool load_program(const uint8_t *data,uint32_t size) {
        if(size<40||!same(data,4,"WMFW")||le32(data+4)!=40||data[10]!=4||data[11]!=3)
            return fail(ProgramFormat);
        uint32_t pos=40;
        while(pos<size) {
            if(size-pos<8)return fail(ProgramFormat,0,pos);
            uint32_t type=data[pos+3],off=le32(data+pos)&0xffffff,n=le32(data+pos+4);
            if(n>size-pos-8)return fail(ProgramFormat,0,pos);
            const uint8_t *p=data+pos+8;uint32_t reg=memory(type,off);
            if(reg) {
                uint32_t multiple=type==0x10?20:(type==0x11||type==0x12)?12:4;
                if(!raw(reg,p,n,multiple,r.program_bytes,ProgramFormat))return false;
                ++r.program_blocks;
            } else if(type==0xf2) {
                if(!descriptors(p,n))return false;
            } else if(type!=0xfe&&type!=0xff&&type!=0xfc)return fail(ProgramFormat,0,type);
            pos+=8+n;
        }
        for(const Control &c:controls)if(!c.present)return fail(ControlMissing);
        return r.program_blocks!=0||fail(ProgramFormat);
    }
    bool identity() {
        // Read back the real unpacked24 ID table, not the source file header.
        const uint32_t expected[]={0x40000,0x30000,2,0x400a4,0x2100,0x1e0,0xe,0,0,2,
            0xcd,0x1d3500,0x94,0x4d,0xe,0x7e9,0xf20b,1,0x170,0x4b,0,0,0xbedead};
        for(unsigned i=0;i<sizeof(expected)/sizeof(expected[0]);++i) {
            uint32_t value,reg=0x02800000+i*4;
            if(!read(reg,value))return false;
            if(value!=expected[i])return fail(RuntimeIdentity,reg,value);
        }
        for(Control &c:controls)c.reg=memory(5,0x94+c.offset);
        r.firmware_id=0x400a4;r.firmware_version=0x2100;r.algorithm_count=2;
        r.cspl_xm=0x94;r.cspl_ym=0xe;
        r.identity_verified=true;return true;
    }
    bool load_coefficients(const uint8_t *data,uint32_t size) {
        if(size<16||!same(data,4,"WMDR")||le32(data+4)!=16||(be32(data+8)&255)!=1)
            return fail(CoefficientFormat);
        uint32_t pos=16;
        while(pos<size) {
            if(size-pos<20)return fail(CoefficientFormat,0,pos);
            uint32_t off=le16(data+pos),type=le16(data+pos+2),alg=le32(data+pos+4);
            uint32_t n=le32(data+pos+16);
            if(n>size-pos-20)return fail(CoefficientFormat,0,pos);
            uint32_t padded=n+((4-(n&3))&3);
            if(padded>size-pos-20)return fail(CoefficientFormat,0,pos);
            uint32_t reg=memory(type,0);
            if(reg) {
                // Actual Nabu WMDR blocks use CSPL YM; other algorithms are
                // supported from the same ID table for matching memory types.
                uint32_t xm,ym;
                if(alg==0xcd) {xm=0x94;ym=0xe;}
                else if(alg==0xf20b) {xm=0x170;ym=0;}
                else if(alg==0x400a4) {xm=0x1e0;ym=0;}
                else return fail(CoefficientFormat,0,alg);
                if(type==0x10)return fail(CoefficientFormat,0,type);
                reg=memory(type,(type==5||type==0x11)?xm:ym)+off;
                uint32_t multiple=(type==0x11||type==0x12)?12:4;
                if((reg&3)||!raw(reg,data+pos+20,n,multiple,r.coefficient_bytes,CoefficientFormat))
                    return r.error==Ok?fail(CoefficientFormat,reg):false;
                ++r.coefficient_blocks;
            } else if(type!=0xfe00&&type!=0xff00&&type!=0xfc00)
                return fail(CoefficientFormat,0,type);
            pos+=20+padded;
        }
        return r.coefficient_blocks!=0||fail(CoefficientFormat);
    }
    bool trim() {
        const OtpField *map=nullptr;unsigned word=2,bit=16;
        if(r.devid_otp==0x35a40) {
            if(r.otp_id==1||r.otp_id==8)map=otp_map_1;
            if(r.otp_id==2||r.otp_id==6)map=otp_map_2;
        } else if(r.devid_otp==0&&r.otp_id==3)map=otp_map_2;
        else if(r.devid_otp==0x35a41&&r.otp_id==1) {map=otp_map_1;word=4;}
        if(!map)return fail(OtpMapMissing,0x10,r.otp_id);
        r.otp_map=map==otp_map_1?1:2;
        uint32_t otp[32];
        for(unsigned i=0;i<32;++i)if(!read(0x400+i*4,otp[i]))return false;
        unlocked=true;lock1=0xcc;lock2=0x33;
        if(!write(0x40,0x55)||!write(0x40,0xaa))return false;
        for(unsigned i=0;i<99;++i) {
            const OtpField &f=map[i];uint64_t bits=otp[word];
            if(bit+f.bits>32)bits|=uint64_t(otp[word+1])<<32;
            uint32_t mask=(uint32_t(1)<<f.bits)-1,val=uint32_t(bits>>bit)&mask;
            bit+=f.bits;word+=bit/32;bit%=32;
            if(f.reg) {
                if(!update(f.reg,mask<<f.shift,val<<f.shift))return false;
                ++r.otp_writes;
            }
        }
        if(!write(0x40,0xcc)||!write(0x40,0x33))return false;
        unlocked=false;return true;
    }
    bool configure() {
        // Physical Nabu boost/OTP preparation; no amplifier or core enable.
        return write(0x02bc1000,0)&&update(0x3810,0xffff,0x2424)&&
            update(0x3814,0xff03,0x7500)&&update(0x3808,0x7f,0x40)&&
            update(0x4220,3,3)&&update(0x480c,3,3)&&update(0x2c0c,0x1f,3);
    }
    bool work(unsigned index) {
        if(index>=4)return fail(InvalidPosition,0,index);
        const Position &p=Positions[index];
        r.phase=Quiet;if(!quiet())return fail(Io);
        r.phase=Probe;
        if(!read(0,r.devid)||!read(4,r.revid)||!read(0x10,r.otp_id)||!read(0x2850,r.devid_otp))return false;
        if(r.devid!=0x35a40||r.revid!=0xb2)return fail(ChipIdentity,0,r.devid);
        uint32_t status=0;
        for(unsigned i=0;i<100;++i) {
            if(!read(0x1001c,status))return false;
            if(status&2)break;
            io.delay_us(1000);
        }
        if(!(status&2))return fail(OtpNotReady,0x1001c,status);
        if(!read(0x10018,status))return false;
        if(status&0x80000000)return fail(OtpNotReady,0x10018,status);
        r.phase=Trim;unlocked=true;lock1=0xcccc;lock2=0x3333;
        for(const RegisterValue &v:B2Errata)if(!write(v.reg,v.value))return false;
        unlocked=false;if(!trim())return false;
        r.phase=Configure;if(!configure())return false;
        uint32_t size=0;const uint8_t *asset;
        r.phase=Program;asset=io.firmware("cs35l41-dsp1-spk-prot.wmfw",size);
        if(!asset)return fail(MissingFirmware);
        if(!load_program(asset,size))return false;
        r.phase=Identity;if(!identity())return false;
        r.phase=Coefficients;asset=io.firmware(p.coefficients,size);
        if(!asset)return fail(MissingFirmware);
        if(!load_coefficients(asset,size))return false;
        r.phase=Calibration;uint32_t values[]={p.cal_r,1,p.cal_r+1,p.ch_bal};
        for(unsigned i=0;i<4;++i)if(!write(controls[i].reg,values[i]))return false;
        r.phase=Verify;
        uint32_t *outputs[]={&r.cal_r,&r.cal_status,&r.cal_checksum,&r.ch_bal};
        for(unsigned i=0;i<4;++i) {
            if(!read(controls[i].reg,*outputs[i]))return false;
            if(*outputs[i]!=values[i])return fail(ReadbackMismatch,controls[i].reg,*outputs[i]);
        }
        if(!quiet())return fail(Io);
        r.phase=Complete;r.complete=true;return true;
    }
public:
    explicit Preloader(Backend &owner):io(owner) {}
    Result run(unsigned position_index) {
        r=Result{};unlocked=false;lock1=0xcc;lock2=0x33;
        for(Control &c:controls)c=Control{};
        if(!work(position_index)&&position_index<4)quiet();
        return r;
    }
};
} // namespace NabuCs35l41
