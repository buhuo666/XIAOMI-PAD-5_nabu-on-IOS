#!/usr/bin/env python3
"""Replay production shared-power and WLAN-before-BT startup ordering."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]
PREFIX=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
using vm_offset_t=uintptr_t;
using vm_size_t=uintptr_t;
using thread_call_param_t=void *;
static unsigned wireless_level,failed_rail;
static bool map_ok=true;
static int report_lock;
static const char *wireless_report="report",*gIODTPlane="IODeviceTree";
static std::vector<unsigned> events;
static vm_offset_t ml_io_map(vm_offset_t pa,vm_size_t bytes){assert(pa==0x18220000&&bytes==0x4000);return map_ok?1:0;}
static bool enable_supply(vm_offset_t rsc,const char *name,uint32_t address,uint32_t mv){
    static const char *names[]={"ldoa1","ldoa7","ldoc2","ldoc11"};
    static const unsigned addresses[]={0x40800,0x41f00,0x41d00,0x41a00},voltages[]={752,1800,1304,3312};
    unsigned i=events.size();assert(i<4&&rsc==1&&!strcmp(name,names[i])&&address==addresses[i]&&mv==voltages[i]);
    events.push_back(i+1);return failed_rail!=i+1;
}
static void IOSleep(unsigned ms){assert(ms==10);events.push_back(5);}
static void nabu_wireless_log(const char *,...){}
static void smem_survey(){} static void cmd_db_survey(){} static void rpmh_survey(){}
static void regulator_survey(){} static void uart_survey(){}
static void nabu_modem_start_trial(){events.push_back(6);}
static void nabu_bluetooth_version_trial(){events.push_back(7);}
static void IOLockLock(int){} static void IOLockUnlock(int){}
struct IORegistryEntry {
    static IORegistryEntry *fromPath(const char *,const char *){static IORegistryEntry e;return &e;}
    void setProperty(const char *,const char *){events.push_back(8);}
    void release(){}
};
'''
TEST=r'''
int main(){
    wireless_level=5;wireless_survey(nullptr,nullptr);
    assert((events==std::vector<unsigned>{1,2,3,4,5,6,7,8}));
    events.clear();wireless_level=3;wireless_survey(nullptr,nullptr);
    assert((events==std::vector<unsigned>{1,2,3,4,5,7,8}));
    events.clear();wireless_level=1;wireless_survey(nullptr,nullptr);assert((events==std::vector<unsigned>{8}));
    for(failed_rail=1;failed_rail<=4;++failed_rail){
        events.clear();wireless_level=5;wireless_survey(nullptr,nullptr);
        assert(events.size()==failed_rail+1&&events.back()==8);
        for(unsigned i=0;i<failed_rail;++i)assert(events[i]==i+1);
    }
    events.clear();failed_rail=0;map_ok=false;wireless_survey(nullptr,nullptr);
    assert((events==std::vector<unsigned>{8}));
    puts("Wireless startup: unchanged four shared rails, WLAN before BT pulses, BT-only and survey levels, power failure stops both and still publishes report passed");
}
'''

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    bt=(ROOT/'patches/nabu-wireless/NabuBluetooth.cpp').read_text()
    power=bt[bt.index('bool nabu_wireless_power_on()'):bt.index('void nabu_bluetooth_version_trial()')]
    source=(ROOT/'patches/nabu-wireless/NabuWireless.cpp').read_text()
    order=source[source.index('static void wireless_survey('):source.index('extern "C" void nabu_wireless_start(')]
    harness=a.output/'wireless-start.cpp';harness.write_text(PREFIX+power+order+TEST);binary=a.output/'wireless-start-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',host_path(harness),'-o',host_path(binary)]),check=True)
    r=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (a.output/'test.log').write_bytes(r.stdout);(a.output/'test.stderr').write_bytes(r.stderr);r.check_returncode()
    report={'production_startup_tested':True,'hardware_tested':False,'sanitizers':['address','undefined'],'result':r.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
