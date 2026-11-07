#!/usr/bin/env python3
"""Replay HTC READY/connect/setup and WCN399x credit flow against fixed wire examples."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include "NabuHtc.h"
static bool feed(NabuHtc &h,std::vector<uint8_t> frame){unsigned ep,n;const uint8_t *p;return h.receive(frame.data(),frame.size(),ep,p,n);}
int main(){
    NabuHtc h;assert(!h.connect(0x100));
    // HTC header eid0,len8; READY id1,credits32,size256,endpoints9.
    const std::vector<uint8_t> ready{0,0,8,0,0,0,0,0,1,0,32,0,0,1,9,0};
    assert(feed(h,ready)&&h.state==NabuHtc::Ready&&h.credit_size==256&&h.credit_count==1&&h.reported_credits==32);
    assert(h.connect(0x100));
    const uint8_t wmi[]={0,0,8,0,0,0,0,0,2,0,0,1,0,1,0,0};
    assert(h.bytes==sizeof(wmi)&&!memcmp(h.request,wmi,sizeof(wmi))&&!h.waiting);
    assert(!feed(h,{0,0,8,0,0,0,0,0,3,0,0,1,0,2,0,8}));
    h.sent();assert(h.waiting&&h.endpoints[0].sequence==1);
    assert(!feed(h,{0,0,8,0,0,0,0,0,3,0,0,3,0,1,0,8})&&h.waiting);
    assert(feed(h,{0,0,8,0,0,0,0,0,3,0,0,1,0,2,0,8})&&h.endpoint_for(0x100)==2);
    assert(!h.setup());assert(h.connect(0x300));
    const uint8_t htt[]={0,0,8,0,0,1,0,0,2,0,0,3,8,0,0,0};
    assert(h.bytes==sizeof(htt)&&!memcmp(h.request,htt,sizeof(htt)));h.sent();
    assert(feed(h,{0,0,8,0,0,0,0,0,3,0,0,3,0,1,0,8}));
    assert(h.setup());
    const uint8_t setup[]={0,0,12,0,0,2,0,0,5,0,0,0,0,0,0,0,0,0,0,0};
    assert(h.bytes==sizeof(setup)&&!memcmp(h.request,setup,sizeof(setup)));h.sent();assert(h.state==NabuHtc::Started);
    uint8_t packet[300]{};assert(h.prepare_wmi(packet,248)&&packet[0]==2&&packet[1]==1&&packet[5]==0);
    assert(!h.prepare_wmi(packet,249));h.wmi_sent(248);assert(!h.prepare_wmi(packet,1)&&h.endpoints[2].credits==0);
    // Credit-only RX: 4-byte record header and one 4-byte credit entry.
    assert(feed(h,{2,2,8,0,8,0,0,0,1,4,0,0,2,2,0,0}));
    assert(h.endpoints[2].credits==2&&h.prepare_wmi(packet,249)&&packet[5]==1);
    const std::vector<uint8_t> bad{2,2,8,0,8,0,0,0,1,8,0,0,2,99,0,0};
    assert(!feed(h,bad)&&h.endpoints[2].credits==2);
    unsigned ep=0,len=0;const uint8_t *payload=nullptr;
    const uint8_t rx[]={2,2,12,0,8,0,0,0,0x11,0x22,0x33,0x44,1,4,0,0,2,1,0,0};
    assert(h.receive(rx,sizeof(rx),ep,payload,len)&&ep==2&&len==4&&payload[0]==0x11&&h.endpoints[2].credits==3);
    assert(feed(h,{0,2,8,0,8,0,0,0,1,4,0,0,2,1,0,0})&&h.endpoints[2].credits==4);
    h.invalidate();assert(!feed(h,ready)&&!h.prepare_wmi(packet,1)&&!h.endpoint_for(0x100));
    NabuHtc failed;assert(feed(failed,ready)&&failed.connect(0x100));failed.sent();
    assert(!feed(failed,{0,0,8,0,0,0,0,0,3,0,0,1,3,2,0,8})&&failed.state==NabuHtc::Failed);
    NabuHtc timeout;for(unsigned i=0;i<5000;++i)timeout.tick();assert(timeout.state==NabuHtc::Failed);
    NabuHtc short_ready;assert(!feed(short_ready,{0,0,4,0,0,0,0,0,1,0,1,0}));
    puts("HTC: fixed SNOC READY credits, actual endpoint assignments, WMI/HTT connect, extended setup, credit exhaustion/return, trailer stripping, errors/timeout and retired instance rejection passed");
}
'''
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    source=a.output/'htc.cpp';source.write_text(HARNESS);binary=a.output/'htc-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    r=subprocess.run(host_command([host_path(binary)]),capture_output=True);(a.output/'test.log').write_bytes(r.stdout);(a.output/'test.stderr').write_bytes(r.stderr);r.check_returncode()
    report={'hardware_tested':False,'sanitizers':['address','undefined'],'result':r.stdout.decode().strip(),'source':'SeimoDev/linux-xiaomi-nabu@4e6d08bb1b467c721e19cd693e4ec7388d982d73 ath10k htc.[ch], core.c WCN3990'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
