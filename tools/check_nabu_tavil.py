#!/usr/bin/env python3
"""Replay original SLIM register messages and Tavil digital bring-up."""
import argparse
import json
from pathlib import Path
from check_nabu_adsp_glink import run
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <map>
#include <utility>
#include "NabuSlimNgd.h"
#include "NabuTavil.h"
using Bytes=std::vector<uint8_t>;
struct Registers {
    std::map<uint32_t,uint32_t> regs;
    std::vector<Bytes> tx;
    std::vector<std::pair<unsigned,unsigned>> codec_writes;
    uint32_t bank,version;uint8_t page=0xff;Bytes message;
    bool respond=true,retained;
    Registers(bool old,bool warm):bank(old?0x800:0x1000),version(old?0:0x1000),retained(warm) {
        regs[0]=version<<16;regs[bank+4]=warm?2:0;
        regs[bank]=6;regs[bank+8]=7;regs[bank+0x10]=0x80000000;
    }
    uint32_t read(uint32_t reg) {return regs[reg];}
    void incoming(Bytes p) {
        for(unsigned i=0;i<(p.size()+3)/4;++i) {
            uint32_t v=0;for(unsigned j=0;j<4&&i*4+j<p.size();++j)v|=uint32_t(p[i*4+j])<<(j*8);
            regs[bank+0x70+i*4]=v;
        }
        regs[bank+0x14]|=0x40000000;
    }
    void transmit() {
        uint32_t bytes=message[0]&31;message.resize(bytes);tx.push_back(message);
        regs[bank+0x14]|=0x80000000;
        const auto &p=message;
        if(p[1]==1) {
            assert(p==Bytes({0xc7,1,0xff,0xd9,0xc5,1,1}));regs[bank+4]|=2;return;
        }
        if(!respond)return;
        if(p[1]==0x0d) {
            assert(bytes==10&&p[0]==0x4a&&p[2]==0xff);
            assert(p[4]==0&&p[6]==0x50&&p[7]==2&&p[8]==0x17&&p[9]==2);
            Bytes reply={0xcb,0x0e,0, p[3]};reply.insert(reply.end(),p.begin()+4,p.end());
            reply.push_back(p[5]?0xcf:0xce);incoming(reply);
        } else if(p[1]==0x68) {
            assert(bytes==6&&p[2]==0xcf);uint16_t ec=p[3]|uint16_t(p[4])<<8;
            assert((ec&15)==8);unsigned offset=ec>>4;assert(offset>=0x800&&offset<=0x8ff);
            if(offset==0x800)page=p[5];else codec_writes.push_back({page*256+offset-0x800,p[5]});
        } else if(p[1]==0x60) {
            assert(bytes==6&&p[2]==0xcf&&page==0);uint16_t ec=p[4]|uint16_t(p[5])<<8;
            assert(ec==0x8219||ec==0x8239);uint16_t value=ec==0x8219?1:0x108;
            incoming({6,0x64,0,p[3],uint8_t(value),uint8_t(value>>8)});
        } else assert(false);
    }
    void write(uint32_t reg,uint32_t value) {
        if(reg==bank+0x18) {regs[bank+0x14]&=~value;return;}
        regs[reg]=value;
        if(reg==bank&&value==1&&!retained)incoming({0xc3,0,0xff});
        if(reg>=bank+0x30&&reg<bank+0x50) {
            unsigned offset=reg-bank-0x30;
            if(!offset)message.assign(32,0);
            for(unsigned i=0;i<4;++i)message[offset+i]=uint8_t(value>>(i*8));
            if(offset+4>=unsigned(message[0]&31))transmit();
        }
    }
};
static void run_codec(bool old,bool retained) {
    Registers io(old,retained);NabuSlimNgd::Bus<Registers> bus(io);NabuTavil::Codec<decltype(bus)> codec(bus);
    bus.begin(0);bool begun=false;
    for(unsigned ms=0;ms<200&&!codec.done();++ms) {
        bus.step(ms);if(bus.result().ready&&bus.idle()&&!begun) {codec.begin();begun=true;}
        if(begun)codec.step(ms);
    }
    assert(codec.done()&&codec.result().identified&&codec.result().major==0x108&&codec.result().minor==1);
    assert(codec.result().pgd==0xcf&&codec.result().ifd==0xce&&bus.result().error==NabuSlimNgd::Ok);
    const std::vector<std::pair<unsigned,unsigned>> expected={
        {0x9,1},{0x71b,0x19},{0x71c,0x15},{0x11,5},{0x11,7},{0x9,3},{0x9,7},{0x11,3}};
    assert(io.codec_writes==expected);
    assert(bus.result().capability==!retained&&bus.result().reported==!retained);
    assert(io.regs[io.bank+0x10]==0xfe000000);bus.stop();
    assert(bus.result().stopped&&io.regs[io.bank]==6&&io.regs[io.bank+8]==7&&io.regs[io.bank+0x10]==0x80000000);
}
int main() {
    for(bool old:{false,true})for(bool retained:{false,true})run_codec(old,retained);
    Registers io(false,true);io.respond=false;NabuSlimNgd::Bus<Registers> bus(io);bus.begin(0);
    const uint8_t ea[]={0,1,0x50,2,0x17,2};bus.address(ea);bus.step(1);bus.step(1000);
    assert(bus.result().error==NabuSlimNgd::Timeout);
    std::puts("PASS: NGD old/new banks, cold capability and retained LA, exact PGD/IFD queries, paged vendor bring-up, live identity replies, register restore and missing-RX timeout");
}
'''

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    source=a.output/'tavil.cpp';source.write_text(HARNESS);binary=a.output/'tavil'
    run(host_command(['clang++-18','-std=c++17','-O1','-g','-fsanitize=address,undefined',
        '-fno-omit-frame-pointer','-Wall','-Wextra','-Werror','-I'+host_path(ROOT/'patches/nabu-audio'),
        host_path(source),'-o',host_path(binary)]))
    result=run(host_command([host_path(binary)]))
    report={'status':'passed','result':result.strip(),'device_executed':False,
            'production_sources':['NabuSlimNgd.h','NabuTavil.h'],
            'sanitizers':['address','undefined']}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
