#!/usr/bin/env python3
"""Check WLFW requests against protocol bytes and replay successful/error responses."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include "NabuWlfw.h"
int main(){
    NabuWlfw w{};w.prepare();
    const uint8_t register_request[]={0,1,0,0x20,0,15,0,0x10,1,0,1,0x13,1,0,1,0x15,4,0,0x4c,0x45,0x4e,0x4b};
    assert(w.bytes==sizeof(register_request)&&!memcmp(w.request,register_request,sizeof(register_request)));
    uint8_t response[]={2,1,0,0x20,0,7,0,2,4,0,0,0,0,0};w.sent();
    response[1]=9;assert(!w.receive(response,sizeof(response))&&w.waiting);response[1]=1;assert(w.receive(response,sizeof(response))&&w.step==1);
    w.prepare();assert(w.message==0x34&&w.bytes==14);w.sent();response[1]=2;response[3]=0x34;
    assert(w.receive(response,sizeof(response))&&w.step==2);w.prepare();
    const uint8_t msa_request[]={0,3,0,0x2d,0,18,0,1,8,0,0,0,0xc0,0x8b,0,0,0,0,2,4,0,0,0,0x18,0};
    assert(w.bytes==sizeof(msa_request)&&!memcmp(w.request,msa_request,sizeof(msa_request)));w.sent();
    std::vector<uint8_t> msa{2,3,0,0x2d,0,37,0,2,4,0,0,0,0,0,3,27,0,2,
        0,0,0xc0,0x8b,0,0,0,0,0,0,0x10,0,1,
        0,0,0xd0,0x8b,0,0,0,0,0,0,8,0,0};
    assert(w.receive(msa.data(),msa.size())&&w.complete&&!w.failed&&w.region_count==2);
    assert(w.regions[0].address==0x8bc00000&&w.regions[1].size==0x80000&&!w.regions[1].secure);
    NabuWlfw timeout{};timeout.prepare();timeout.sent();for(unsigned i=0;i<10000;++i)timeout.tick();assert(timeout.failed&&!timeout.waiting);
    NabuWlfw error{};error.prepare();error.sent();response[1]=1;response[3]=0x20;response[10]=1;response[12]=1;
    assert(error.receive(response,sizeof(response))&&error.failed&&!error.complete);
    puts("WLFW: golden registration/MSA requests, transaction match, two regions, error and timeout passed");
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);source=a.output/'wlfw.cpp';source.write_text(HARNESS);binary=a.output/'wlfw-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (a.output/'test.log').write_bytes(result.stdout);(a.output/'test.stderr').write_bytes(result.stderr);result.check_returncode()
    report={'production_wlfw_tested':True,'sanitizers':['address','undefined'],'result':result.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
