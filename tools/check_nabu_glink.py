#!/usr/bin/env python3
"""Replay a modem peer against the production GLINK ring and QRTR parser."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = r'''
#include <cassert>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include "NabuSmem.h"
#include "NabuTftp.h"
#include "NabuServreg.h"
#include "NabuWlfw.h"
#include "NabuDiagFrames.h"
using vm_offset_t = uintptr_t;
static void *IOMalloc(size_t n) { return malloc(n); }
static void IOFree(void *p, size_t) { free(p); }
static void IOSleep(unsigned) {}
static constexpr const char *gIODTPlane = "IODeviceTree";
struct IORegistryEntry {
    static IORegistryEntry *fromPath(const char *, const char *) { return nullptr; }
    void setProperty(const char *, const void *, unsigned) {}
    void release() {}
};
static bool rmtfs_available;
static unsigned rmtfs_request_calls;
static bool nabu_rmtfs_available() { return rmtfs_available; }
static unsigned nabu_rmtfs_request(const uint8_t *, unsigned, uint8_t *) { ++rmtfs_request_calls;return 0; }
static unsigned msa_prepare_calls;
static bool nabu_msa_prepare(const NabuWlfw::Region *,unsigned) { ++msa_prepare_calls;return true; }
static std::string captured_log;
static void nabu_wireless_log(const char *format, ...) {
    char line[1024];va_list args,copy;va_start(args,format);va_copy(copy,args);
    vsnprintf(line,sizeof(line),format,copy);va_end(copy);captured_log+=line;
    vprintf(format,args);va_end(args);
}
static std::string captured_bulk_log;
static void IOLog(const char *format, ...) {
    char line[1024];va_list args;va_start(args,format);
    vsnprintf(line,sizeof(line),format,args);va_end(args);captured_bulk_log+=line;
}
static uintptr_t smem_va;
static uint32_t hardware_lock;
static int hakios_smem_alloc_lock;
static constexpr unsigned VM_WIMG_IO = 7;
static uintptr_t map_region(const char *, uintptr_t, size_t, unsigned) { return (uintptr_t)&hardware_lock; }
static void lck_mtx_lock(int *) {}
static void lck_mtx_unlock(int *) {}
static void IODelay(unsigned) {}
static uint32_t rd(uintptr_t at) { return *(uint32_t *)at; }
static void wr(uintptr_t at, uint32_t value) { *(uint32_t *)at = value; }
'''
TEST = r'''
alignas(16) static uint8_t shared[65536];
static uint32_t doorbell;
static void put32(unsigned at, uint32_t v) { memcpy(shared+at,&v,4); }
static void receive(NabuGlink &g, uint16_t cmd, uint16_t channel, uint32_t value, const void *data=nullptr, unsigned bytes=0) {
    GlinkMessage h{cmd,channel,value}; unsigned head=g.word(12), size=(8+bytes+7)&~7u;
    for(unsigned i=0;i<size;++i) shared[g.rx.offset+(head+i)%g.rx.size]=i<8?((uint8_t*)&h)[i]:i<8+bytes?((const uint8_t*)data)[i-8]:0;
    put32(g.descriptor.offset+12,(head+size)%g.rx.size);
}
static void data(NabuGlink &g, const std::vector<uint8_t> &packet, unsigned first) {
    std::vector<uint8_t> payload(8+first); uint32_t n=first,left=packet.size()-first;
    memcpy(payload.data(),&n,4);memcpy(payload.data()+4,&left,4);memcpy(payload.data()+8,packet.data(),first);
    receive(g,9,9,1,payload.data(),payload.size());g.pump();
    if(left) {
        payload.resize(8+left);n=left;left=0;memcpy(payload.data(),&n,4);memcpy(payload.data()+4,&left,4);
        memcpy(payload.data()+8,packet.data()+first,n);receive(g,12,9,1,payload.data(),payload.size());g.pump();
    }
}
static unsigned count_command(NabuGlink &g, unsigned wanted) {
    unsigned at=0,count=0;
    while(at!=g.word(4)) {
        GlinkMessage h;memcpy(&h,shared+g.tx.offset+at,8);unsigned size=8;
        if(h.command==2)size+=h.value&0xffff;
        if(h.command==5)size+=h.value*8;
        if(h.command==9){uint32_t bytes;memcpy(&bytes,shared+g.tx.offset+at+8,4);size=16+bytes;}
        if(h.command==wanted)++count;
        at=(at+((size+7)&~7u))%g.tx.size;
    }
    return count;
}
static void check_tftp_reuse() {
    NabuGlink g{};
    uint8_t firmware[600];
    for (unsigned i=0;i<sizeof(firmware);++i) firmware[i]=i;
    g.wlan_firmware=firmware;g.wlan_bytes=sizeof(firmware);
    const uint8_t negotiated[]="\0\1/readonly/firmware/image/wlanmdsp.mbn\0octet\0blksize\0" "4000";
    g.tftp(0,23,0x4000,negotiated,sizeof(negotiated));
    NabuTftp &t=g.transfers[0];
    assert(t.block_size==4000&&t.options&&t.payload[1]==6);
    uint8_t ack[]={0,4,0,0};t.sent();g.tftp(0,23,0x4010,ack,sizeof(ack));
    assert(t.payload_bytes==604&&t.payload[1]==3);
    t.sent();ack[3]=1;g.tftp(0,23,0x4010,ack,sizeof(ack));
    assert(t.complete&&!t.active&&!t.pending&&g.tftp_completed==1);
    // Reuse the completed transfer without options; do not carry its block size or state forward.
    const uint8_t plain[]="\0\1/readonly/firmware/image/wlanmdsp.mbn\0octet";
    g.tftp(0,29,0x4000,plain,sizeof(plain));
    assert(t.block_size==512&&!t.options&&!t.complete&&!t.last&&t.block==1);
    assert(t.peer_port==29&&t.delivered==0&&t.payload_bytes==516);
    assert(t.payload[1]==3&&!memcmp(t.payload+4,firmware,512));
    assert(g.tftp_requests==2&&g.tftp_completed==1);
}
static void check_diag_observation() {
    memset(shared,0,sizeof(shared));
    NabuGlink g{};g.memory={shared,sizeof(shared)};g.doorbell=&doorbell;
    g.descriptor={0,32};g.tx={0x4000,16384};g.rx={0x8000,16384};
    uint8_t firmware[4]{};g.wlan_firmware=firmware;g.wlan_bytes=sizeof(firmware);
    g.registry.records=firmware;rmtfs_available=true;g.qmi_enabled=true;
    std::vector<uint8_t> packet;
    auto feed_control=[&](unsigned command,unsigned service){
        QrtrHeader h{1,command,0,control_port,0,20,1,control_port};
        QrtrControl c{command,{service,0,0,0}};
        packet.resize(52);memcpy(packet.data(),&h,32);memcpy(packet.data()+32,&c,20);
        g.qrtr(packet.data(),packet.size());
    };
    auto queued=[&](unsigned i)->const NabuGlink::Pending &{return g.pending[(g.pending_head+i)%16];};
    auto check_servers=[&](unsigned at){
        for(unsigned i=0;i<2;++i){
            const auto &p=queued(at+i);
            assert(p.header.type==4&&p.header.from_node==1&&p.header.from_port==control_port);
            assert(p.header.to_node==0&&p.header.to_port==control_port&&p.header.size==20);
            assert(p.control.command==4&&p.control.words[0]==4097&&p.control.words[1]==2*i);
            assert(p.control.words[2]==1&&p.control.words[3]==0x4005+i);
        }
    };
    feed_control(2,0);
    assert(g.pending_count==6&&g.diag_servers_queued==2&&!g.broken);
    assert(queued(0).control.command==2&&queued(1).control.words[0]==14);
    assert(queued(2).control.words[0]==64&&queued(3).control.words[0]==4096);
    check_servers(4);
    // The new advertisements use existing QRTR control frames and GLINK intents.
    g.opened=true;for(unsigned i=0;i<6;++i)g.remote[i]={100+i,1024,true,false};
    g.flush();assert(g.pending_count==0&&count_command(g,9)==6&&!g.broken);
    for(unsigned i=0;i<6;++i){
        NabuGlink::Pending p;memcpy(&p,shared+g.tx.offset+72*i+16,sizeof(p));
        assert(p.header.type==(i?4u:2u));
        if(i>=4)assert(p.control.words[0]==4097&&p.control.words[1]==2*(i-4)&&p.control.words[3]==0x4005+i-4);
    }
    feed_control(10,4097);assert(g.pending_count==3);check_servers(0);
    assert(queued(2).control.command==4&&queued(2).control.words[0]==0);
    g.pending_head=g.pending_count=0;
    feed_control(10,0);assert(g.pending_count==6);check_servers(3);
    assert(queued(0).control.words[0]==14&&queued(1).control.words[0]==64&&queued(2).control.words[0]==4096);
    g.pending_head=g.pending_count=0;
    feed_control(10,0x45);assert(g.pending_count==1&&queued(0).control.words[0]==0);
    g.pending_head=g.pending_count=0;g.qmi_enabled=false;
    feed_control(10,4097);assert(g.pending_count==1&&g.diag_servers_queued==6);
    g.pending_head=g.pending_count=0;g.qmi_enabled=true;
    g.wlfw.step=6;g.wlfw.waiting=true;g.wlfw_node=0;g.wlfw_port=90;
    auto feed_diag=[&](unsigned port,const uint8_t *body,unsigned bytes,unsigned node,unsigned source){
        QrtrHeader h{1,1,node,source,0,bytes,1,port};
        packet.resize(32+bytes);memcpy(packet.data(),&h,32);if(bytes)memcpy(packet.data()+32,body,bytes);
        g.qrtr(packet.data(),packet.size());
    };
    uint8_t body[80];for(unsigned i=0;i<sizeof(body);++i)body[i]=i;
    uint32_t id=8,length=72;memcpy(body,&id,4);memcpy(body+4,&length,4);
    captured_log.clear();feed_diag(0x4005,body,sizeof(body),0,90);
    assert(captured_log.find("inst=0 packet=1 from=0:90 bytes=80 id=8 len=72 fits=1 raw[32]=0800000048000000")!=std::string::npos);
    assert(captured_log.find("1c1d1e1f\n")!=std::string::npos&&captured_log.find("20212223")==std::string::npos);
    length=999;memcpy(body+4,&length,4);feed_diag(0x4005,body,8,0,90);
    const uint8_t short_header[]={0xff,0xfe,0xfd};feed_diag(0x4005,short_header,sizeof(short_header),0,90);
    assert(captured_log.find("len=999 fits=0")!=std::string::npos&&captured_log.find("header=short raw[3]=fffefd")!=std::string::npos);
    size_t log_bytes=captured_log.size();feed_diag(0x4005,body,20,1,91);feed_diag(0x4005,nullptr,0,1,91);
    assert(captured_log.size()==log_bytes&&g.diag[0].packets==5&&g.diag[0].captured_packets==3);
    assert(g.diag[0].bytes==111&&g.diag[0].captured_bytes==43&&g.diag[0].source_changes==1);
    assert(g.diag[0].source_node==1&&g.diag[0].source_port==91);
    // A truncated transport datagram must not become a captured DIAG packet or ACK.
    packet.resize(33);QrtrHeader truncated{1,1,0,90,1,8,1,0x4005};memcpy(packet.data(),&truncated,32);
    g.qrtr(packet.data(),packet.size());assert(g.diag[0].packets==5&&g.pending_count==0);
    // v2 header with extension and confirm: only the normal QRTR RESUME_TX is queued.
    packet.assign(20+64,0);packet[0]=3;packet[1]=1;packet[2]=1;packet[3]=4;packet[4]=64;
    packet[10]=100;packet[12]=1;packet[14]=6;packet[15]=0x40;memcpy(packet.data()+20,body,64);
    g.qrtr(packet.data(),packet.size());assert(g.diag[1].packets==1&&g.pending_count==1);
    const auto &ack=queued(0);
    assert(ack.header.type==7&&ack.header.from_port==0x4006&&ack.header.to_node==0&&ack.header.to_port==100);
    assert(ack.control.command==7&&ack.control.words[0]==1&&ack.control.words[1]==0x4006);
    feed_diag(0x4006,body,1,0,100);feed_diag(0x4006,nullptr,0,0,100);
    log_bytes=captured_log.size();feed_diag(0x4006,body,10,3,101);
    assert(captured_log.size()==log_bytes&&g.diag[1].packets==4&&g.diag[1].captured_packets==3);
    assert(g.diag[1].bytes==75&&g.diag[1].captured_bytes==33&&g.diag[1].source_changes==1);
    assert(g.diag[1].source_node==3&&g.diag[1].source_port==101);
    assert(g.wlfw.step==6&&g.wlfw.waiting&&!g.wlfw.fw_ready&&g.wlfw_port==90);
    assert(g.tftp_requests==0&&g.tftp_completed==0&&g.registry.requests==0&&rmtfs_request_calls==0);
    assert(g.response_count==0&&g.pending_count==1&&!g.broken&&count_command(g,9)==6);
    g.diag_summary();assert(captured_log.size()<4096);
    assert(captured_log.find("inst=0 packets=5 captured=3 omitted=2 bytes=111 raw-bytes=43 omitted-bytes=68 last=1:91 changes=1")!=std::string::npos);
    assert(captured_log.find("inst=2 packets=4 captured=3 omitted=1 bytes=75 raw-bytes=33 omitted-bytes=42 last=3:101 changes=1")!=std::string::npos);
    NabuGlink empty{};captured_log.clear();empty.diag_summary();
    assert(captured_log.find("inst=0 packets=0 captured=0 omitted=0 bytes=0 raw-bytes=0 omitted-bytes=0")!=std::string::npos);
    assert(captured_log.find("inst=2 packets=0 captured=0 omitted=0 bytes=0 raw-bytes=0 omitted-bytes=0")!=std::string::npos);
    rmtfs_available=false;
}
static void check_diag_handshake() {
    memset(shared,0,sizeof(shared));
    NabuGlink g{};g.memory={shared,sizeof(shared)};g.doorbell=&doorbell;
    g.descriptor={0,32};g.tx={0x4000,16384};g.rx={0x8000,16384};g.qmi_enabled=true;
    const uint8_t feature[]={8,0,0,0,7,0,0,0,3,0,0,0,0xf7,0xfe,3};
    const uint8_t expected[]={8,0,0,0,8,0,0,0,4,0,0,0,0x51,0xa0,0,0};
    const uint8_t presets[]={12,0,0,0,1,0,0,0,2};
    auto feed=[&](NabuGlink &link,const uint8_t *body,unsigned bytes,unsigned port=26){
        QrtrHeader h{1,1,0,port,0,bytes,1,0x4005};
        std::vector<uint8_t> packet(32+bytes);memcpy(packet.data(),&h,32);memcpy(packet.data()+32,body,bytes);
        link.qrtr(packet.data(),packet.size());
    };
    auto id_request=[](const char *name){
        unsigned n=strlen(name)+1;
        std::vector<uint8_t> record(16+n);uint32_t words[]={33,8+n,1,0};
        memcpy(record.data(),words,16);memcpy(record.data()+16,name,n);return record;
    };
    auto response=[&](unsigned i)->const NabuGlink::Response &{return g.responses[(g.response_head+i)%8];};
    feed(g,feature,sizeof(feature));
    assert(g.diag_feature_queued&&!g.diag_feature_tx&&g.response_count==1);
    assert(response(0).node==0&&response(0).port==26&&response(0).from==0x4005&&response(0).bytes==16);
    assert(!memcmp(response(0).data,expected,sizeof(expected))&&g.diag_feature_mask_bytes==3);
    assert(g.diag_feature_mask[0]==0xf7&&g.diag_feature_mask[1]==0xfe&&g.diag_feature_mask[2]==3);
    feed(g,feature,sizeof(feature));feed(g,presets,sizeof(presets));
    assert(g.response_count==1&&g.diag_feature_records==2&&g.diag_presets==2);
    auto root=id_request("modem/root_pd"),wlan=id_request("modem/wlan_pd");
    feed(g,root.data(),root.size());feed(g,root.data(),root.size());feed(g,wlan.data(),wlan.size());
    assert(g.response_count==4&&g.diag_id_count==2&&g.diag_root_id==2&&g.diag_wlan_id==3&&!g.diag_root_id_tx);
    for(unsigned i=1;i<4;++i){
        NabuSmem r{response(i).data,response(i).bytes};
        assert(r.u32(0)==33&&r.u32(8)==1&&r.u32(12)==(i==3?3u:2u));
        assert(r.u32(4)+8==response(i).bytes&&response(i).port==26);
    }
    assert(!strcmp((char*)response(1).data+16,"modem/root_pd"));
    assert(!strcmp((char*)response(3).data+16,"modem/wlan_pd"));
    // Feature and ID replies travel through the actual GLINK data sender, in order.
    g.opened=true;for(unsigned i=0;i<8;++i)g.remote[i]={100+i,1024,true,false};
    g.tftp_flush();
    assert(g.response_count==0&&g.diag_feature_tx&&g.diag_root_id_tx&&g.diag_replies_tx==4&&!g.broken);
    QrtrHeader first;memcpy(&first,shared+g.tx.offset+16,32);
    assert(first.type==1&&first.from_port==0x4005&&first.to_node==0&&first.to_port==26&&first.size==16);
    assert(!memcmp(shared+g.tx.offset+48,expected,sizeof(expected)));
    assert(g.wlfw.step==0&&!g.wlfw.waiting&&g.tftp_requests==0&&g.registry.requests==0);
    auto unknown=id_request("unrecognized/pd");feed(g,unknown.data(),unknown.size());
    assert(g.diag_id_unknown==1&&g.response_count==0&&g.diag_id_count==2);
    auto invalid=root;invalid[8]=2;feed(g,invalid.data(),invalid.size());
    invalid=root;invalid.back()='X';feed(g,invalid.data(),invalid.size());
    assert(g.diag_control_invalid==2&&g.response_count==0);
    // IDs follow real request order, not a hard-coded root=2/WLAN=3 assumption.
    NabuGlink reordered{};reordered.qmi_enabled=true;
    feed(reordered,feature,sizeof(feature));feed(reordered,wlan.data(),wlan.size());feed(reordered,root.data(),root.size());
    assert(reordered.diag_wlan_id==2&&reordered.diag_root_id==3&&reordered.diag_id_count==2);
    // One real transport datagram can contain multiple control records.
    NabuGlink compound{};compound.qmi_enabled=true;std::vector<uint8_t> body;
    auto append=[&](const uint8_t *p,unsigned n){body.insert(body.end(),p,p+n);};
    append(feature,sizeof(feature));append(presets,sizeof(presets));append(root.data(),root.size());
    const uint8_t ssids[]={24,0,0,0,12,0,0,0,1,0,0,0,1,0,0,0,100,0,101,0};
    const uint8_t masks[]={25,0,0,0,20,0,0,0,1,0,0,0,1,0,0,0,100,0,101,0,4,0,0,0,16,0,0,0};
    const uint8_t pd[]={30,0,0,0,9,0,0,0,1,0,0,0,8,0,0,0,0};
    const uint8_t registration[]={1,0,0,0,20,0,0,0,1,0,0,0,75,0,12,0,1,0,0,0,2,0,3,0,0,0,0,0};
    append(ssids,sizeof(ssids));append(masks,sizeof(masks));append(pd,sizeof(pd));append(registration,sizeof(registration));
    captured_log.clear();feed(compound,body.data(),body.size());
    assert(compound.diag_control_records==7&&compound.diag_control_invalid==0&&compound.response_count==2);
    assert(compound.diag_ssid_records==1&&compound.diag_build_records==1&&compound.diag_pd_records==1&&compound.diag_registration_records==1);
    assert(captured_log.find("ssid=100..101 masks=2 first-mask=0x4 last-mask=0x10")!=std::string::npos);
    assert(captured_log.find("pd-status version=1 pd=8 status=0")!=std::string::npos);
    assert(captured_log.find("registration version=1 cmd=75 subsys=12 ranges=1 port=0")!=std::string::npos);
    assert(compound.diag_root_id==2&&compound.diag_wlan_id==0&&compound.diag_presets==2);
    // Parse all records after the raw sample budget; a truncated record is not read.
    feed(compound,presets,sizeof(presets));feed(compound,presets,sizeof(presets));feed(compound,wlan.data(),wlan.size());
    assert(compound.diag[0].captured_packets==3&&compound.diag_wlan_id==3&&compound.response_count==3);
    const uint8_t truncated[]={25,0,0,0,12,0,0,0,1,0,0,0};
    feed(compound,truncated,sizeof(truncated));assert(compound.diag_control_invalid==1&&compound.response_count==3);
    // Failed enqueue must not claim feature completion; peer retransmission can retry.
    NabuGlink full{};full.qmi_enabled=true;full.response_count=8;
    feed(full,feature,sizeof(feature));assert(!full.diag_feature_queued&&full.diag_reply_full==1);
    full.response_count=0;feed(full,feature,sizeof(feature));assert(full.diag_feature_queued&&full.response_count==1);
    // A restarted control endpoint gets a new ID session; queued old replies are not redirected.
    memset(shared,0,sizeof(shared));NabuGlink moved{};
    moved.memory={shared,sizeof(shared)};moved.doorbell=&doorbell;moved.descriptor={0,32};moved.tx={0x4000,16384};moved.rx={0x8000,16384};moved.qmi_enabled=true;
    feed(moved,feature,sizeof(feature));feed(moved,root.data(),root.size());
    feed(moved,feature,sizeof(feature),30);assert(moved.diag_id_count==0&&moved.diag_root_id==0&&moved.diag_control_port==30);
    moved.opened=true;moved.remote[0]={100,1024,true,false};moved.tftp_flush();
    assert(moved.response_count==0&&moved.diag_replies_tx==1&&moved.diag_feature_tx&&!moved.diag_root_id_tx);
    memcpy(&first,shared+moved.tx.offset+16,32);assert(first.to_port==30&&first.size==16);
}
// Expected wire values below come from the fixed MiCode command transport and
// original modem.b19 WLAN ULog dispatcher, not from the production serializer.
// See wireless-v110/diag-command-route/protocol-spec.json and
// analysis/nabu-wlan-ulog-export-v110.md. This peer supplies responses, not hardware.
struct UlogPeer {
    NabuGlink g{};
    struct Tx { QrtrHeader header; std::vector<uint8_t> payload, wire; };
    uint8_t board[4]{};
    UlogPeer() {
        memset(shared,0,sizeof(shared));g.memory={shared,sizeof(shared)};g.doorbell=&doorbell;
        g.descriptor={0,32};g.tx={0x4000,16384};g.rx={0x8000,16384};
        g.qmi_enabled=true;g.ulog_enabled=true;g.opened=true;reset_tx();
    }
    void reset_tx() {
        put32(0,0);put32(4,0);g.intent_requested=false;
        for(unsigned i=0;i<16;++i)g.remote[i]={100+i,8192,true,false};
    }
    void feed(const std::vector<uint8_t> &body,unsigned local=0x4005,unsigned node=3,unsigned port=51) {
        QrtrHeader h{1,1,node,port,0,(uint32_t)body.size(),1,local};
        std::vector<uint8_t> packet(32+body.size());memcpy(packet.data(),&h,32);
        if(!body.empty())memcpy(packet.data()+32,body.data(),body.size());g.qrtr(packet.data(),packet.size());
    }
    void server(unsigned command=4,unsigned service=4097,unsigned instance=1,unsigned node=7,unsigned port=219) {
        QrtrHeader h{1,command,0,control_port,0,20,1,control_port};
        QrtrControl c{command,{service,instance,node,port}};uint8_t packet[52];
        memcpy(packet,&h,32);memcpy(packet+32,&c,20);g.qrtr(packet,sizeof(packet));
    }
    void feature(uint8_t first=0xf7,unsigned source=51) {
        feed({8,0,0,0,7,0,0,0,3,0,0,0,first,0xfe,3},0x4005,3,source);
    }
    void root() {
        const char name[]="modem/root_pd";std::vector<uint8_t> body(16+sizeof(name));
        uint32_t words[]={33,8+sizeof(name),1,0};memcpy(body.data(),words,16);memcpy(body.data()+16,name,sizeof(name));feed(body);
    }
    void registration(unsigned first=0x900,unsigned last=0x90f,unsigned command=0xff,unsigned source=51) {
        std::vector<uint8_t> body{1,0,0,0,20,0,0,0,1,0,0,0,(uint8_t)command,0,0x4d,0,
            1,0,0x34,0x12,(uint8_t)first,(uint8_t)(first>>8),(uint8_t)last,(uint8_t)(last>>8),0xef,0xbe,0xad,0xde};
        feed(body,0x4005,3,source);
    }
    void setup() { server();feature();root();registration(); }
    void cal() { g.wlfw.board_data=board;g.wlfw.board_bytes=sizeof(board);g.wlfw.step=7;g.wlfw_node=0;g.wlfw_port=35; }
    void ticks(unsigned n) { for(unsigned i=0;i<n;++i)g.tick_ulog(); }
    std::vector<Tx> flush() {
        reset_tx();g.tftp_flush();std::vector<Tx> result;
        for(unsigned at=0;at<g.word(4);) {
            GlinkMessage frame;memcpy(&frame,shared+g.tx.offset+at,8);assert(frame.command==9);
            uint32_t count;memcpy(&count,shared+g.tx.offset+at+8,4);assert(count>=32);
            Tx tx;memcpy(&tx.header,shared+g.tx.offset+at+16,32);assert(tx.header.size<=count-32);
            const uint8_t *p=shared+g.tx.offset+at+48;tx.payload.assign(p,p+tx.header.size);
            tx.wire.assign(p-32,p-32+count);result.push_back(tx);
            at+=(16+count+7)&~7u;
        }
        return result;
    }
    static unsigned commands(const std::vector<Tx> &tx) {
        unsigned n=0;for(const auto &p:tx)if(p.header.from_port==0x4007)++n;return n;
    }
    static void expect(const std::vector<Tx> &tx,const std::vector<uint8_t> &wire) {
        assert(commands(tx)==1);for(const auto &p:tx)if(p.header.from_port==0x4007){
            assert(p.header.type==1&&p.header.from_node==1&&p.header.to_node==7&&p.header.to_port==219);
            assert(p.payload==wire); // No framing/tag prefix and no registration port/data destination.
        }
    }
    static bool has_cal(const std::vector<Tx> &tx) {
        for(const auto &p:tx)if(p.header.from_port==0x4004){
            const std::vector<uint8_t> expected{0,1,0,0x26,0,8,0,1,1,0,0,0x11,1,0,0};
            assert(p.header.to_node==0&&p.header.to_port==35&&p.payload==expected);return true;
        }return false;
    }
    static std::vector<uint8_t> connect(unsigned index) {
        const char *name=index?"CCPM User DEBUG LOG":"CCPM User LOG";
        std::vector<uint8_t> wire(28);wire[0]=0x4b;wire[1]=0x4d;wire[2]=1;wire[3]=9;
        memcpy(wire.data()+4,name,strlen(name)+1);return wire;
    }
    static std::vector<uint8_t> payload(unsigned command,std::initializer_list<uint32_t> fields) {
        std::vector<uint8_t> p{0x4b,0x4d,(uint8_t)command,(uint8_t)(command>>8)};
        for(uint32_t value:fields)for(unsigned i=0;i<4;++i)p.push_back(value>>(8*i));return p;
    }
    void raw(const std::vector<uint8_t> &p,unsigned node=7,unsigned port=219,bool tail=true) {
        std::vector<uint8_t> frame{0x7e,1,(uint8_t)p.size(),(uint8_t)(p.size()>>8)};
        frame.insert(frame.end(),p.begin(),p.end());frame.push_back(tail?0x7e:0);feed(frame,0x4007,node,port);
    }
    void initial_queries() {
        expect(flush(),{0x4b,0x4d,0,9});raw(payload(0x900,{1,0}));
        assert(g.ulog_route_verified&&g.ulog_version_replies==1);
        expect(flush(),{0x4b,0x4d,4,9,0,0,0,0});
        auto names=payload(0x904,{0,2,0,2});const char list[]="CCPM User LOG\0CCPM User DEBUG LOG";
        names.insert(names.end(),list,list+sizeof(list));raw(names);
    }
    void connections(uint32_t first,uint32_t second) {
        expect(flush(),connect(0));raw(payload(0x901,{first,first?0u:13u}));
        expect(flush(),connect(1));raw(payload(0x901,{second,second?0u:13u}));
    }
};
static void check_ulog_commands() {
    {
        UlogPeer p;p.server(4,4097,0);assert(!p.g.diag_command_server);
        p.server();p.feature();p.registration(0x700,0x70f);p.root();
        auto sent=p.flush();assert(UlogPeer::commands(sent)==0&&!UlogPeer::has_cal(sent));
        p.registration(0x900,0x90f,0xff,52);assert(!p.g.diag_ulog_registered);
        p.registration();assert(p.g.diag_ulog_registered);UlogPeer::expect(p.flush(),{0x4b,0x4d,0,9});
    }
    {
        UlogPeer p;p.server();p.feature();p.registration(0x900,0x90f,0x4b);
        assert(UlogPeer::commands(p.flush())==0&&p.g.diag_feature_tx&&!p.g.diag_root_id_tx);
        p.root();p.reset_tx();p.g.send_ulog_command();assert(p.g.word(4)==0&&!p.g.ulog_waiting);
        UlogPeer::expect(p.flush(),{0x4b,0x4d,0,9});assert(p.g.diag_root_id_tx);
    }
    {
        UlogPeer p;p.server();p.feature(0xa7);p.root();p.registration();
        assert(UlogPeer::commands(p.flush())==0); // Peer lacks separate response/raw encoding bits.
    }
    {
        UlogPeer p;p.cal();p.setup();p.initial_queries();p.connections(0x11223344,0xa1b2c3d4);
        assert(p.g.ulog_handles[0]==0x11223344&&p.g.ulog_handles[1]==0xa1b2c3d4);
        assert(p.g.hold_cal_for_ulog()&&!p.g.wlfw.waiting);
        p.ticks(5);UlogPeer::expect(p.flush(),{0x4b,0x4d,5,9,0x44,0x33,0x22,0x11,1,0,0,0});
        captured_bulk_log.clear();auto first=UlogPeer::payload(0x905,{1,4});
        first.insert(first.end(),{0,0,0,0,0x99});p.raw(first);
        assert(p.g.ulog_first_reads==1&&p.g.ulog_saved_bytes==4&&p.g.ulog_empty==1);
        assert(captured_bulk_log.find("bytes=4 raw=00000000\n")!=std::string::npos);
        assert(p.g.hold_cal_for_ulog()&&!UlogPeer::has_cal(p.flush()));
        p.ticks(5);UlogPeer::expect(p.flush(),{0x4b,0x4d,5,9,0xd4,0xc3,0xb2,0xa1,1,0,0,0});
        auto second=UlogPeer::payload(0x905,{3,1024});
        for(unsigned i=0;i<1024;++i)second.push_back(i);second.push_back(0xee);
        captured_bulk_log.clear();p.raw(second);
        assert(p.g.ulog_first_reads==3&&p.g.ulog_saved_bytes==1028&&p.g.ulog_overruns==1&&!p.g.ulog_stopped);
        assert(captured_bulk_log.find("at=896 bytes=128 raw=")!=std::string::npos);
        assert(captured_bulk_log.find("at=1024")==std::string::npos);
        assert(!p.g.hold_cal_for_ulog()&&UlogPeer::has_cal(p.flush())&&p.g.wlfw.waiting);
        assert(p.g.wlfw.step==7&&!p.g.wlfw.fw_ready&&!p.g.wlfw.init_done);
    }
    {
        UlogPeer p;p.cal();p.setup();p.initial_queries();p.connections(0,0);
        assert(p.g.ulog_connect_attempted==3&&!p.g.ulog_handles[0]&&!p.g.ulog_handles[1]);
        assert(UlogPeer::has_cal(p.flush())&&!p.g.ulog_stopped);
        p.ticks(5);UlogPeer::expect(p.flush(),UlogPeer::connect(0));p.raw(UlogPeer::payload(0x901,{7,0}));
        p.ticks(5);UlogPeer::expect(p.flush(),UlogPeer::connect(1));p.raw(UlogPeer::payload(0x901,{0,13}));
        p.ticks(5);UlogPeer::expect(p.flush(),{0x4b,0x4d,5,9,7,0,0,0,1,0,0,0});
        assert(p.g.ulog_handles[0]==7&&!p.g.ulog_stopped); // A ring created after CAL remains discoverable.
    }
    {
        UlogPeer p;p.cal();p.setup();UlogPeer::expect(p.flush(),{0x4b,0x4d,0,9});
        p.ticks(999);assert(!p.g.ulog_stopped&&p.g.hold_cal_for_ulog());
        p.ticks(1);assert(p.g.ulog_stopped&&!p.g.ulog_waiting&&UlogPeer::has_cal(p.flush()));
    }
    {
        UlogPeer p;p.cal();assert(!UlogPeer::has_cal(p.flush()));p.ticks(1999);
        assert(!UlogPeer::has_cal(p.flush()));p.ticks(1);assert(UlogPeer::has_cal(p.flush()));
    }
    {
        UlogPeer p;p.cal();p.setup();p.flush();auto good=UlogPeer::payload(0x900,{1,0});
        p.raw(good,7,218);assert(p.g.ulog_waiting&&p.g.diag_command_packets==0); // Wrong peer ignored.
        p.raw(good,7,219,false);assert(p.g.diag_frame_errors==1&&p.g.ulog_stopped&&!p.g.ulog_waiting);
        assert(UlogPeer::has_cal(p.flush())&&p.g.ulog_stage==0);
    }
    {
        UlogPeer p;p.setup();p.initial_queries();p.connections(2,3);p.ticks(5);p.flush();
        p.raw(UlogPeer::payload(0x905,{1,1025}));assert(p.g.ulog_stopped&&p.g.ulog_saved_bytes==0);
    }
    {
        UlogPeer p;p.setup();p.initial_queries();p.connections(2,3);p.ticks(5);p.flush();
        p.g.ulog_saved_bytes=65532;auto page=UlogPeer::payload(0x905,{1,8});page.resize(20);
        captured_bulk_log.clear();p.raw(page);
        assert(p.g.ulog_stopped&&p.g.ulog_saved_bytes==65532&&p.g.ulog_omitted_bytes==8&&captured_bulk_log.empty());
    }
    {
        UlogPeer p;p.setup();p.initial_queries();p.connections(2,3);p.ticks(5);p.g.ulog_requests=1024;
        assert(UlogPeer::commands(p.flush())==0&&p.g.ulog_stopped);
    }
    {
        UlogPeer p;p.setup();p.initial_queries();p.connections(2,3);p.ticks(5);p.flush();assert(p.g.ulog_waiting);
        p.server(4,4097,1,7,220);
        assert(!p.g.ulog_waiting&&!p.g.ulog_handles[0]&&!p.g.ulog_handles[1]);
        assert(!p.g.ulog_route_verified&&p.g.ulog_version_replies==1);
        auto late=UlogPeer::payload(0x905,{1,4});late.resize(16);
        p.raw(late);p.raw(late,7,220);assert(p.g.ulog_reads==0&&p.g.ulog_saved_bytes==0);
        assert(p.g.ulog_stopped&&UlogPeer::commands(p.flush())==0); // Old handles never sent to new peer.
        p.server(5,4097,1,7,219);assert(p.g.diag_command_server); // Stale removal cannot remove new peer.
        p.server(5,4097,1,7,220);assert(!p.g.diag_command_server);
    }
    {
        UlogPeer p;p.setup();p.initial_queries();p.connections(2,3);p.ticks(5);p.flush();assert(p.g.ulog_waiting);
        p.feature(0xf7,52);assert(!p.g.ulog_waiting&&!p.g.ulog_handles[0]&&!p.g.ulog_handles[1]);
        assert(!p.g.ulog_route_verified&&p.g.ulog_version_replies==1);
        auto late=UlogPeer::payload(0x905,{1,4});late.resize(16);p.raw(late);
        assert(p.g.ulog_reads==0&&p.g.ulog_saved_bytes==0);
        assert(p.g.ulog_stopped&&!p.g.diag_ulog_registered&&UlogPeer::commands(p.flush())==0);
    }
    {
        UlogPeer p;p.setup();p.initial_queries();p.connections(2,3);p.ticks(5);p.flush();assert(p.g.ulog_waiting);
        // Original packed id27 has 10 fixed payload bytes and 4 per range, unlike id1.
        const std::vector<uint8_t> deregister{0x1b,0,0,0,0x0e,0,0,0,1,0,0,0,0xff,0,0x4d,0,1,0,0,9,0x0f,9};
        p.feed(deregister,0x4005,3,52);assert(p.g.diag_ulog_registered&&p.g.ulog_waiting);
        auto unrelated=deregister;unrelated[19]=unrelated[21]=7;p.feed(unrelated);
        assert(p.g.diag_ulog_registered&&p.g.ulog_waiting&&!p.g.ulog_stopped);
        auto malformed=deregister;malformed[16]=2;p.feed(malformed);
        assert(p.g.diag_control_invalid==1&&p.g.diag_ulog_registered&&p.g.ulog_waiting);
        p.feed(deregister);
        assert(!p.g.diag_ulog_registered&&p.g.ulog_stopped&&!p.g.ulog_waiting);
        assert(!p.g.ulog_handles[0]&&!p.g.ulog_handles[1]);
        auto late=UlogPeer::payload(0x905,{1,4});late.resize(16);p.raw(late);
        assert(p.g.ulog_reads==0&&p.g.ulog_saved_bytes==0&&UlogPeer::commands(p.flush())==0);
    }
    {
        UlogPeer p;p.setup();p.initial_queries();p.connections(2,3);p.ticks(5);p.flush();
        // Withdrawing the used READ command alone also invalidates this collection.
        p.feed({0x1b,0,0,0,0x0e,0,0,0,1,0,0,0,0x4b,0,0x4d,0,1,0,5,9,5,9});
        assert(p.g.ulog_stopped&&!p.g.diag_ulog_registered&&!p.g.ulog_waiting&&!p.g.ulog_handles[0]);
    }
    {
        UlogPeer p;p.setup();p.initial_queries();p.connections(2,3);captured_bulk_log.clear();
        auto empty=UlogPeer::payload(0x905,{1,4});empty.resize(16);
        for(unsigned i=0;i<12;++i){
            p.ticks(5);auto tx=p.flush();assert(UlogPeer::commands(tx)==1);p.raw(empty);
            if(i==1)captured_bulk_log.clear();
        }
        assert(p.g.ulog_empty==12&&p.g.ulog_saved_bytes==8&&captured_bulk_log.empty());
        // A changed status and overrun remain observable even without a record body.
        p.ticks(5);p.flush();auto changed=empty;changed[12]=1;p.raw(changed);
        assert(p.g.ulog_saved_bytes==12&&!captured_bulk_log.empty());captured_bulk_log.clear();
        p.ticks(5);p.flush();auto overrun=empty;overrun[4]=3;p.raw(overrun);
        assert(p.g.ulog_saved_bytes==16&&p.g.ulog_overruns==1&&!captured_bulk_log.empty());
    }
    {
        UlogPeer p;p.setup();p.initial_queries();p.connections(2,3);p.ticks(5);p.flush();
        assert(p.g.ulog_waiting);p.g.registry.records=p.board;
        std::vector<uint8_t> failure{0,9,0,0x24,0,20,0,1,12,0,
            'w','l','a','n','_','p','r','o','c','e','s','s',2,2,0,'E','X'};
        p.feed(failure,0x4002,0,9);
        assert(p.g.wlan_crash_captured&&p.g.ulog_stopped&&!p.g.ulog_waiting);
        assert(!p.g.ulog_handles[0]&&!p.g.ulog_handles[1]);
        assert(!p.g.ulog_route_verified&&p.g.ulog_version_replies==1);
        unsigned before=p.g.ulog_reads;auto late=UlogPeer::payload(0x905,{1,4});late.resize(16);p.raw(late);
        assert(p.g.ulog_reads==before&&p.g.ulog_saved_bytes==0&&UlogPeer::commands(p.flush())==0);
    }
    {
        UlogPeer p;p.cal();assert(p.g.hold_cal_for_ulog());
        p.feed({4,0,0,0x39,0,0,0},0x4003,0,35);
        assert(p.g.wlfw.rejuvenate_count==1&&!p.g.hold_cal_for_ulog());
        auto tx=p.flush();assert(tx.size()==1&&tx[0].header.from_port==0x4003);
        assert((tx[0].payload==std::vector<uint8_t>{0,1,0,0x3a,0,0,0}));
        assert(p.g.wlfw.waiting&&p.g.wlfw.message==0x3a); // Recovery ACK is never held by the CAL gate.
    }
}
static void check_ulog_version_without_registration() {
    // The original MPSS internal dispatcher accepts WLAN's fixed read-only 0900
    // handler without waiting for APPS REG advertisement. It does not authorize
    // advancing on a local TX, bad-command response or mismatched version.
    // Evidence: wireless-v111/diag-registration-followup/findings.md.
    {
        UlogPeer p;p.server();p.feature();p.root();
        auto tx=p.flush();assert(UlogPeer::commands(tx)==0&&p.g.wlfw_port==0);
        assert(p.g.diag_feature_tx&&p.g.diag_root_id_tx&&!p.g.diag_ulog_registered);
        p.server(4,0x45,1,0,35);p.g.wlfw.waiting=true;
        UlogPeer::expect(p.flush(),{0x4b,0x4d,0,9});
        assert(p.g.ulog_requests==1&&p.g.ulog_waiting&&!p.g.ulog_route_verified);
        p.ticks(200);assert(UlogPeer::commands(p.flush())==0&&p.g.ulog_stage==0&&p.g.ulog_requests==1);
        // A packet from another endpoint is not version evidence.
        p.raw(UlogPeer::payload(0x900,{1,0}),7,218);
        assert(p.g.ulog_waiting&&!p.g.ulog_route_verified&&p.g.ulog_version_replies==0);
        p.raw(UlogPeer::payload(0x900,{1,0}));
        assert(p.g.ulog_route_verified&&p.g.ulog_version_replies==1&&!p.g.diag_ulog_registered);
        UlogPeer::expect(p.flush(),{0x4b,0x4d,4,9,0,0,0,0});
        p.raw(UlogPeer::payload(0x904,{0,0,0,0}));
        UlogPeer::expect(p.flush(),UlogPeer::connect(0));
        assert(p.g.ulog_command==0x901&&!p.g.diag_ulog_registered);
    }
    {
        UlogPeer p;p.server();p.feature();p.root();p.server(4,0x45,1,0,35);p.g.wlfw.waiting=true;
        // The new route does not bypass actual FEATURE/root-ID response transmission.
        p.reset_tx();p.g.send_ulog_command();assert(p.g.word(4)==0&&!p.g.diag_feature_tx&&!p.g.diag_root_id_tx);
        UlogPeer::expect(p.flush(),{0x4b,0x4d,0,9});
        p.ticks(1000);assert(p.g.ulog_stopped&&!p.g.ulog_waiting);
        assert(UlogPeer::commands(p.flush())==0&&!p.g.ulog_route_verified&&p.g.ulog_version_replies==0);
    }
    {
        UlogPeer p;p.server();p.feature();p.root();p.server(4,0x45,1,0,35);p.g.wlfw.waiting=true;
        p.flush();captured_bulk_log.clear();
        p.raw({0x13,0x4b,0x4d,0,9}); // Original unregistered-handler BAD_CMD with request prefix.
        assert(p.g.ulog_stopped&&!p.g.ulog_waiting&&!p.g.ulog_route_verified&&p.g.ulog_stage==0);
        assert(p.g.ulog_version_replies==0&&UlogPeer::commands(p.flush())==0);
        assert(captured_bulk_log.find("kind=unexpected sequence=1 at=0 bytes=5 raw=134b4d0009\n")!=std::string::npos);
    }
    for(unsigned failure=0;failure<4;++failure) {
        UlogPeer p;p.server();p.feature();p.root();p.server(4,0x45,1,0,35);p.g.wlfw.waiting=true;p.flush();
        auto reply=UlogPeer::payload(0x900,{1,0});
        if(failure==0)reply[4]=2; // Unsupported version, correct command echo.
        if(failure==1)reply[8]=1; // Nonzero version-query status.
        if(failure==2)reply[3]=8; // Another PD's 0800 echo cannot establish the WLAN route.
        if(failure==3)reply.resize(11); // A short apparent success cannot establish it either.
        p.raw(reply);assert(p.g.ulog_stopped&&!p.g.ulog_waiting&&p.g.ulog_stage==0);
        assert(!p.g.ulog_route_verified&&p.g.ulog_version_replies==0&&UlogPeer::commands(p.flush())==0);
    }
    {
        UlogPeer p;p.server();p.feature();p.root();p.flush();
        p.server(4,0x45,1,0,35);p.g.wlfw.waiting=true;
        // An unverified nonzero stage cannot issue LIST/CONNECT/READ without REG.
        for(unsigned stage=1;stage<5;++stage){
            p.g.ulog_stage=stage;p.ticks(5);
            assert(UlogPeer::commands(p.flush())==0&&p.g.ulog_requests==0&&!p.g.ulog_waiting);
        }
    }
    {
        UlogPeer p;p.server();p.feature();p.root();p.server(4,0x45,1,0,35);p.g.wlfw.waiting=true;p.flush();
        std::vector<uint8_t> bad(90,0xaa);bad[0]=0x13;captured_bulk_log.clear();p.raw(bad);
        assert(p.g.ulog_stopped&&captured_bulk_log.find("bytes=64 raw=13")!=std::string::npos);
        assert(captured_bulk_log.find("at=64")==std::string::npos&&captured_bulk_log.size()<240);
    }
    {
        UlogPeer p;p.feature();for(unsigned i=0;i<4;++i)p.root();captured_bulk_log.clear();
        p.flush();assert(p.g.diag_replies_tx==5);
        assert(captured_bulk_log.find("kind=control-tx sequence=1 at=0 bytes=16 raw=08000000080000000400000051a00000\n")!=std::string::npos);
        assert(captured_bulk_log.find("raw=210000001600000001000000020000006d6f64656d2f726f6f745f706400\n")!=std::string::npos);
        assert(captured_bulk_log.find("kind=control-tx sequence=4")!=std::string::npos);
        assert(captured_bulk_log.find("kind=control-tx sequence=5")==std::string::npos);
    }
}
static std::vector<uint8_t> wire_hex(const char *hex) {
    std::vector<uint8_t> result;
    auto digit=[](char c)->unsigned {assert((c>='0'&&c<='9')||(c>='a'&&c<='f'));return c<='9'?c-'0':c-'a'+10;};
    for(unsigned i=0;hex[i];i+=2){assert(hex[i+1]);result.push_back((digit(hex[i])<<4)|digit(hex[i+1]));}return result;
}
struct ConfirmPeer:UlogPeer {
    void feature() {feed({8,0,0,0,7,0,0,0,3,0,0,0,0xf7,0xfe,3},0x4005,0,26);}
    void root_id() {
        // Recorded MPSS root name and opaque request ID; the response assigns ID2.
        feed(wire_hex("210000001a00000001000000504366c26d736d2f6d6f64656d2f726f6f745f706400"),0x4005,0,26);
    }
    void setup() {feature();root_id();server(4,4097,1,0,27);cal();}
    void incoming(const std::vector<uint8_t> &wire) {g.qrtr(wire.data(),wire.size());}
    void reply(const std::vector<uint8_t> &payload) {raw(payload,0,27);}
    static unsigned confirms(const std::vector<Tx> &packets) {
        unsigned n=0;for(const auto &p:packets){assert(p.header.confirm<=1);n+=p.header.confirm;}return n;
    }
    static void command(const std::vector<Tx> &packets,const std::vector<uint8_t> &payload) {
        assert(commands(packets)==1);for(const auto &p:packets)if(p.header.from_port==0x4007)
            assert(p.header.to_node==0&&p.header.to_port==27&&p.payload==payload&&p.header.confirm==0);
    }
};
static void check_diag_socket_receipts() {
    // Full independent golden vectors from original MPSS receive/dequeue evidence:
    // wireless-v112/diag-rx-followup/confirm-probe-spec.json. Includes QRTR padding.
    const auto root_tx=wire_hex("010000000100000001000000054000000100000022000000000000001a000000210000001a00000001000000020000006d736d2f6d6f64656d2f726f6f745f7064000000");
    auto first_root_tx=root_tx;first_root_tx[16]=0;
    const auto version_tx=wire_hex("010000000100000001000000074000000100000004000000000000001b0000004b4d0009");
    const auto root_v1=wire_hex("010000000700000000000000feffffff000000001400000001000000feffffff07000000000000001a0000000000000000000000");
    const auto root_v3=wire_hex("03070000140000000000feff0100feff07000000000000001a0000000000000000000000");
    const auto version_v1=wire_hex("010000000700000000000000feffffff000000001400000001000000feffffff07000000000000001b0000000000000000000000");
    const auto version_v3=wire_hex("03070000140000000000feff0100feff07000000000000001b0000000000000000000000");
    {
        ConfirmPeer p;p.ticks(10);p.feature();p.root_id();p.server(4,4097,1,0,27);
        auto tx=p.flush();assert(tx.size()==2);
        assert(tx[0].header.confirm==0&&tx[1].wire==first_root_tx);
        assert(p.g.diag_root_reply_bytes==34&&p.g.diag_root_replies_tx==1);
        assert(!memcmp(p.g.diag_root_reply,first_root_tx.data()+32,34));
        assert(!p.g.diag_receipts[0].sent&&!p.g.diag_receipts[1].sent&&p.g.ulog_requests==0);
        unsigned confirmed=ConfirmPeer::confirms(tx);assert(confirmed==0);
        p.ticks(20);tx=p.flush();assert(tx.empty()&&!p.g.diag_receipts[0].sent); // No WLFW, no repeat.
        p.cal();tx=p.flush();assert(tx.size()==2&&tx[0].wire==root_tx&&tx[1].wire==version_tx);
        confirmed+=ConfirmPeer::confirms(tx);assert(confirmed==2&&p.g.diag_root_replies_tx==2);
        for(unsigned i=0;i<2;++i){const auto &r=p.g.diag_receipts[i];
            assert(r.sent&&r.active&&r.node==0&&r.port==26+i&&r.sent_tick==30&&r.packets==0);}
        p.root_id();tx=p.flush();assert(tx.size()==1&&tx[0].header.confirm==0);confirmed+=ConfirmPeer::confirms(tx);
        assert(tx[0].wire==first_root_tx&&p.g.diag_root_replies_tx==3);
        p.feed(wire_hex("210000001a00000001000000000000006d736d2f6d6f64656d2f776c616e5f706400"),0x4005,0,26);
        tx=p.flush();assert(tx.size()==1&&tx[0].header.confirm==0);confirmed+=ConfirmPeer::confirms(tx);
        assert(!p.g.ulog_route_verified&&p.g.ulog_requests==1&&p.g.ulog_waiting);
        p.reply(UlogPeer::payload(0x900,{1,0}));assert(p.g.ulog_route_verified&&p.g.ulog_version_replies==1);
        tx=p.flush();ConfirmPeer::command(tx,{0x4b,0x4d,4,9,0,0,0,0});confirmed+=ConfirmPeer::confirms(tx);
        p.reply(UlogPeer::payload(0x904,{0,0,0,0}));
        tx=p.flush();ConfirmPeer::command(tx,UlogPeer::connect(0));confirmed+=ConfirmPeer::confirms(tx);
        p.reply(UlogPeer::payload(0x901,{0,13}));
        tx=p.flush();ConfirmPeer::command(tx,UlogPeer::connect(1));confirmed+=ConfirmPeer::confirms(tx);
        p.reply(UlogPeer::payload(0x901,{0,13}));tx=p.flush();assert(UlogPeer::has_cal(tx));
        confirmed+=ConfirmPeer::confirms(tx);assert(confirmed==2&&p.g.ulog_requests==4);
    }
    {
        ConfirmPeer p;p.ticks(10);p.setup();auto sent=p.flush();
        assert(sent.size()==4&&sent[1].wire==first_root_tx&&sent[2].wire==root_tx&&sent[3].wire==version_tx);
        assert(ConfirmPeer::confirms(sent)==2); // First root reply is never confirmed, even with WLFW ready.
        std::vector<std::vector<uint8_t>> wrong;
        auto packet=version_v1;packet[40]=7;packet[41]=0x40;wrong.push_back(packet); // Local 0x4007 is not DSP27.
        packet=version_v1;packet[8]=packet[36]=2;wrong.push_back(packet); // Valid envelope, wrong target node.
        packet=version_v1;packet[8]=2;wrong.push_back(packet); // Envelope source disagrees with payload node.
        packet=version_v1;packet[12]=27;packet[13]=packet[14]=packet[15]=0;wrong.push_back(packet);
        packet=version_v1;packet[24]=0;wrong.push_back(packet); // Not addressed to APPS node1.
        packet=version_v1;packet[28]=7;packet[29]=0x40;packet[30]=packet[31]=0;wrong.push_back(packet);
        packet=version_v1;packet[32]=8;wrong.push_back(packet); // Wrong payload control command.
        packet=version_v1;packet[44]=1;wrong.push_back(packet); // Original five-word ack has zero tail words.
        packet=version_v1;packet[20]=19;packet.pop_back();wrong.push_back(packet);
        packet=version_v1;packet[4]=1;wrong.push_back(packet); // DATA carrying 7 is not a type7 receipt.
        for(const auto &bad:wrong)p.incoming(bad);
        assert(!p.g.diag_receipts[0].packets&&!p.g.diag_receipts[1].packets);
        assert(p.g.diag_resume_invalid&&p.g.diag_resume_unmatched&&!p.g.ulog_route_verified);
        p.ticks(3);p.incoming(root_v1);assert(p.g.diag_receipts[0].packets==1&&p.g.diag_receipts[0].first_tick==13);
        assert(p.g.diag_receipts[1].packets==0);
        p.ticks(7);p.incoming(version_v3);assert(p.g.diag_receipts[1].packets==1&&p.g.diag_receipts[1].first_tick==20);
        p.incoming(root_v3);p.incoming(version_v1);
        assert(p.g.diag_receipts[0].packets==2&&p.g.diag_receipts[0].first_tick==13);
        assert(p.g.diag_receipts[1].packets==2&&p.g.diag_receipts[1].first_tick==20);
        assert(!p.g.ulog_route_verified&&p.g.ulog_version_replies==0&&!p.g.diag_ulog_registered);
        assert(p.g.ulog_waiting&&p.g.ulog_stage==0&&p.g.hold_cal_for_ulog()&&p.g.diag_command_packets==0);
        assert(UlogPeer::commands(p.flush())==0&&p.g.ulog_requests==1); // No receipt-driven retry.
        p.ticks(990);assert(p.g.ulog_stopped&&!p.g.ulog_waiting&&!p.g.ulog_route_verified);
        assert(UlogPeer::has_cal(p.flush())&&p.g.ulog_version_replies==0);
    }
    {
        ConfirmPeer p;p.incoming(root_v1);p.incoming(version_v3);
        assert(p.g.diag_resume_unmatched==2&&!p.g.diag_receipts[0].sent&&!p.g.diag_receipts[1].sent);
        p.feature();p.flush();p.root_id();p.reset_tx();
        // Ring pressure makes datagram() return false even with a remote intent.
        put32(4,16368);p.g.tftp_flush();
        assert(!p.g.diag_receipts[0].sent&&!p.g.diag_root_id_tx&&p.g.response_count==1);
        assert(p.g.diag_root_reply_bytes==0&&p.g.diag_root_replies_tx==0);
        p.incoming(root_v1);assert(!p.g.diag_receipts[0].packets&&p.g.diag_resume_unmatched==3);
        auto tx=p.flush();assert(tx.size()==1&&tx[0].wire==first_root_tx&&!p.g.diag_receipts[0].sent);
        assert(p.g.diag_root_reply_bytes==34&&p.g.diag_root_replies_tx==1);
        p.server(4,4097,1,0,27);p.cal();p.reset_tx();
        for(auto &intent:p.g.remote)intent.present=false;p.g.intent_requested=true;
        p.g.send_ulog_command();assert(!p.g.diag_receipts[0].sent&&!p.g.diag_receipts[1].sent);
        assert(!p.g.ulog_waiting&&p.g.ulog_requests==0&&p.g.word(4)==0&&p.g.diag_root_replies_tx==1);
        p.incoming(root_v1);p.incoming(version_v1);
        assert(!p.g.diag_receipts[0].packets&&!p.g.diag_receipts[1].packets&&p.g.diag_resume_unmatched==5);
        tx=p.flush();assert(tx.size()==2&&tx[0].wire==root_tx&&tx[1].wire==version_tx);
        assert(p.g.diag_receipts[0].sent&&p.g.diag_receipts[1].sent&&p.g.ulog_requests==1&&p.g.diag_root_replies_tx==2);
    }
    {
        ConfirmPeer p;p.feature();p.root_id();p.server(4,4097,1,0,27);p.flush();p.cal();p.reset_tx();
        for(unsigned i=1;i<16;++i)p.g.remote[i].present=false;
        p.g.intent_requested=true; // One intent allows the repeat but forces 0900 to wait.
        p.g.send_ulog_command();assert(p.g.diag_receipts[0].sent&&!p.g.diag_receipts[1].sent);
        assert(p.g.diag_root_replies_tx==2&&!p.g.ulog_waiting&&p.g.ulog_requests==0);
        assert(p.g.word(4)==88&&!memcmp(shared+p.g.tx.offset+16,root_tx.data(),root_tx.size()));
        p.incoming(root_v1);assert(p.g.diag_receipts[0].packets==1&&!p.g.ulog_route_verified);
        auto tx=p.flush();assert(tx.size()==1&&tx[0].wire==version_tx);
        assert(p.g.diag_root_replies_tx==2&&p.g.diag_receipts[1].sent&&p.g.ulog_requests==1);
        assert(p.flush().empty()); // Successful repeat is not retransmitted while 0900 waits.
    }
    for(unsigned retirement=0;retirement<4;++retirement) {
        ConfirmPeer p;p.feature();p.root_id();p.server(4,4097,1,0,27);auto first=p.flush();
        assert(first.size()==2&&first[1].wire==first_root_tx&&p.g.diag_root_reply_bytes==34);
        if(retirement==0) {
            p.feed({8,0,0,0,7,0,0,0,3,0,0,0,0xf7,0xfe,3},0x4005,0,30);
            assert(p.g.diag_root_reply_bytes==0&&!p.g.diag_root_id_tx);
        } else if(retirement==1)p.server(4,4097,1,0,28);
        else if(retirement==2)p.server(5,4097,1,0,27);
        else {
            p.g.registry.records=p.board;
            p.feed({0,9,0,0x24,0,20,0,1,12,0,'w','l','a','n','_','p','r','o','c','e','s','s',2,2,0,'E','X'},0x4002,0,9);
            assert(p.g.wlan_crash_captured);
        }
        assert(p.g.ulog_stopped);p.cal();auto tx=p.flush();
        assert(ConfirmPeer::confirms(tx)==0&&UlogPeer::commands(tx)==0);
        assert(!p.g.diag_receipts[0].sent&&!p.g.diag_receipts[1].sent&&p.g.diag_root_replies_tx==1);
        p.incoming(root_v1);assert(p.g.diag_resume_unmatched==1&&!p.g.diag_receipts[0].packets);
    }
    {
        ConfirmPeer p;p.setup();p.flush();p.server(4,4097,1,0,28);
        assert(p.g.diag_receipts[1].sent&&!p.g.diag_receipts[1].active);
        p.incoming(version_v1);assert(!p.g.diag_receipts[1].packets&&p.g.diag_resume_unmatched==1);
        p.incoming(root_v3);assert(p.g.diag_receipts[0].packets==1); // Control endpoint is still the same socket.
        p.feed({8,0,0,0,7,0,0,0,3,0,0,0,0xf7,0xfe,3},0x4005,0,30);
        assert(!p.g.diag_receipts[0].active&&!p.g.diag_receipts[1].active);
        p.incoming(root_v1);assert(p.g.diag_receipts[0].packets==1&&p.g.diag_resume_unmatched==2);
        assert(!p.g.ulog_route_verified&&p.g.ulog_version_replies==0);
    }
}
int main() {
    smem_va=(uintptr_t)shared;
    put32(0xf000,0x434f5424);put32(0xf004,1);put32(0xf008,1);
    put32(0xf020,0x1000);put32(0xf024,0xc000);put32(0xf02c,1u<<16);put32(0xf030,32);
    put32(0x1000,0x54525024);put32(0x1008,0xc000);put32(0x100c,32);put32(0x1010,0xc000);
    NabuSmem smem{shared,sizeof(shared)};uint32_t smp,desc,fifo,existing;NabuSmemItem found;
    assert(allocate_item(smem,428,340,&smp)&&allocate_item(smem,478,32,&desc)&&allocate_item(smem,479,16384,&fifo));
    assert(smem.find(428,&found)&&found.offset==smp&&found.size==340);
    assert(smem.find(479,&found)&&found.offset==fifo&&found.size==16384);
    unsigned end=smem.u32(0x100c);assert(allocate_item(smem,479,16384,&existing)&&existing==fifo&&smem.u32(0x100c)==end);
    assert(!allocate_item(smem,479,8192,&existing)&&smem.u32(0x100c)==end&&hardware_lock==0);
    NabuGlink snapshot{};snapshot.memory=smem;
    std::vector<uint8_t> unchanged(shared,shared+sizeof(shared));
    captured_log.clear();snapshot.capture_minidump_prefixes("test-absent");
    assert(captured_log.find("item=602 phase=test-absent present=0 offset=0 directory-bytes=0 captured-prefix-bytes=0 prefix-limit=64")!=std::string::npos);
    assert(captured_log.find("item=618 phase=test-absent present=0 offset=0 directory-bytes=0 captured-prefix-bytes=0 prefix-limit=32")!=std::string::npos);
    assert(!memcmp(shared,unchanged.data(),sizeof(shared)));
    // Fixtures contain non-dereferenceable pointer bytes. Capture is prefix-only and read-only.
    uint32_t md602,md618;assert(allocate_item(smem,602,304,&md602)&&allocate_item(smem,618,96,&md618));
    for(unsigned i=0;i<304;++i)shared[md602+i]=i<64?i:0xee;
    for(unsigned i=0;i<96;++i)shared[md618+i]=i<32?0xff:0xee;
    put32(md602+0x20,0x454e424c);
    unchanged.assign(shared,shared+sizeof(shared));captured_log.clear();snapshot.capture_minidump_prefixes("test-prefix");
    assert(captured_log.find("directory-bytes=304 captured-prefix-bytes=64 prefix-limit=64")!=std::string::npos);
    assert(captured_log.find("directory-bytes=96 captured-prefix-bytes=32 prefix-limit=32")!=std::string::npos);
    assert(captured_log.find("item=602 phase=test-prefix prefix+0x20=4c 42 4e 45 24 25 26 27")!=std::string::npos);
    assert(captured_log.find("item=618 phase=test-prefix prefix+0x10=ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff ff")!=std::string::npos);
    assert(captured_log.find("prefix+0x40=")==std::string::npos&&captured_log.find("ee ee")==std::string::npos);
    assert(!memcmp(shared,unchanged.data(),sizeof(shared)));
    // A directory entry shorter than the desired prefix reports and reads only its actual bytes.
    put32(md618-12,8);put32(md618-8,0);put32(0x100c,md618-0x1000+8);
    unchanged.assign(shared,shared+sizeof(shared));captured_log.clear();snapshot.capture_minidump_prefixes("test-short");
    assert(captured_log.find("directory-bytes=8 captured-prefix-bytes=8 prefix-limit=32")!=std::string::npos);
    assert(captured_log.find("item=618 phase=test-short prefix+0x10=")==std::string::npos);
    assert(!memcmp(shared,unchanged.data(),sizeof(shared)));
    captured_log.clear();snapshot.capture_minidump_edge("test-no-edge");
    assert(captured_log.find("edge=1:7 toc-valid=1 present=0; metadata only")!=std::string::npos);
    // This metadata names unmapped memory; a payload/header dereference would fail.
    put32(0xf008,2);put32(0xf050,0xfffff000);put32(0xf054,0x40000000);put32(0xf05c,(1u<<16)|7);
    unchanged.assign(shared,shared+sizeof(shared));captured_log.clear();snapshot.capture_minidump_edge("test-modem-tz");
    assert(captured_log.find("edge=1:7 toc-valid=1 present=1 entry=1 offset=0xfffff000 size=0x40000000; metadata only")!=std::string::npos);
    assert(!memcmp(shared,unchanged.data(),sizeof(shared)));
    put32(0xf05c,(7u<<16)|1);captured_log.clear();snapshot.capture_minidump_edge("test-reversed-edge");
    assert(captured_log.find("edge=1:7 toc-valid=1 present=1 entry=1")!=std::string::npos);
    // APPS/TZ is a different edge and must not be mistaken for MODEM/TZ.
    put32(0xf05c,7u<<16);captured_log.clear();snapshot.capture_minidump_edge("test-apps-tz");
    assert(captured_log.find("edge=1:7 toc-valid=1 present=0; metadata only")!=std::string::npos);
    put32(0xf008,85);captured_log.clear();snapshot.capture_minidump_edge("test-invalid-toc");
    assert(captured_log.find("edge=1:7 toc-valid=0; metadata only")!=std::string::npos);
    memset(shared,0,sizeof(shared));
    NabuGlink g{};g.memory={shared,sizeof(shared)};g.doorbell=&doorbell;
    g.descriptor={0,32};g.tx={0x4000,16384};g.rx={0x8000,16384};
    // The initial header and payload cross the FIFO boundary.
    put32(8,16380);put32(12,16380);
    receive(g,0,1,1);receive(g,1,1,1);g.pump();assert(g.agreed&&g.requested);
    receive(g,2,9,(4u<<16)|7,"IPCRTR",7);receive(g,4,1,0);g.pump();
    assert(g.opened&&g.remote_channel==9&&g.local_count==4&&!g.broken);
    uint32_t intents[]={1024,91,1024,92,1024,93,1024,94};
    receive(g,5,9,4,intents,sizeof(intents));g.pump();assert(g.pending_count==0);
    QrtrHeader h{1,2,3,control_port,0,20,1,control_port};QrtrControl c{2,{0,0,0,0}};
    std::vector<uint8_t> packet(52);memcpy(packet.data(),&h,32);memcpy(packet.data()+32,&c,20);
    data(g,packet,52);assert(g.peer==3&&g.hello_replied&&!g.broken);
    // v2 control header, confirmed and split over two GLINK fragments.
    packet.assign(36,0);packet[0]=3;packet[1]=4;packet[2]=1;packet[4]=20;
    packet[8]=3;packet[10]=0xfe;packet[11]=0xff;packet[12]=1;packet[14]=0xfe;packet[15]=0xff;
    c={4,{0x45,1,3,17}};memcpy(packet.data()+16,&c,20);
    data(g,packet,19);assert(g.servers==1&&g.wlfw_node==3&&g.wlfw_port==17&&g.local[0].fill==0);
    assert(count_command(g,14)==2&&count_command(g,9)==3&&!g.broken);
    receive(g,14,9,91);g.pump();assert(g.remote[0].present&&!g.remote[0].used);
    g.closing=true;receive(g,11,1,0);receive(g,3,9,0);g.pump();assert(g.close_ack&&!g.opened&&!g.broken);
    // Truncated transport data remains unread until its payload is available.
    unsigned before=g.word(8);uint32_t fragment[]={12,0};receive(g,9,9,1,fragment,8);g.pump();assert(g.word(8)==before);
    // A full TX queue rejects a write without changing its producer index.
    put32(4,0);put32(0,16);GlinkMessage m{13,0,0};assert(!g.send(&m,8)&&g.word(4)==0);
    // A full 6144-byte board segment traverses QRTR and wraps the TX FIFO intact.
    put32(4,15000);put32(0,15000);
    for(auto &r:g.remote)r.present=false;
    g.remote[0]={101,8192,true,false};
    std::vector<uint8_t> board(26328);for(unsigned i=0;i<board.size();++i)board[i]=i%251;
    NabuWlfw w{};w.board_data=board.data();w.board_bytes=board.size();w.step=6;w.prepare();
    assert(g.datagram(1,w.local_port(),0,35,w.request,w.bytes)&&g.remote[0].used);
    unsigned total=(32+w.bytes+3)&~3u,frame=(16+total+7)&~7u;
    std::vector<uint8_t> wire(frame);for(unsigned i=0;i<frame;++i)wire[i]=shared[g.tx.offset+(15000+i)%g.tx.size];
    GlinkMessage gh;memcpy(&gh,wire.data(),8);assert(gh.command==9&&gh.value==101);
    assert(NabuRmtfs::u32(wire.data()+8)==total&&NabuRmtfs::u32(wire.data()+12)==0);
    QrtrHeader qh;memcpy(&qh,wire.data()+16,32);assert(qh.size==w.bytes&&qh.from_port==0x4004&&qh.to_node==0&&qh.to_port==35);
    assert(!memcmp(wire.data()+48,w.request,w.bytes)&&g.word(4)==(15000+frame)%g.tx.size);
    g.qmi_enabled=true;g.wlfw_node=0;g.wlfw_port=35;g.wlfw=NabuWlfw{};
    g.wlfw.board_data=board.data();g.wlfw.board_bytes=board.size();g.wlfw.step=5;g.wlfw.dynamic_feature_complete=true;g.wlfw.prepare();g.wlfw.sent();
    uint8_t reg_response[]={2,1,0,0x20,0,7,0,2,4,0,0,0,0,0};
    QrtrHeader reply{1,1,0,35,0,sizeof(reg_response),1,0x4004};
    packet.resize(32+sizeof(reg_response));memcpy(packet.data(),&reply,32);memcpy(packet.data()+32,reg_response,sizeof(reg_response));
    g.qrtr(packet.data(),packet.size());assert(g.wlfw.step==6&&!g.wlfw.waiting);
    uint8_t ready[]={4,0,0,0x21,0,0,0};reply.size=sizeof(ready);reply.to_port=0x4003;
    packet.resize(32+sizeof(ready));memcpy(packet.data(),&reply,32);memcpy(packet.data()+32,ready,sizeof(ready));
    g.qrtr(packet.data(),packet.size());assert(g.wlfw.fw_ready&&g.wlfw.step==6);
    g.wlfw.prepare();g.wlfw.sent();
    const uint8_t pins[]={4,0,0,0x2c,0,14,0,0x10,4,0,0,0,0,0,0x12,4,0,0x78,0x56,0x34,0x12};
    reply.size=sizeof(pins);packet.resize(32+sizeof(pins));
    memcpy(packet.data(),&reply,32);memcpy(packet.data()+32,pins,sizeof(pins));
    g.qrtr(packet.data(),packet.size());
    assert(g.wlfw.pin_result_count==1&&g.wlfw.pin_result_step==6&&g.wlfw.waiting&&g.wlfw.message==0x25);
    assert(g.wlfw.pin_result_valid[0]&&g.wlfw.pin_result[0]==0&&!g.wlfw.pin_result_valid[1]);
    assert(g.wlfw.pin_result_valid[2]&&g.wlfw.pin_result[2]==0x12345678&&!g.wlfw.init_done);
    // Send through the production queue to verify KNEL/DMON routing and recovery stop.
    g.opened=true;g.closing=false;g.broken=false;
    auto reset_tx=[&](){put32(0,0);put32(4,0);g.remote[0]={101,8192,true,false};};
    auto feed_qmi=[&](const uint8_t *body,unsigned bytes,uint32_t node=0,uint32_t port=35){
        QrtrHeader incoming{1,1,node,port,0,bytes,1,0x4003};
        packet.resize(32+bytes);memcpy(packet.data(),&incoming,32);memcpy(packet.data()+32,body,bytes);
        g.qrtr(packet.data(),packet.size());
    };
    auto server=[&](unsigned command,unsigned node,unsigned port){
        QrtrHeader incoming{1,command,0,control_port,0,20,1,control_port};
        QrtrControl control{command,{wlfw_service,1,node,port}};
        packet.resize(52);memcpy(packet.data(),&incoming,32);memcpy(packet.data()+32,&control,20);
        g.qrtr(packet.data(),packet.size());
    };
    auto transmitted=[&](){QrtrHeader result;memcpy(&result,shared+g.tx.offset+16,32);return result;};
    g.wlfw=NabuWlfw{};g.wlfw.board_data=board.data();g.wlfw.board_bytes=board.size();g.wlfw.step=5;
    reset_tx();g.tftp_flush();qh=transmitted();
    assert(g.wlfw.waiting&&g.wlfw.message==0x3b&&g.wlfw.step==5);
    assert(qh.from_port==0x4003&&qh.to_node==0&&qh.to_port==35&&qh.size==18);
    const uint8_t feature_request[]={0,1,0,0x3b,0,11,0,0x10,8,0,1,0,0,0,0,0,0,0};
    assert(!memcmp(shared+g.tx.offset+48,feature_request,sizeof(feature_request)));
    uint8_t feature_response[]={2,1,0,0x3b,0,7,0,2,4,0,0,0,0,0};
    feed_qmi(feature_response,sizeof(feature_response));
    assert(g.wlfw.dynamic_feature_complete&&!g.wlfw.waiting&&g.wlfw.step==5);
    reset_tx();g.tftp_flush();qh=transmitted();
    assert(g.wlfw.waiting&&g.wlfw.message==0x20&&qh.from_port==0x4004&&qh.to_port==35);
    g.wlfw=NabuWlfw{};g.wlfw.activate=true;g.wlfw.step=3;
    const uint8_t rejuvenate[]={4,0,0,0x39,0,0,0};
    feed_qmi(rejuvenate,sizeof(rejuvenate));
    reset_tx();g.tftp_flush();qh=transmitted();
    assert(msa_prepare_calls==0&&g.wlfw.waiting&&g.wlfw.message==0x3a&&g.wlfw.step==3);
    assert(qh.from_port==0x4003&&qh.to_node==0&&qh.to_port==35&&qh.size==7);
    const uint8_t ack_request[]={0,1,0,0x3a,0,0,0};
    assert(!memcmp(shared+g.tx.offset+48,ack_request,sizeof(ack_request)));
    uint8_t ack_response[]={2,1,0,0x3a,0,7,0,2,4,0,0,0,0,0};
    feed_qmi(ack_response,sizeof(ack_response));
    assert(g.wlfw.rejuvenate_ack_finished&&g.wlfw.rejuvenate_ack_success&&!g.wlfw.complete);
    reset_tx();g.tftp_flush();assert(g.word(4)==0&&g.wlfw.step==3&&msa_prepare_calls==0);
    // A new service endpoint cancels an unsent ACK and cannot restart initialization.
    g.wlfw=NabuWlfw{};g.wlfw.step=6;feed_qmi(rejuvenate,sizeof(rejuvenate));
    server(4,0,41);assert(g.wlfw.failed&&g.wlfw_port==41&&!g.wlfw.waiting&&g.wlfw.bytes==0);
    reset_tx();g.tftp_flush();assert(g.word(4)==0&&g.wlfw.step==6);
    feed_qmi(ack_response,sizeof(ack_response));assert(!g.wlfw.rejuvenate_ack_finished);
    // Removal of this endpoint cancels an in-flight ACK; an unrelated removal does not.
    g.wlfw=NabuWlfw{};g.wlfw_port=35;feed_qmi(rejuvenate,sizeof(rejuvenate));
    reset_tx();g.tftp_flush();assert(g.wlfw.waiting&&g.wlfw.message==0x3a);
    server(5,0,41);assert(g.wlfw.waiting&&!g.wlfw.failed&&g.wlfw_port==35);
    server(5,0,35);assert(!g.wlfw.waiting&&g.wlfw.failed&&g.wlfw_port==0&&g.wlfw.bytes==0);
    feed_qmi(ack_response,sizeof(ack_response));assert(!g.wlfw.rejuvenate_ack_finished);
    reset_tx();g.tftp_flush();assert(g.word(4)==0);
    server(4,0,41);g.tftp_flush();assert(g.word(4)==0&&g.wlfw.failed);
    g.release();
    check_tftp_reuse();
    check_diag_observation();
    check_diag_handshake();
    check_ulog_commands();
    check_ulog_version_without_registration();
    check_diag_socket_receipts();
    puts("GLINK: original root-ID without confirm, one exact repeat only after WLFW, failed-send/cache/order and retirement checks, two-confirm limit, v1/v3 socket receipts without DIAG success inference; bounded ULog route/CAL gates, framing and existing rings/fragments/KNEL/DMON recovery tests passed");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = (ROOT/'patches/nabu-wireless/NabuGlink.cpp').read_text()
    source = source[source.index('struct GlinkMessage'):]
    source = source[:source.index('extern "C" void nabu_glink_trial')]
    source = source.replace('__asm__ volatile("dsb sy" ::: "memory");', '(void)0;')
    harness = args.output/'glink.cpp'
    modem = (ROOT/'patches/nabu-wireless/NabuModem.cpp').read_text()
    allocation = modem[modem.index('static bool allocate_item('):modem.index('static bool make_smp2p(')]
    harness.write_text(PREFIX+allocation+source+TEST)
    binary = args.output/'glink-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined',
        '-fno-omit-frame-pointer','-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(harness),'-o',host_path(binary)]),check=True)
    result = subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (args.output/'test.log').write_bytes(result.stdout); (args.output/'test.stderr').write_bytes(result.stderr)
    result.check_returncode()
    report = {'production_protocol_tested':True,'sanitizers':['address','undefined'],
              'diag_service':4097,'diag_instances':[0,1,2],'diag_local_ports':[0x4005,0x4006,0x4007],
              'diag_packet_limit_per_channel':3,'diag_prefix_limit':32,
              'diag_payload_responses':True,'apps_feature_hex':'51a00000',
              'ulog_commands':[0x900,0x901,0x904,0x905],
              'ulog_evidence':'wireless-v110/diag-command-route/protocol-spec.json and analysis/nabu-wlan-ulog-export-v110.md',
              'ulog_version_probe_without_registration':True,
              'ulog_probe_evidence':'wireless-v111/diag-registration-followup/findings.md',
              'diag_confirm_probe_evidence':'wireless-v112/diag-rx-followup/confirm-probe-spec.json',
              'diag_confirm_probes':['one exact root ID33 repeat after WLFW','single ULog0900 request'],
              'diag_root_repeat_evidence':'wireless-v113/diag-consumer-followup/findings.md',
              'diag_root_repeat_requires_successful_original_tx':True,
              'diag_confirm_does_not_verify_route':True,
              'hardware_tested':False,'result':result.stdout.decode().splitlines()[-1]}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
