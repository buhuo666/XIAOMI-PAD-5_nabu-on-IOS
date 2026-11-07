#!/usr/bin/env python3
"""Replay production CE polling/HTC transport with actual allocated host buffers and a DMA peer."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include "NabuWlanTransport.h"
struct Peer {
    unsigned cursor=0,syncs=0,barriers=0;
    std::map<unsigned,uint32_t> regs;
    std::map<uint32_t,void *> memory;
    std::vector<std::pair<unsigned,uint32_t>> writes;
    std::vector<std::string> events;
    ~Peer(){for(auto &m:memory)free(m.second);}
    NabuWlanTransport::Ops ops() {
        return {this,
            [](void *x,unsigned bytes,unsigned align,NabuWlanDma::Buffer &b){auto &p=*(Peer *)x;
                unsigned at=(p.cursor+align-1)&~(align-1);
                if(at%65536+bytes>65536)at=(at+65535)&~65535u;
                if(at+bytes>0x800000)return false;
                void *cpu=aligned_alloc(64,(bytes+63)&~63u);assert(cpu);memset(cpu,0,bytes);
                b={cpu,0xa0000000+at,bytes};p.memory[b.iova]=cpu;p.cursor=at+bytes;return true;},
            [](void *,const NabuWlanDma::Buffer &b)->void *{assert(b.bytes==65536&&(b.iova&65535)==0);return b.cpu;},
            [](void *x,NabuWlanDma::Buffer &){++((Peer *)x)->syncs;},
            [](void *x,unsigned at){return ((Peer *)x)->regs[at];},
            [](void *x,unsigned at,uint32_t v){auto &p=*(Peer *)x;p.regs[at]=v;p.writes.push_back({at,v});},
            [](void *x){++((Peer *)x)->barriers;},
            [](void *x,const char *event,unsigned,unsigned){((Peer *)x)->events.push_back(event);}};
    }
    void receive(NabuWlanTransport &t,unsigned pipe,const std::vector<uint8_t> &frame) {
        auto &r=*t.find(pipe,false);unsigned at=r.ce.consumer;
        auto &b=*(NabuWlanDma::Buffer *)r.ce.contexts[at];assert(frame.size()<=b.bytes);
        memcpy(b.cpu,frame.data(),frame.size());r.ce.descriptors[at].bytes=frame.size();
    }
};
int main() {
    auto *t=new NabuWlanTransport;Peer p;
    assert(t->prepare(p.ops())&&t->phase==NabuWlanTransport::Prepared&&p.writes.empty());
    assert(t->ring_count==12&&t->buffer_count==4852&&p.cursor<0x800000);
    assert(t->start()&&t->phase==NabuWlanTransport::Running);
    assert(p.regs[0x24c004]==t->rri.iova&&p.regs[0x24c008]==0);
    assert(p.regs[0x242014]==64&&p.regs[0x242040]==63);
    for(unsigned id=0;id<12;++id)assert((p.regs[NabuSnocPipe::base(id)+0x2c]&0x1f)==0);
    // Actual peer READY in a posted CE2 DMA buffer, followed by actual TX descriptor.
    p.receive(*t,2,{0,0,8,0,0,0,0,0,1,0,7,0,0,1,9,0});t->poll();
    assert(t->htc_ready_seen&&t->tx_packets==1&&t->htc.waiting&&t->htc.pending_service==0x100);
    auto &tx=*t->find(0,true);assert(tx.ce.descriptors[0].bytes==16&&p.regs[0x32000]==1);
    const uint8_t connect[]={0,0,8,0,0,0,0,0,2,0,0,1,0,1,0,0};
    assert(!memcmp(tx.packets[0].cpu,connect,sizeof(connect)));
    // Consume the source descriptor and respond through a second posted RX buffer.
    p.regs[0x240044]=1;
    p.receive(*t,2,{0,0,8,0,0,0,0,0,3,0,0,1,0,3,0,4});t->poll();
    assert(t->tx_completed==1&&t->wmi_connected_seen&&t->htc.endpoint_for(0x100)==3);
    assert(!t->htc.endpoint_for(0x300)&&t->htc.state!=NabuHtc::Started&&t->tx_packets==1);
    p.receive(*t,2,{3,0,4,0,0,0,0,0,0x34,0x12,0,0});t->poll();
    assert(t->wmi_packets==1&&t->last_wmi_event==0x1234&&t->rx_packets==3);
    auto &rx=*t->find(2,false);assert(rx.ce.available()==0&&rx.ce.consumer==3);
    // Credit/HTC parser works from received bytes; polling cannot manufacture READY.
    unsigned before=p.writes.size();t->lost();t->poll();assert(p.writes.size()==before&&!t->transmit(0,connect,sizeof(connect)));
    delete t;
    {auto *q=new NabuWlanTransport;Peer silent;assert(q->prepare(silent.ops())&&q->start());
        for(unsigned i=0;i<5000;++i)q->poll();
        assert(q->phase==NabuWlanTransport::Failed&&!q->htc_ready_seen&&q->tx_packets==0);delete q;}
    {auto *q=new NabuWlanTransport;Peer busy;assert(q->prepare(busy.ops()));
        busy.regs[0x240044]=1;
        assert(!q->start()&&q->phase==NabuWlanTransport::Failed);delete q;}
    puts("Production CE resources, RRI/shadow doorbells, peer DMA HTC READY and WMI connect, bounded RX repost/TX completion, no fabricated READY/HTT/setup, timeout/loss passed");
}
'''
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);source=a.output/'runtime.cpp';source.write_text(HARNESS)
    binary=a.output/'runtime-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    r=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (a.output/'test.log').write_bytes(r.stdout);(a.output/'test.stderr').write_bytes(r.stderr);r.check_returncode()
    report={'hardware_tested':False,'sanitizers':['address','undefined'],'result':r.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
