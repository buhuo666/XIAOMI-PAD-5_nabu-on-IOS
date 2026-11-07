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
    g.diag_summary();assert(captured_log.size()<1900);
    assert(captured_log.find("inst=0 packets=5 captured=3 omitted=2 bytes=111 raw-bytes=43 omitted-bytes=68 last=1:91 changes=1")!=std::string::npos);
    assert(captured_log.find("inst=2 packets=4 captured=3 omitted=1 bytes=75 raw-bytes=33 omitted-bytes=42 last=3:101 changes=1")!=std::string::npos);
    NabuGlink empty{};captured_log.clear();empty.diag_summary();
    assert(captured_log.find("inst=0 packets=0 captured=0 omitted=0 bytes=0 raw-bytes=0 omitted-bytes=0")!=std::string::npos);
    assert(captured_log.find("inst=2 packets=0 captured=0 omitted=0 bytes=0 raw-bytes=0 omitted-bytes=0")!=std::string::npos);
    rmtfs_available=false;
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
    puts("GLINK: bounded DIAG 4097 control/data observation, public MODEM/TZ TOC metadata without payload reads, APPS-visible prefixes, rings/fragments, KNEL/DMON routing and recovery stop passed");
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
              'diag_service':4097,'diag_instances':[0,2],'diag_local_ports':[0x4005,0x4006],
              'diag_packet_limit_per_channel':3,'diag_prefix_limit':32,
              'diag_payload_responses':False,
              'hardware_tested':False,'result':result.stdout.decode().splitlines()[-1]}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
