#!/usr/bin/env python3
"""Replay the production modem proxy votes against the stock SM8150 clock contract."""
import argparse
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include "NabuSmem.h"
using vm_offset_t = uintptr_t;
static uint8_t db_data[0x20000];
static uint32_t registers[0x4000/4];
static vm_offset_t rsc = reinterpret_cast<uintptr_t>(registers);
static int hakios_rsc_lock;
static constexpr unsigned VM_WIMG_IO=7;
static bool locked, respond=true, fail_xo;
struct Command { uint32_t address, data; };
static std::vector<Command> commands;
static void nabu_wireless_log(const char *,...) {}
static uintptr_t map_region(const char *,uintptr_t pa,size_t bytes,unsigned) {
    assert(pa==0x85f20000&&bytes==sizeof(db_data));return reinterpret_cast<uintptr_t>(db_data);
}
static void lck_mtx_lock(int *) { assert(!locked);locked=true; }
static void lck_mtx_unlock(int *) { assert(locked);locked=false; }
static void IODelay(unsigned) {}
static uint32_t rd(uintptr_t address) { return *reinterpret_cast<uint32_t *>(address); }
static void wr(uintptr_t address,uint32_t value) {
    assert(locked);unsigned offset=address-rsc;
    if(offset==0xd08){registers[0xd04/4]&=~value;return;}
    registers[offset/4]=value;
    if(offset==0xd14&&(value&(1u<<24))) {
        unsigned enable=registers[0xd1c/4];assert(enable==7&&registers[0xd10/4]==7);
        for(unsigned i=0;i<3;++i) {
            unsigned at=0xd30+20*i;assert(registers[at/4]==0x10108);
            commands.push_back({registers[(at+4)/4],registers[(at+8)/4]});
            registers[(at+12)/4]=fail_xo&&i==2?0:0x10101;
        }
        if(respond)registers[0xd04/4]=1;
    }
}
static void put16(unsigned at,unsigned value) { db_data[at]=value;db_data[at+1]=value>>8; }
static void put32(unsigned at,uint32_t value) { memcpy(db_data+at,&value,4); }
static void reset() {
    memset(db_data,0,sizeof(db_data));memset(registers,0,sizeof(registers));commands.clear();
    locked=false;respond=true;fail_xo=false;registers[0xd18/4]=1;
    put32(4,0x0c0330db);put16(8,3);put16(10,0);put16(12,0x100);put16(14,3);
    const char *names[]={"mss.lvl","xo.lvl","cx.lvl"};
    const unsigned addresses[]={0x30060,0x30090,0x30000};
    for(unsigned i=0;i<3;++i) {
        unsigned at=144+24*i;memcpy(db_data+at,names[i],strlen(names[i]));put32(at+16,addresses[i]);
        // XO deliberately has no voltage-level auxiliary table.
        if(i!=1){put16(at+20,8);put16(at+22,i*8);
            for(unsigned j=0;j<4;++j)put16(144+0x100+i*8+j*2,j*128);}
    }
}
'''
TEST = r'''
int main() {
    reset();assert(proxy_power()&&!locked&&commands.size()==3);
    assert(commands[0].address==0x30000&&commands[0].data==3);
    assert(commands[1].address==0x30060&&commands[1].data==3);
    // Independent vendor contract: RPMH_CXO_CLK -> xo.lvl + 0, on-value 3.
    assert(commands[2].address==0x30090&&commands[2].data==3);
    assert(!registers[0xd1c/4]&&!registers[0xd10/4]&&!registers[0xd14/4]);
    reset();memset(db_data+144+24,0,8);assert(!proxy_power()&&commands.empty()&&!locked);
    reset();fail_xo=true;assert(!proxy_power()&&commands.size()==3&&!locked);
    reset();respond=false;assert(!proxy_power()&&!locked);
    reset();registers[0xd1c/4]=1;assert(!proxy_power()&&commands.empty()&&!locked);
    puts("Modem: CX/MSS OPP votes plus mandatory XO ARC value 3, missing XO, failed XO completion, timeout and busy TCS passed");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = (ROOT/'patches/nabu-wireless/NabuModem.cpp').read_text()
    power = source[source.index('static bool proxy_power()'):source.index('static bool allocate_item(')]
    harness=args.output/'modem-power.cpp';harness.write_text(PREFIX+power+TEST)
    binary=args.output/'modem-power-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined',
        '-fno-omit-frame-pointer','-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(harness),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (args.output/'test.log').write_bytes(result.stdout);(args.output/'test.stderr').write_bytes(result.stderr)
    result.check_returncode()
    report={'production_proxy_power_tested':True,'sanitizers':['address','undefined'],
        'xo_resource':'xo.lvl','xo_offset':0,'xo_on_value':3,'hardware_tested':False,
        'result':result.stdout.decode().strip()}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
