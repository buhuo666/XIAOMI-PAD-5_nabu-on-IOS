#!/usr/bin/env python3
"""Replay WLAN_CFG/MODE and WCN399x CE rings; compare config with pinned Linux arrays."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tools/fixtures/nabu-wlan-snoc-config.json'
PREFIX = r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include <map>
#include "NabuWlanConfig.h"
#include "NabuSnocRing.h"
#include "NabuSnocPipe.h"
'''
TEST = r'''
int main() {
    NabuWlanConfig c;
    assert(!c.begin(false,true,42)&&!c.begin(true,false,42)&&!c.bytes);
    assert(c.begin(true,true,42)&&c.bytes==559);
    // Frozen oracle encoded from the pinned original Linux arrays and WLFW IDL.
    std::vector<uint8_t> wire(golden,golden+sizeof(golden));
    assert(wire.size()==c.bytes&&!memcmp(wire.data(),c.request,c.bytes));
    assert(!c.prepare_mode(43));c.sent();
    uint8_t response[]={2,41,0,0x23,0,7,0,2,4,0,0,0,0,0};
    assert(!c.receive(response,sizeof(response))&&c.waiting);
    response[1]=42;assert(c.receive(response,sizeof(response))&&c.phase==NabuWlanConfig::Mode);
    assert(c.prepare_mode(43));
    const uint8_t mission[]={0,43,0,0x22,0,11,0,1,4,0,0,0,0,0,0x10,1,0,0};
    assert(c.bytes==sizeof(mission)&&!memcmp(c.request,mission,sizeof(mission)));
    c.sent();response[1]=43;assert(!c.receive(response,sizeof(response)));response[3]=0x22;
    assert(c.receive(response,sizeof(response))&&c.phase==NabuWlanConfig::Enabled);
    assert(!c.begin(true,true,44));c.invalidate();assert(!c.begin(true,true,45));
    for(bool during_mode:{false,true}) {
        NabuWlanConfig f;f.begin(true,true,1);f.sent();response[1]=1;response[3]=0x23;
        if(during_mode){f.receive(response,sizeof(response));f.prepare_mode(2);f.sent();response[1]=2;response[3]=0x22;}
        response[10]=1;response[12]=94;assert(f.receive(response,sizeof(response))&&f.phase==NabuWlanConfig::Failed&&f.error==94);
        assert(!f.prepare_mode(3));response[10]=response[12]=0;
    }
    NabuWlanConfig late;late.begin(true,true,1);late.sent();late.invalidate();
    response[1]=1;response[3]=0x23;assert(!late.receive(response,sizeof(response))&&!late.bytes);
    NabuWlanConfig timeout;timeout.begin(true,true,1);timeout.sent();for(unsigned i=0;i<10000;++i)timeout.tick();
    assert(timeout.phase==NabuWlanConfig::Failed&&!timeout.waiting&&!timeout.bytes);
    NabuSnocRing::Descriptor desc[4]{};void *contexts[4]{};
    NabuSnocRing ring{desc,contexts,4};int a=1,b=2,d=3;void *ctx=nullptr;
    assert(ring.post(0x712345678ULL,100,0x123,&a));
    assert(desc[0].address==0x712345678ULL&&desc[0].bytes==100&&desc[0].metadata==0x1230&&desc[0].hash==0);
    assert(!ring.post(1ULL<<35,100,1,&a)&&ring.producer==1);
    assert(ring.post(0x100,200,0,&b)&&ring.post(0x200,300,0,&d)&&!ring.post(0x300,10,0,&a));
    assert(!ring.complete_send(0,ctx)&&!ring.complete_send(4,ctx));
    assert(ring.complete_send(2,ctx)&&ctx==&a&&ring.complete_send(2,ctx)&&ctx==&b&&!ring.complete_send(2,ctx));
    assert(ring.post(0x300,20,0,&a)&&ring.producer==0);
    assert(ring.complete_send(0,ctx)&&ctx==&d&&ring.complete_send(0,ctx)&&ctx==&a);
    NabuSnocRing rx{desc,contexts,4};assert(rx.post_receive(0xa0000000,&a));uint16_t bytes=0;
    assert(!rx.complete_receive(ctx,bytes));desc[0].bytes=64;
    assert(rx.complete_receive(ctx,bytes)&&bytes==64&&ctx==&a&&desc[0].bytes==0);
    assert(rx.post_receive(0xa0000800,&b));rx.invalidate();desc[1].bytes=32;
    assert(!rx.complete_receive(ctx,bytes)&&contexts[1]==&b&&!rx.post_receive(0xa0001000,&d));
    struct Bus {
        std::map<uint32_t,uint32_t> regs;
        uint32_t read(uint32_t at){return regs[at];}
        void write(uint32_t at,uint32_t value){regs[at]=value;}
    } bus;
    NabuSnocRing init{desc,contexts,4};
    bus.regs={{0x243044,6},{0x24303c,6},{0x243018,0xffffffff}};
    NabuSnocPipe::initialize(bus,3,init,0x6a0000000ULL,true);
    assert(init.consumer==2&&init.producer==2&&bus.regs[0x243000]==0xa0000000&&bus.regs[0x243004]==6);
    assert(bus.regs[0x243008]==4&&bus.regs[0x243018]==0xfffd0800&&bus.regs[0x24304c]==4);
    bus.regs={{0x242048,7},{0x242040,7},{0x242010,0xffffffe0},{0x242018,0xffffffff}};
    NabuSnocPipe::initialize(bus,2,init,0x7a0100000ULL,false);
    assert(init.consumer==3&&init.producer==3&&bus.regs[0x24200c]==0xa0100000&&bus.regs[0x242010]==0xffffffe7);
    assert(bus.regs[0x242014]==4&&bus.regs[0x242018]==0xfffbffff&&bus.regs[0x242050]==4);
    bus.regs[0x24202c]=0xff;NabuSnocPipe::interrupts(bus,2,true);assert(bus.regs[0x24202c]==0xe1);
    bus.regs[0x242034]=0xffff;NabuSnocPipe::interrupts(bus,2,false);
    assert(bus.regs[0x24202c]==0xe0&&bus.regs[0x242034]==0xfc1f);
    NabuSnocPipe::interrupts(bus,4,true);assert(bus.regs[0x24402c]==0);
    puts("WLAN_CFG exact pinned SNOC map, CFG-before-MODE, QMI failures/retirement, CE 35-bit descriptors, ring fullness/wrap and DMA completion ownership passed");
}
'''

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    fixture=json.loads(FIXTURE.read_text())
    golden=','.join(str(x) for x in bytes.fromhex(fixture['wire_hex']))
    harness=args.output/'wlan.cpp'
    harness.write_text(PREFIX+'const uint8_t golden[]={'+golden+'};\n'+TEST)
    binary=args.output/'wlan-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined',
        '-fno-omit-frame-pointer','-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(harness),'-o',host_path(binary)]),check=True)
    r=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (args.output/'test.log').write_bytes(r.stdout);(args.output/'test.stderr').write_bytes(r.stderr);r.check_returncode()
    report={'hardware_tested':False,'sanitizers':['address','undefined'],'reference':fixture['source'],
        'config_wire_bytes':559,'mode_wire_bytes':18,'result':r.stdout.decode().strip()}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
