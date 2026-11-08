#!/usr/bin/env python3
"""Replay QCA boot diagnostics before real HCI responses through production RX."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path

ROOT=Path(__file__).resolve().parents[1]
PREFIX=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <deque>
#include <vector>
#include "NabuBluetoothBootRx.h"
using vm_offset_t=uintptr_t;
static std::deque<std::vector<uint8_t>> arrivals;
static unsigned offset,uart_error,sleeps;
static uint32_t rd(vm_offset_t at) {
    if(at==0x640)return uart_error;
    if(at==0x804) {
        if(arrivals.empty())return 0;
        unsigned n=arrivals.front().size()-offset;
        return (n+3)/4 | (n%4 ? 0x80000000u|(n%4)<<28 : 0);
    }
    assert(at==0x780&&!arrivals.empty());uint32_t word=0;
    for(unsigned i=0;i<4&&offset<arrivals.front().size();++i)word|=(uint32_t)arrivals.front()[offset++]<<(i*8);
    return word;
}
static void wr(vm_offset_t at,uint32_t) {
    assert(at==0x648);
    if(!arrivals.empty()&&offset==arrivals.front().size()){arrivals.pop_front();offset=0;}
}
static void IOSleep(unsigned ms){assert(ms==1);++sleeps;}
static void nabu_wireless_log(const char *,...){}
'''
TEST=r'''
static std::vector<uint8_t> reset={4,0x0e,4,1,3,0x0c,0};
static std::vector<uint8_t> debug(unsigned size) {
    std::vector<uint8_t> p={2,0xdc,0x2e,(uint8_t)size,(uint8_t)(size>>8)};
    for(unsigned i=0;i<size;++i)p.push_back(reset[i%reset.size()]);return p;
}
static void queue(const std::vector<uint8_t> &p,unsigned fragment) {
    for(unsigned at=0;at<p.size();at+=fragment)
        arrivals.emplace_back(p.begin()+at,p.begin()+((at+fragment<p.size())?at+fragment:p.size()));
}
static void clean(){boot_rx={};arrivals.clear();offset=uart_error=sleeps=0;}
int main() {
    uint8_t reply[256];
    // Run128 really began 02 dc 2e ed 01: QCA debug handle, 493-byte ACL
    // payload. The remainder here is a synthetic peer, not a recovered reply.
    for(unsigned fragment: {1u,3u,4u,7u,16u,128u,512u}) {
        clean();auto p=debug(493);p.insert(p.end(),reset.begin(),reset.end());queue(p,fragment);
        assert(receive(0,reply,sizeof(reply),0x0c03)==7&&!memcmp(reply,reset.data(),7));
        assert(boot_rx.debug_frames==1&&boot_rx.debug_bytes==493&&!boot_rx.failed);
        assert(arrivals.empty());
    }
    clean();queue(reset,4);assert(receive(0,reply,sizeof(reply),0x0c03)==7);
    assert(boot_rx.debug_frames==0&&!memcmp(reply,reset.data(),7));
    // An HCI byte pattern inside any declared diagnostic payload is not a reply.
    clean();queue(debug(65535),128);assert(receive(0,reply,sizeof(reply),0x0c03)==0);
    assert(boot_rx.debug_frames==1&&boot_rx.debug_bytes==65535&&!boot_rx.type);
    // A timeout partway through a frame retains framing, including across calls.
    clean();auto p=debug(493);queue({p.begin(),p.begin()+256},64);
    assert(receive(0,reply,sizeof(reply),0x0c03)==0&&boot_rx.type==2&&boot_rx.remaining==242);
    std::vector<uint8_t> rest(p.begin()+256,p.end());rest.insert(rest.end(),reset.begin(),reset.end());queue(rest,64);
    assert(receive(0,reply,sizeof(reply),0x0c03)==7&&!memcmp(reply,reset.data(),7));
    // Read the whole FIFO word after the event, retaining a following partial ACL.
    clean();p=reset;auto d=debug(10);p.insert(p.end(),d.begin(),d.begin()+3);queue(p,64);
    assert(receive(0,reply,sizeof(reply),0x0c03)==7&&boot_rx.type==2&&boot_rx.header_bytes==2);
    const std::vector<uint8_t> version={4,0x0e,12,1,1,0x10,0,11,0,0,11,0x1d,0,0x3f,0x37};
    rest.assign(d.begin()+3,d.end());rest.insert(rest.end(),version.begin(),version.end());queue(rest,64);
    assert(receive(0,reply,sizeof(reply),0x1001)==15&&!memcmp(reply,version.data(),15));
    // Unrelated events are framed and skipped; genuine error status is retained.
    clean();p=version;auto denied=reset;denied.back()=0x0c;p.insert(p.end(),denied.begin(),denied.end());queue(p,7);
    assert(receive(0,reply,sizeof(reply),0x0c03)==7&&reply[6]==0x0c&&boot_rx.other_events==1);
    clean();queue({0x99,4,0x0e,4,1,3,0x0c,0},64);
    assert(receive(0,reply,sizeof(reply),0x0c03)==0&&boot_rx.failed);
    clean();p=debug(5);p[1]=0x08;p[2]=0x01;queue(p,64); // SSR dump is NOT debug.
    assert(receive(0,reply,sizeof(reply),0x0c03)==0&&boot_rx.failed);
    clean();queue(reset,64);uart_error=1u<<24;
    assert(receive(0,reply,sizeof(reply),0x0c03)==0&&boot_rx.failed);
    puts("Bluetooth boot RX: production FIFO reader drains full QCA debug ACL packets, preserves H4 boundaries, matches genuine command-complete opcodes/status, retains partial frames and rejects UART/SSR/malformed data; legacy event-only path preserved");
}
'''

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'patches/nabu-wireless/NabuBluetooth.cpp').read_text()
    receive=source[source.index('static NabuBluetoothBootRx boot_rx;'):source.index('static void log_reply(')]
    cpp=a.output/'boot-rx.cpp';cpp.write_text(PREFIX+receive+TEST)
    binary=a.output/'boot-rx'
    subprocess.run(host_command(['clang++-18','-std=c++17','-O1','-g','-fsanitize=address,undefined',
        '-fno-sanitize-recover=all','-fno-omit-frame-pointer','-I'+host_path(ROOT/'patches/nabu-wireless'),
        host_path(cpp),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True,timeout=30)
    (a.output/'test.log').write_bytes(result.stdout);(a.output/'test.stderr').write_bytes(result.stderr);result.check_returncode()
    report={'hardware_tested':False,'sanitizers':['address','undefined'],'production_receive_tested':True,
        'observed_run128_prefix':'02dc2eed01','synthetic_reply_after_debug':True,'result':result.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
