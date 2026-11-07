#!/usr/bin/env python3
"""Replay production SM8150 proxy votes and WLAN QDSS/PAS mailbox lifetime."""
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

QMP_PREFIX = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
using vm_offset_t=uintptr_t;
struct IORegistryEntry {};
static uint32_t ram[1024],doorbell;
static vm_offset_t aop=(uintptr_t)ram,ipc=(uintptr_t)&doorbell;
static uint32_t mailbox;
static bool qdss_touched,locked,rmtfs_ok=true,pas_start_ok=true,pas_stop_ok=true;
static int hakios_aop_mailbox_lock;
static std::vector<std::string> events;
static std::string timeout_message;
static void nabu_wireless_log(const char *,...) {}
static void lck_mtx_lock(int *){assert(!locked);locked=true;}
static void lck_mtx_unlock(int *){assert(locked);locked=false;}
static uint32_t rd(uintptr_t at){assert(locked);return *(uint32_t *)at;}
static void wr(uintptr_t at,uint32_t v){
    assert(locked);*(uint32_t *)at=v;
    if(at!=ipc)return;
    assert(v==1);
    if(ram[0x24/4]==0xffff)ram[0x28/4]=0xffff;
    if(ram[0x2c/4]==0xffff)ram[0x14/4]=0xffff;
    if(ram[0x18/4]==0xffff)ram[0x30/4]=0xffff;
    if(mailbox&&ram[mailbox/4]) {
        assert(ram[mailbox/4]==64);
        const char *text=(const char *)ram+mailbox+4;
        size_t n=strlen(text);assert(n<64);
        for(unsigned i=n;i<64;++i)assert(text[i]==0);
        events.emplace_back(text);
        if(timeout_message!=text)ram[mailbox/4]=0;
    }
}
static bool wait_value(uintptr_t at,uint32_t v,unsigned ms){assert(ms==1000);return rd(at)==v;}
static bool nabu_rmtfs_prepare(IORegistryEntry *){assert(!locked);events.emplace_back("rmtfs-prepare");return rmtfs_ok;}
static void nabu_wlan_runtime_stop(){assert(!locked);events.emplace_back("dma-stop");}
static void nabu_msa_finish(){assert(!locked);events.emplace_back("msa-finish");}
static void nabu_rmtfs_finish(){assert(!locked);events.emplace_back("rmtfs-finish");}
static bool scm(unsigned command,uint64_t types,uint64_t a,uint64_t b,uint64_t c){
    assert(!locked&&types==1&&a==4&&!b&&!c&&(command==5||command==6));
    events.emplace_back(command==5?"pas5":"pas6");return command==5?pas_start_ok:pas_stop_ok;
}
static void reset_qmp(){
    memset(ram,0,sizeof(ram));ram[0]=0x4d41494c;ram[1]=1;
    ram[0xc/4]=0xffff;ram[0x34/4]=68;ram[0x38/4]=0x100;
    mailbox=0;qdss_touched=false;locked=false;rmtfs_ok=pas_start_ok=pas_stop_ok=true;
    events.clear();timeout_message.clear();
}
'''
QMP_TEST = r'''
int main(){
    const std::string on="{class: clock, res: qdss, val: 1}",off="{class: clock, res: qdss, val: 0}";
    const std::string load="{class: image, res: load_state, name: modem, val: on}";
    const std::string unload="{class: image, res: load_state, name: modem, val: off}";
    bool requested=false;reset_qmp();
    assert(start_image(nullptr,true,requested)&&requested&&qdss_touched&&!locked);
    assert((events==std::vector<std::string>{"rmtfs-prepare",on,load,"pas5"}));
    // The vote stays held through running firmware; confirmed PAS6 precedes off.
    stop_image(true,requested);assert(!qdss_touched&&!locked);
    assert((events==std::vector<std::string>{"rmtfs-prepare",on,load,"pas5","pas6","dma-stop",off,unload,"msa-finish","rmtfs-finish"}));
    reset_qmp();requested=false;assert(start_image(nullptr,false,requested));stop_image(false,requested);
    assert((events==std::vector<std::string>{"rmtfs-prepare",load,"pas5","pas6",unload,"msa-finish","rmtfs-finish"}));
    reset_qmp();requested=false;timeout_message=on;
    assert(!start_image(nullptr,true,requested)&&!requested&&qdss_touched&&!locked);
    assert((events==std::vector<std::string>{"rmtfs-prepare",on}));
    // Simulate the late AOP consume. The failed on is still explicitly revoked.
    ram[mailbox/4]=0;timeout_message.clear();stop_image(true,requested);
    assert(!qdss_touched&&events[2]=="dma-stop"&&events[3]==off);
    reset_qmp();requested=false;pas_start_ok=false;
    assert(!start_image(nullptr,true,requested)&&requested&&qdss_touched);
    pas_stop_ok=false;stop_image(true,requested);
    assert(qdss_touched&&events.size()==5&&events.back()=="pas6");
    pas_stop_ok=true;stop_image(true,requested);assert(!qdss_touched&&events[6]=="dma-stop"&&events[7]==off);
    reset_qmp();requested=false;assert(start_image(nullptr,true,requested));timeout_message=off;
    stop_image(true,requested);assert(qdss_touched&&!locked); // No false off success.
    reset_qmp();requested=false;lck_mtx_lock(&hakios_aop_mailbox_lock);
    assert(qmp_open());lck_mtx_unlock(&hakios_aop_mailbox_lock);ram[mailbox/4]=64;
    assert(!start_image(nullptr,true,requested)&&!requested&&!qdss_touched);
    assert(events.size()==1&&events[0]=="rmtfs-prepare"); // Busy slot is not overwritten.
    puts("QDSS: exact padded QMP messages, mailbox locking, on before PAS5, retained while live, off after PAS6, timeout/busy admission and failed shutdown retention passed");
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
    qmp_source=args.output/'qmp-power.cpp'
    qmp_source.write_text(QMP_PREFIX+source[source.index('static bool qmp_open()'):source.index('static bool proxy_power()')]+QMP_TEST)
    qmp_binary=args.output/'qmp-power-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined',
        '-fno-omit-frame-pointer',host_path(qmp_source),'-o',host_path(qmp_binary)]),check=True)
    qmp_result=subprocess.run(host_command([host_path(qmp_binary)]),capture_output=True)
    (args.output/'qmp-test.log').write_bytes(qmp_result.stdout);(args.output/'qmp-test.stderr').write_bytes(qmp_result.stderr)
    qmp_result.check_returncode()
    report={'production_proxy_power_tested':True,'sanitizers':['address','undefined'],
        'xo_resource':'xo.lvl','xo_offset':0,'xo_on_value':3,'hardware_tested':False,
        'production_qmp_lifetime_tested':True,'qmp_result':qmp_result.stdout.decode().strip(),
        'result':result.stdout.decode().strip()}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
