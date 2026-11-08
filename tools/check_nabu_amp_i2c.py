#!/usr/bin/env python3
"""Exercise production Nabu 32-bit I2C reads against scripted open-drain wire replies."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include "NabuAmpI2c.h"
struct Pins {
    struct Bit {bool released,value;};
    std::vector<Bit> bits;
    bool scl=true,sda=true,taken=false,idle=true;
    unsigned index=0,rises=0,starts=0,stops=0,restored=0,waits=0,fail_rise=0;
    bool initial=true;
    void take(){assert(!taken);taken=true;initial=true;}
    void restore(){assert(taken);taken=false;++restored;}
    void delay_us(unsigned us){assert(us==5);++waits;}
    void line(bool clock,bool release) {
        assert(taken);
        if(clock){if(release&&!scl)++rises;scl=release;}
        else {if(scl&&sda!=release){if(release)++stops;else ++starts;}sda=release;}
    }
    bool level(bool clock) {
        assert(taken);
        if(clock)return scl&&(!fail_rise||rises<fail_rise);
        if(initial){initial=false;return idle;}
        assert(scl&&index<bits.size());auto b=bits[index++];assert(sda==b.released);return b.value;
    }
    void tx(uint8_t value,bool ack=true){for(int i=7;i>=0;--i)bits.push_back({bool((value>>i)&1),bool((value>>i)&1)});bits.push_back({true,!ack});}
    void rx(uint8_t value,bool more){for(int i=7;i>=0;--i)bits.push_back({true,bool((value>>i)&1)});bits.push_back({!more,!more});}
    void script(uint8_t address,uint32_t reg,uint32_t value) {
        tx(address<<1);for(int shift=24;shift>=0;shift-=8)tx(reg>>shift);tx(address<<1|1);
        for(int shift=24;shift>=0;shift-=8)rx(value>>shift,shift!=0);
    }
};
int main() {
    for(uint8_t address:{0x40,0x41,0x42,0x43}) {
        Pins p;p.script(address,0x0001001c,0x35a40);NabuAmpI2c::Bus<Pins> bus(p);uint32_t value;
        assert(bus.read_register(address,0x1001c,value)&&value==0x35a40&&bus.error()==NabuAmpI2c::Ok);
        assert(p.index==90&&p.starts==2&&p.stops==1&&p.restored==1&&!p.taken);
    }
    for(unsigned fail=0;fail<6;++fail) {
        Pins p;uint8_t bytes[]={0x80,0x12,0x34,0x56,0x78,0x81};
        for(unsigned i=0;i<=fail;++i)p.tx(bytes[i],i!=fail);
        NabuAmpI2c::Bus<Pins> bus(p);uint32_t value;
        assert(!bus.read_register(0x40,0x12345678,value));
        assert(bus.error()==(fail==0?NabuAmpI2c::AddressNack:fail==5?NabuAmpI2c::ReadAddressNack:NabuAmpI2c::RegisterNack));
        assert(p.index==p.bits.size()&&p.restored==1&&p.stops==1);
    }
    {Pins p;p.idle=false;NabuAmpI2c::Bus<Pins> bus(p);uint32_t value;
        assert(!bus.read_register(0x40,0,value)&&bus.error()==NabuAmpI2c::BusNotIdle);
        assert(p.starts==0&&p.restored==1&&p.index==0);}
    {Pins p;p.fail_rise=3;p.script(0x40,0,0);NabuAmpI2c::Bus<Pins> bus(p);uint32_t value;
        assert(!bus.read_register(0x40,0,value)&&bus.error()==NabuAmpI2c::ClockHeldLow);
        assert(p.restored==1&&p.waits>=100&&p.index==2);}
    puts("production I2C: four Nabu addresses, 32-bit big-endian register/data, repeated START, byte ACK/final NACK, every outbound NACK, idle/clock hold failures and pin restoration passed");
}
'''
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);source=args.output/'i2c.cpp';source.write_text(HARNESS)
    binary=args.output/'i2c-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-Wall','-Wextra','-Werror','-I'+host_path(ROOT/'patches/nabu-audio'),host_path(source),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (args.output/'stdout.txt').write_bytes(result.stdout);(args.output/'stderr.txt').write_bytes(result.stderr);result.check_returncode()
    report={'hardware_tested':False,'production_header':'patches/nabu-audio/NabuAmpI2c.h','sanitizers':['address','undefined'],'result':result.stdout.decode().strip()}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
