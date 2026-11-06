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
    const uint8_t register_request[]={0,1,0,0x20,0,19,0,0x10,1,0,1,0x13,1,0,1,0x15,4,0,0x4c,0x45,0x4e,0x4b,0x18,1,0,1};
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
    w.activate=true;w.complete=false;w.prepare();assert(w.message==0x2e&&w.bytes==7);w.sent();
    response[1]=4;response[3]=0x2e;assert(w.receive(response,sizeof(response))&&w.msa_ready);
    w.prepare();assert(w.message==0x24&&w.bytes==7);w.sent();
    std::vector<uint8_t> cap{2,5,0,0x24,0,25,0,2,4,0,0,0,0,0,0x10,8,0,0x91,0x39,0,0,1,0,0,0,0x11,4,0,0x34,0x12,0,0};
    assert(w.receive(cap.data(),cap.size())&&w.complete&&w.capability_valid&&w.chip_id==0x3991&&w.board_id_valid&&w.board_id==0x1234);
    NabuWlfw missing_board{};missing_board.activate=true;missing_board.step=4;missing_board.prepare();missing_board.sent();
    response[1]=1;response[3]=0x24;assert(missing_board.receive(response,sizeof(response))&&!missing_board.board_id_valid&&missing_board.board_id==0xff);
    std::vector<uint8_t> board(26328),copied;for(unsigned i=0;i<board.size();++i)board[i]=i%251;
    w.board_data=board.data();w.board_bytes=board.size();w.complete=false;
    w.prepare();unsigned dn=0;const uint8_t *dc=NabuRmtfs::tlv(w.request,w.bytes,0x15,dn);
    assert(w.message==0x20&&w.local_port()==0x4004&&dc&&dn==4&&NabuRmtfs::u32(dc)==0x444d4f4e);
    w.sent();response[1]=w.transaction;response[3]=0x20;assert(w.receive(response,sizeof(response))&&w.step==6);
    NabuWlfw host{};host.board_data=board.data();host.step=1;host.prepare();
    const uint8_t *support=NabuRmtfs::tlv(host.request,host.bytes,0x10,dn);assert(support&&dn==4&&NabuRmtfs::u32(support)==1);
    while(w.step==6){
        w.prepare();unsigned n=0;const uint8_t *p=NabuRmtfs::tlv(w.request,w.bytes,0x13,n);
        assert(p&&n==w.chunk+2&&NabuRmtfs::u16(p)==w.chunk&&w.bytes<8192-32);
        assert(w.chunk==(w.board_segment<4?6144u:1752u));
        unsigned tn=0;const uint8_t *type=NabuRmtfs::tlv(w.request,w.bytes,0x15,tn);assert(type&&tn==1&&type[0]==0);
        copied.insert(copied.end(),p+2,p+n);w.sent();response[1]=w.transaction;response[3]=0x25;
        assert(w.receive(response,sizeof(response))&&!w.failed);
    }
    assert(copied==board&&w.board_sent==board.size()&&w.board_segment==5);
    const uint8_t mac[]={2,0x11,0x22,0x33,0x44,0x55};w.mac_available=true;memcpy(w.mac_address,mac,6);
    w.prepare();assert(w.message==0x26&&w.bytes==11&&w.request[7]==1&&w.request[10]==0);w.sent();
    response[1]=w.transaction;response[3]=0x26;assert(w.receive(response,sizeof(response))&&!w.complete&&w.step==8);
    w.prepare();assert(w.message==0x33&&w.bytes==16&&w.request[7]==0x10&&w.request[8]==6&&!memcmp(w.request+10,mac,6));
    w.sent();response[1]=w.transaction;response[3]=0x33;assert(w.receive(response,sizeof(response))&&w.mac_set&&w.complete);
    w.prepare();assert(w.bytes==0); // Wait for indications without registering the live daemon again.
    NabuWlfw registration{};registration.prepare();registration.sent();
    std::vector<uint8_t> status{2,1,0,0x20,0,18,0,2,4,0,0,0,0,0,0x10,8,0,0x1f,0,0,0,0,0,0,0};
    assert(registration.receive(status.data(),status.size())&&registration.status_valid&&registration.fw_status==0x1f);
    uint8_t ready[]={4,0,0,0x21,0,0,0};w.receive(ready,sizeof(ready));assert(w.fw_ready);
    uint8_t initialized[]={4,0,0,0x38,0,0,0};w.receive(initialized,sizeof(initialized));assert(w.init_done);
    NabuWlfw absent{};absent.status_valid=true;absent.fw_status=0x1f;absent.prepare();absent.sent();
    response[1]=1;response[3]=0x20;assert(absent.receive(response,sizeof(response))&&!absent.status_valid&&!absent.fw_status);
    NabuWlfw timeout{};timeout.prepare();timeout.sent();for(unsigned i=0;i<10000;++i)timeout.tick();assert(timeout.failed&&!timeout.waiting);
    NabuWlfw error{};error.prepare();error.sent();response[1]=1;response[3]=0x20;response[10]=1;response[12]=1;
    assert(error.receive(response,sizeof(response))&&error.failed&&!error.complete);
    puts("WLFW: dual registration/MSA, BIN board segments, calibration and board MAC without re-registration, ready/init indications, errors and timeout passed");
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
