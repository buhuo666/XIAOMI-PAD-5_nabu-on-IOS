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
    const uint8_t register_request[]={0,1,0,0x20,0,30,0,0x10,1,0,1,0x13,1,0,1,0x14,1,0,1,0x15,4,0,0x4c,0x45,0x4e,0x4b,0x18,1,0,1,0x19,4,0,1,0,0,0};
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
    // The KNEL notification can arrive during another outstanding request.
    const uint8_t pins[]={4,0,0,0x2c,0,21,0,0x12,4,0,0xff,0xff,0xff,0xff,
        0x10,4,0,0,0,0,0,0x11,4,0,0x78,0x56,0x34,0x12};
    assert(!w.receive(pins,sizeof(pins))&&w.waiting&&w.message==0x2e&&w.step==3);
    assert(w.pin_result_count==1&&w.pin_result_step==3);
    assert(w.pin_result_valid[0]&&w.pin_result[0]==0&&w.pin_result_valid[1]&&w.pin_result[1]==0x12345678);
    assert(w.pin_result_valid[2]&&w.pin_result[2]==0xffffffffu&&!w.fw_ready&&!w.init_done);
    const uint8_t pwr_only[]={4,0,0,0x2c,0,7,0,0x10,4,0,1,0,0,0};
    w.receive(pwr_only,sizeof(pwr_only));assert(w.pin_result_count==2&&w.pin_result_valid[0]&&w.pin_result[0]==1);
    assert(!w.pin_result_valid[1]&&!w.pin_result_valid[2]&&!w.pin_result[1]&&!w.pin_result[2]);
    assert(!w.receive(pins,sizeof(pins)-1)&&w.pin_result_count==2&&w.waiting);
    response[1]=4;response[3]=0x2e;assert(w.receive(response,sizeof(response))&&w.msa_ready);
    w.prepare();assert(w.message==0x24&&w.bytes==7);w.sent();
    std::vector<uint8_t> cap{2,5,0,0x24,0,25,0,2,4,0,0,0,0,0,0x10,8,0,0x91,0x39,0,0,1,0,0,0,0x11,4,0,0x34,0x12,0,0};
    assert(w.receive(cap.data(),cap.size())&&w.complete&&w.capability_valid&&w.chip_id==0x3991&&w.board_id_valid&&w.board_id==0x1234);
    NabuWlfw missing_board{};missing_board.activate=true;missing_board.step=4;missing_board.prepare();missing_board.sent();
    response[1]=1;response[3]=0x24;assert(missing_board.receive(response,sizeof(response))&&!missing_board.board_id_valid&&missing_board.board_id==0xff);
    std::vector<uint8_t> board(26328),copied;for(unsigned i=0;i<board.size();++i)board[i]=i%251;
    w.board_data=board.data();w.board_bytes=board.size();w.complete=false;
    w.prepare();
    const uint8_t feature_request[]={0,6,0,0x3b,0,11,0,0x10,8,0,1,0,0,0,0,0,0,0};
    assert(w.local_port()==0x4003&&w.bytes==sizeof(feature_request)&&!memcmp(w.request,feature_request,sizeof(feature_request)));w.sent();
    uint8_t features[]={2,6,0,0x3b,0,29,0,2,4,0,0,0,0,0,0x10,8,0,0xef,0xcd,0xab,0x89,0x67,0x45,0x23,0x81,
        0x11,8,0,1,0,0,0,0,0,0,0};
    assert(w.receive(features,sizeof(features))&&w.dynamic_feature_complete&&w.step==5&&!w.waiting&&!w.complete);
    assert(w.dynamic_prev_valid&&w.dynamic_prev==0x8123456789abcdefULL&&w.dynamic_current_valid&&w.dynamic_current==1);
    w.prepare();unsigned dn=0;const uint8_t *dc=NabuRmtfs::tlv(w.request,w.bytes,0x15,dn);
    assert(w.message==0x20&&w.local_port()==0x4004&&dc&&dn==4&&NabuRmtfs::u32(dc)==0x444d4f4e);
    assert(!NabuRmtfs::tlv(w.request,w.bytes,0x14,dn)); // DMON registration stays as captured.
    assert(!NabuRmtfs::tlv(w.request,w.bytes,0x19,dn));
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
    // Official Xiaomi V14.0.7.0 CAL_REPORT builder + native QMI descriptor: empty IDs and optional tag 0x11=u8(0).
    const uint8_t official_cal_report_tlvs[]={1,1,0,0,0x11,1,0,0};
    w.prepare();assert(w.message==0x26&&w.local_port()==0x4004&&w.bytes==7+sizeof(official_cal_report_tlvs));
    assert(w.request[5]==sizeof(official_cal_report_tlvs)&&w.request[6]==0);
    assert(!memcmp(w.request+7,official_cal_report_tlvs,sizeof(official_cal_report_tlvs)));w.sent();
    response[1]=w.transaction;response[3]=0x26;assert(w.receive(response,sizeof(response))&&!w.complete&&w.step==8&&!w.fw_ready&&!w.init_done);
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
    NabuWlfw feature_absent{};feature_absent.board_data=board.data();feature_absent.step=5;
    feature_absent.dynamic_prev_valid=feature_absent.dynamic_current_valid=true;feature_absent.dynamic_prev=feature_absent.dynamic_current=99;
    feature_absent.prepare();feature_absent.sent();response[1]=1;response[3]=0x3b;response[10]=response[12]=0;
    assert(feature_absent.receive(response,sizeof(response))&&feature_absent.dynamic_feature_complete&&feature_absent.step==5);
    assert(!feature_absent.dynamic_prev_valid&&!feature_absent.dynamic_current_valid&&!feature_absent.dynamic_prev&&!feature_absent.dynamic_current);
    NabuWlfw feature_error{};feature_error.board_data=board.data();feature_error.step=5;feature_error.prepare();feature_error.sent();response[10]=1;response[12]=94;
    assert(feature_error.receive(response,sizeof(response))&&feature_error.failed&&!feature_error.dynamic_feature_complete);
    feature_error.prepare();assert(feature_error.bytes==0&&feature_error.step==5); // No DMON after failure.
    NabuWlfw recovery{};recovery.board_data=board.data();recovery.board_bytes=board.size();recovery.step=6;recovery.prepare();recovery.sent();
    uint16_t old_transaction=recovery.transaction;
    const uint8_t rejuvenate[]={4,0,0,0x39,0,20,0,0x10,1,0,0x81,0x11,1,0,3,0x12,2,0,0x34,0x12,0x13,4,0,'i','n','i','t'};
    assert(!recovery.receive(rejuvenate,sizeof(rejuvenate))&&recovery.rejuvenate_count==1&&!recovery.waiting&&!recovery.complete);
    assert(recovery.rejuvenate_valid[0]&&recovery.rejuvenate_cause==0x81&&recovery.rejuvenate_valid[1]&&recovery.rejuvenate_subsystem==3);
    assert(recovery.rejuvenate_valid[2]&&recovery.rejuvenate_line==0x1234&&recovery.rejuvenate_valid[3]&&!strcmp(recovery.rejuvenate_function,"init"));
    recovery.prepare();assert(recovery.message==0x3a&&recovery.bytes==7&&recovery.local_port()==0x4003&&recovery.transaction==old_transaction+1);recovery.sent();
    response[1]=old_transaction;response[3]=0x25;response[10]=response[12]=0;
    assert(!recovery.receive(response,sizeof(response))&&recovery.waiting&&recovery.board_sent==0);
    recovery.receive(rejuvenate,sizeof(rejuvenate));assert(recovery.rejuvenate_count==2&&recovery.waiting&&recovery.transaction==old_transaction+1);
    response[1]=recovery.transaction;response[3]=0x3a;
    assert(recovery.receive(response,sizeof(response))&&recovery.rejuvenate_ack_finished&&recovery.rejuvenate_ack_success&&!recovery.failed);
    recovery.prepare();assert(recovery.bytes==0&&recovery.step==6&&recovery.board_sent==0&&!recovery.complete);
    const uint8_t empty_rejuvenate[]={4,0,0,0x39,0,0,0};
    recovery.receive(empty_rejuvenate,sizeof(empty_rejuvenate));
    assert(!recovery.rejuvenate_valid[0]&&!recovery.rejuvenate_valid[1]&&!recovery.rejuvenate_valid[2]&&!recovery.rejuvenate_valid[3]&&!recovery.rejuvenate_function[0]);
    NabuWlfw ack_error{};ack_error.receive(empty_rejuvenate,sizeof(empty_rejuvenate));ack_error.prepare();ack_error.sent();
    response[1]=ack_error.transaction;response[3]=0x3a;response[10]=1;response[12]=1;
    assert(ack_error.receive(response,sizeof(response))&&ack_error.rejuvenate_ack_finished&&!ack_error.rejuvenate_ack_success&&ack_error.failed);
    NabuWlfw ack_timeout{};ack_timeout.receive(empty_rejuvenate,sizeof(empty_rejuvenate));ack_timeout.prepare();ack_timeout.sent();
    for(unsigned i=0;i<10000;++i)ack_timeout.tick();assert(ack_timeout.failed&&!ack_timeout.waiting&&!ack_timeout.rejuvenate_ack_success);
    // Reproduce v114: setup completed, then the firmware instance crashed.
    w.permissions_ready=true;
    unsigned saved_step=w.step,saved_board=w.board_sent;
    w.invalidate();
    assert(w.instance_lost&&w.failed&&!w.complete&&!w.waiting&&!w.bytes);
    assert(!w.fw_ready&&!w.init_done&&!w.msa_ready&&!w.capability_valid&&!w.board_id_valid&&!w.mac_set);
    assert(!w.status_valid&&!w.fw_status&&!w.dynamic_feature_complete);
    assert(w.permissions_ready&&w.step==saved_step&&w.board_sent==saved_board);
    w.receive(ready,sizeof(ready));w.receive(initialized,sizeof(initialized));
    w.receive(rejuvenate,sizeof(rejuvenate));w.prepare();
    assert(!w.fw_ready&&!w.init_done&&!w.rejuvenate_count&&!w.bytes);
    // An in-flight BDF response cannot advance the retired instance either.
    NabuWlfw pending{};pending.board_data=board.data();pending.board_bytes=board.size();pending.step=6;
    pending.prepare();pending.sent();response[1]=pending.transaction;response[3]=0x25;response[10]=response[12]=0;
    pending.invalidate();assert(!pending.receive(response,sizeof(response))&&pending.board_sent==0&&pending.step==6);
    pending.prepare();pending.tick();assert(!pending.bytes&&!pending.waiting&&pending.failed);
    puts("WLFW: PFR instance retirement and late response/indication rejection, retained MSA ownership, official Xiaomi CAL_REPORT, feature-mask ordering, KNEL/DMON recovery, BDF/MSA/MAC, errors and timeout passed");
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);source=a.output/'wlfw.cpp';source.write_text(HARNESS);binary=a.output/'wlfw-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (a.output/'test.log').write_bytes(result.stdout);(a.output/'test.stderr').write_bytes(result.stderr);result.check_returncode()
    report={'production_wlfw_tested':True,'sanitizers':['address','undefined'],
            'cal_report_tlv_body':'0101000011010000','cal_report_optional_tlv11_semantics':'unknown; matches official Xiaomi native encoding',
            'result':result.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
