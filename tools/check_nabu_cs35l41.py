#!/usr/bin/env python3
"""Exercise the production CS35L41 preload header with retained Nabu assets."""
import argparse
import json
from pathlib import Path
import subprocess
import zipfile
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <vector>
#include "NabuCs35l41.h"
using namespace NabuCs35l41;
using Bytes=std::vector<uint8_t>;
struct Op {char type;uint32_t reg,value;};
struct Bus {
    std::map<std::string,Bytes> assets;
    std::map<uint32_t,uint32_t> regs;
    std::map<uint32_t,uint8_t> raw_bytes;
    Bytes xm=Bytes(0x3000),ym=Bytes(0x2000),pm=Bytes(0x6000);
    std::vector<Op> ops;
    unsigned fail_at=0,delay=0,otp_wait=0,raw_count=0;
    bool persistent=false,corrupt_cal=false;
    explicit Bus(const std::map<std::string,Bytes> &files):assets(files) {
        regs[0]=0x35a40;regs[4]=0xb2;regs[0x10]=6;regs[0x2850]=0x35a40;
        regs[0x1001c]=2;regs[0x2014]=0;regs[0x2018]=0x3321;regs[0x02bc1000]=0;
        for(unsigned i=0;i<32;++i)regs[0x400+i*4]=0x17e3b59du^(0x9e3779b9u*i);
        for(const OtpField &f:otp_map_1)if(f.reg)regs[f.reg]=0xa5c35a69;
        for(const OtpField &f:otp_map_2)if(f.reg)regs[f.reg]=0xa5c35a69;
    }
    bool operation(char type,uint32_t reg,uint32_t value=0) {
        ops.push_back({type,reg,value});
        return !fail_at||(persistent?ops.size()<fail_at:ops.size()!=fail_at);
    }
    uint32_t unpack(const Bytes &memory,unsigned word) const {
        uint32_t value=0;
        for(unsigned j=0;j<3;++j)value|=uint32_t(memory.at((word*3+j)^3))<<(8*j);
        return value;
    }
    void pack(Bytes &memory,unsigned word,uint32_t value) {
        for(unsigned j=0;j<3;++j)memory.at((word*3+j)^3)=uint8_t(value>>(8*j));
    }
    bool read(uint32_t reg,uint32_t &value) {
        if(!operation('r',reg))return false;
        if(reg>=0x02800000&&reg<0x02804000)value=unpack(xm,(reg-0x02800000)/4);
        else if(reg>=0x03400000&&reg<0x03402000)value=unpack(ym,(reg-0x03400000)/4);
        else value=regs[reg];
        if(reg==0x1001c&&otp_wait){--otp_wait;value=0;}
        if(corrupt_cal&&reg==0x02800268)value^=1;
        return true;
    }
    bool write(uint32_t reg,uint32_t value) {
        // The trial must never enable either output or HALO, nor configure PLL.
        assert(reg!=0x2c04&&reg!=0x4800);
        if(reg==0x2014||reg==0x2018||reg==0x02bc1000)assert(!(value&1));
        if(!operation('w',reg,value))return false;
        if(reg>=0x02800000&&reg<0x02804000)pack(xm,(reg-0x02800000)/4,value);
        else regs[reg]=value;
        return true;
    }
    bool raw_write(uint32_t reg,const uint8_t *data,uint32_t n) {
        assert(n&&n<=60&&!(reg&3));
        Bytes *m=nullptr;uint32_t base=0,multiple=4;
        if(reg>=0x02000000&&reg<0x02003000){m=&xm;base=0x02000000;multiple=12;}
        else if(reg>=0x02c00000&&reg<0x02c02000){m=&ym;base=0x02c00000;multiple=12;}
        else if(reg>=0x03800000&&reg<0x03806000){m=&pm;base=0x03800000;multiple=20;}
        else assert(reg>=0x03400000&&reg<0x03402000);
        assert(n%multiple==0);
        if(!operation('b',reg,n))return false;
        ++raw_count;
        for(unsigned i=0;i<n;++i)raw_bytes[reg+i]=data[i];
        if(m)for(unsigned i=0;i<n;++i)m->at(reg-base+i)=data[i];
        else for(unsigned i=0;i<n;i+=4)pack(ym,(reg-0x03400000+i)/4,be32(data+i));
        return true;
    }
    void delay_us(uint32_t us){assert(us==1000);++delay;}
    const uint8_t *firmware(const char *name,uint32_t &size) {
        auto it=assets.find(name);if(it==assets.end()){size=0;return nullptr;}
        size=it->second.size();return size?it->second.data():nullptr;
    }
};
std::map<std::string,Bytes> assets(const std::string &directory) {
    std::map<std::string,Bytes> out;
    auto load=[&](const char *name){std::ifstream f(directory+"/"+name,std::ios::binary);assert(f.good());out[name]=Bytes(std::istreambuf_iterator<char>(f),{});};
    load("cs35l41-dsp1-spk-prot.wmfw");for(const Position &p:Positions)load(p.coefficients);
    return out;
}
void output_off(const Bus &b,const Result &r) {
    assert(r.quiet);assert(!(b.regs.at(0x2014)&1));assert(!(b.regs.at(0x2018)&1));assert(!(b.regs.at(0x02bc1000)&1));
    assert(r.pwr1==b.regs.at(0x2014)&&r.pwr2==b.regs.at(0x2018)&&r.core==b.regs.at(0x02bc1000));
}
void bytes_match(const Bus &b,unsigned position) {
    // Independent ranges decoded from the captured file, not production parser.
    const uint32_t pieces[][3]={{104,72,0x02000000},{184,528,0x0200009c},{720,1584,0x020003c0},
        {2312,1284,0x020009fc},{3604,372,0x02000f90},{3984,6132,0x02c00000},{10124,20280,0x03800000}};
    std::map<uint32_t,uint8_t> expected;
    const Bytes &fw=b.assets.at("cs35l41-dsp1-spk-prot.wmfw");
    for(const auto &p:pieces)for(unsigned i=0;i<p[1];++i)expected[p[2]+i]=fw.at(p[0]+i);
    const Bytes &coeff=b.assets.at(Positions[position].coefficients);
    for(unsigned i=0;i<4428;++i)expected[0x02c0015c+i]=coeff.at(140+i);
    for(unsigned i=0;i<12;++i)expected[0x034018e0+i]=coeff.at(4588+i);
    assert(b.raw_bytes==expected);
}
void otp_matches(const Bus &b,const std::map<uint32_t,uint32_t> &before,const OtpField *fields,unsigned start) {
    // Bit-by-bit reference independent of production's two-word shift/extract.
    auto expected=before;unsigned cursor=start*32+16,crossings=0,ignored=0;
    for(unsigned i=0;i<99;++i) {
        const OtpField &f=fields[i];uint32_t value=0,mask=0;
        crossings+=(cursor%32+f.bits)>32;
        for(unsigned k=0;k<f.bits;++k) {
            unsigned bit=cursor+k;
            value|=((before.at(0x400+(bit/32)*4)>>(bit%32))&1)<<(f.shift+k);
            mask|=1u<<(f.shift+k);
        }
        cursor+=f.bits;
        if(f.reg)expected[f.reg]=(expected[f.reg]&~mask)|value;else ++ignored;
    }
    assert(crossings>0);if(fields==otp_map_1)assert(ignored>0);
    for(unsigned i=0;i<99;++i)if(fields[i].reg)assert(b.regs.at(fields[i].reg)==expected[fields[i].reg]);
}
void malformed(const std::map<std::string,Bytes> &base,const char *file,size_t offset,uint32_t value,unsigned width,Error error) {
    Bus b(base);auto &data=b.assets[file];
    for(unsigned i=0;i<width;++i)data.at(offset+i)=uint8_t(value>>(i*8));
    Preloader<Bus> p(b);Result r=p.run(0);
    if(r.complete||r.error!=error)fprintf(stderr,"malformed %s offset%zu got%d phase%d expected%d\n",file,offset,r.error,r.phase,error);
    assert(!r.complete&&r.error==error);output_off(b,r);
}
int main(int argc,char **argv) {
    assert(argc==2);auto files=assets(argv[1]);
    std::vector<Op> baseline;
    const uint8_t addresses[]={0x43,0x41,0x42,0x40};
    const uint32_t resistance[]={9301,9342,9630,9717};
    for(unsigned i=0;i<4;++i) {
        assert(Positions[i].address==addresses[i]);Bus b(files);auto before=b.regs;
        Preloader<Bus> p(b);Result r=p.run(i);
        assert(r.complete&&r.error==Ok&&r.phase==Complete&&r.identity_verified);
        assert(r.program_bytes==30252&&r.program_blocks==7&&r.coefficient_bytes==4440&&r.coefficient_blocks==2);
        assert(r.firmware_id==0x400a4&&r.firmware_version==0x2100&&r.algorithm_count==2&&r.cspl_xm==0x94&&r.cspl_ym==0xe);
        assert(r.cal_r==resistance[i]&&r.cal_status==1&&r.cal_checksum==resistance[i]+1&&r.ch_bal==(i%2?0x400000u:0));
        assert(r.otp_map==2&&r.otp_writes==99);output_off(b,r);bytes_match(b,i);otp_matches(b,before,otp_map_2,2);
        assert(b.regs[0x3810]==0x2424&&b.regs[0x3814]==0x7500&&b.regs[0x3808]==0x40);
        assert(b.regs[0x4220]==3&&b.regs[0x480c]==3&&b.regs[0x2c0c]==3);
        assert(b.regs[0x381c]==0x51&&b.regs[0x02bc2020]==0&&b.regs[0x02bc20e0]==0);
        if(i==0)baseline=b.ops;
    }
    struct MapCase {uint32_t devid,id;unsigned table,start;};
    for(const MapCase &m: {MapCase{0x35a40,1,1,2},{0x35a40,2,2,2},{0,3,2,2},
            {0x35a40,6,2,2},{0x35a40,8,1,2},{0x35a41,1,1,4}}) {
        Bus b(files);b.regs[0x2850]=m.devid;b.regs[0x10]=m.id;auto before=b.regs;
        Preloader<Bus> p(b);Result r=p.run(0);assert(r.complete&&r.otp_map==m.table);
        otp_matches(b,before,m.table==1?otp_map_1:otp_map_2,m.start);output_off(b,r);
    }
    {Bus b(files);b.otp_wait=2;Preloader<Bus> p(b);Result r=p.run(0);assert(r.complete&&b.delay==2);}
    {Bus b(files);b.regs[0x1001c]=0;Preloader<Bus> p(b);Result r=p.run(0);assert(r.error==OtpNotReady&&b.delay==100);output_off(b,r);}
    {Bus b(files);b.regs[0x10018]=0x80000000;Preloader<Bus> p(b);Result r=p.run(0);assert(r.error==OtpNotReady);output_off(b,r);}
    {Bus b(files);b.regs[4]=0xa0;Preloader<Bus> p(b);Result r=p.run(0);assert(r.error==ChipIdentity);output_off(b,r);}
    {Bus b(files);b.regs[0x10]=0xff;Preloader<Bus> p(b);Result r=p.run(0);assert(r.error==OtpMapMissing);output_off(b,r);}
    {Bus b(files);Preloader<Bus> p(b);Result r=p.run(4);assert(r.error==InvalidPosition&&b.ops.empty());}
    {Bus b(files);b.regs[0x2014]=1;b.regs[0x02bc1000]=1;Preloader<Bus> p(b);Result r=p.run(0);assert(r.complete);output_off(b,r);}
    {Bus b(files);b.corrupt_cal=true;Preloader<Bus> p(b);Result r=p.run(0);assert(r.error==ReadbackMismatch&&r.phase==Verify&&r.failed_reg==0x02800268);output_off(b,r);}
    const char *fw="cs35l41-dsp1-spk-prot.wmfw",*coeff=Positions[0].coefficients;
    for(const char *file:{fw,coeff}) {
        {Bus b(files);b.assets.erase(file);Preloader<Bus> p(b);Result r=p.run(0);assert(r.error==MissingFirmware);output_off(b,r);}
        for(unsigned size:{4u,12u,39u,unsigned(files.at(file).size()-1u)}) {
            Bus b(files);b.assets[file].resize(size);Preloader<Bus> p(b);Result r=p.run(0);
            assert(r.error==(file==fw?ProgramFormat:CoefficientFormat));output_off(b,r);
        }
    }
    malformed(files,fw,4,41,4,ProgramFormat); // header length
    malformed(files,fw,10,2,1,ProgramFormat); // wrong core
    malformed(files,fw,44,0xffffffff,4,ProgramFormat); // overflowing first region
    malformed(files,fw,100,71,4,ProgramFormat); // packed region alignment
    malformed(files,fw,99,0xf0,1,ProgramFormat); // no absolute hardware writes
    malformed(files,fw,104,1,1,RuntimeIdentity); // actual packed-XM identity readback
    malformed(files,fw,31372,0xff,1,ProgramFormat); // algorithm string length
    malformed(files,coeff,4,20,4,CoefficientFormat);
    malformed(files,coeff,136,0xffffffff,4,CoefficientFormat); // memory block length
    malformed(files,coeff,120,0x135,2,CoefficientFormat); // unaligned target
    malformed(files,coeff,124,0xabcdef,4,CoefficientFormat); // unknown algorithm
    // Representative faults include all pre-program operations, each raw region
    // boundary, every calibration/verification op, and final quiet confirmation.
    unsigned injected=0;
    for(unsigned i=0;i<baseline.size();++i) {
        bool take=i<baseline.size()&&baseline[i].type!='b';
        if(baseline[i].type=='b')take=(i%31==0||i==0||baseline[i-1].type!='b'||
            i+1==baseline.size()||baseline[i+1].type!='b'||baseline[i].value!=60);
        if(!take)continue;
        Bus b(files);b.fail_at=i+1;Preloader<Bus> p(b);Result r=p.run(0);
        assert(!r.complete&&r.error==Io&&r.failed_reg==baseline[i].reg);output_off(b,r);
        assert(b.regs[0x40]==0x33||b.regs[0x40]==0x3333||r.phase==Quiet||r.phase==Probe);
        ++injected;
    }
    {Bus b(files);b.fail_at=20;b.persistent=true;Preloader<Bus> p(b);Result r=p.run(0);
        assert(!r.complete&&r.error==Io&&!r.quiet&&r.failed_reg==baseline[19].reg);}
    printf("production CS35L41: four actual WMFW/WMDR assets, packed XM alias, exact memory writes, six OTP selections/crossing/untouched bits, calibration/channel readback, no output/core enable, malformed files and %u I/O failure unwinds passed\n",injected);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixtures = args.output / 'fixtures'
    fixtures.mkdir(exist_ok=True)
    with zipfile.ZipFile(ROOT / 'tools/fixtures/nabu-cs35l41-assets.zip') as archive:
        archive.extractall(fixtures)
    source = args.output / 'cs35l41.cpp'
    source.write_text(HARNESS)
    binary = args.output / 'cs35l41-test'
    subprocess.run(host_command([
        'clang++-18', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined',
        '-fno-omit-frame-pointer', '-Wall', '-Wextra', '-Werror',
        '-I' + host_path(ROOT / 'patches/nabu-audio'), host_path(source),
        '-o', host_path(binary)]), check=True)
    result = subprocess.run(host_command([
        host_path(binary), host_path(fixtures)]), capture_output=True)
    (args.output / 'stdout.txt').write_bytes(result.stdout)
    (args.output / 'stderr.txt').write_bytes(result.stderr)
    result.check_returncode()
    report = {'hardware_tested': False,
              'production_header': 'patches/nabu-audio/NabuCs35l41.h',
              'sanitizers': ['address', 'undefined'],
              'result': result.stdout.decode().strip()}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
