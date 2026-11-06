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
#include <vector>
#include "NabuSmem.h"
#include "NabuTftp.h"
#include "NabuServreg.h"
using vm_offset_t = uintptr_t;
static void *IOMalloc(size_t n) { return malloc(n); }
static void IOFree(void *p, size_t) { free(p); }
static void IOSleep(unsigned) {}
static bool nabu_rmtfs_available() { return false; }
static unsigned nabu_rmtfs_request(const uint8_t *, unsigned, uint8_t *) { return 0; }
static void nabu_wireless_log(const char *format, ...) {
    va_list args; va_start(args,format); vprintf(format,args); va_end(args);
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
    g.release();
    puts("GLINK: wraparound, version/open, intents, v1/v2 QRTR, fragments, resume, reuse and queue bounds passed");
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
              'hardware_tested':False,'result':result.stdout.decode().splitlines()[-1]}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
