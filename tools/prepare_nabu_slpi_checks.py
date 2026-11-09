#!/usr/bin/env python3
"""Build/run SLPI image, host-isolation and bounded GLINK census host checks."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
import tarfile
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <string>
#include <vector>
#include "NabuSlpiProtocol.h"
#include "NabuSlpiGlink.h"
using Bytes=std::vector<uint8_t>;
// Values are extracted from the captured Android DT, not the driver constants.
// qcom,smp2p consumes qcom,smem cells in inbound, outbound order.
constexpr uint32_t AndroidIncoming=@@INCOMING@@, AndroidOutgoing=@@OUTGOING@@;
static void p16(Bytes &b,size_t at,uint16_t x){b.at(at)=x;b.at(at+1)=x>>8;}
static void p32(Bytes &b,size_t at,uint32_t x){p16(b,at,x);p16(b,at+2,x>>16);}
static uint32_t u32(const Bytes &b,size_t at){return NabuSlpi::le32(b.data()+at);}
struct Memory {
    Bytes b=Bytes(NabuSlpi::SmemSize);
    std::vector<uint32_t> writes;
    NabuSmem view(){return {b.data(),uint32_t(b.size())};}
    void put(uint32_t at,uint32_t x){p32(b,at,x);writes.push_back(at);}
    void layout(){
        uint32_t toc=NabuSlpi::SmemSize-4096;put(toc,0x434f5424);put(toc+4,1);put(toc+8,4);
        for(unsigned i=0;i<4;++i){
            uint32_t base=0x1000+i*0x10000,e=toc+32+i*48,hosts=i?i<<16:0xfffefffe;
            put(e,base);put(e+4,0x10000);put(e+12,hosts);put(e+16,32);
            put(base,0x54525024);put(base+4,hosts);put(base+8,0x10000);put(base+12,32);put(base+16,0x10000);
        }
        writes.clear();
    }
};
static void memory_test(){
    assert(NabuSlpi::Incoming==AndroidIncoming&&NabuSlpi::Outgoing==AndroidOutgoing);
    Memory m;m.layout();uint32_t at;assert(NabuSlpi::allocate(m.view(),m,NabuSlpi::Outgoing,340,at));
    assert(at>=0x31000&&at<0x41000);for(auto x:m.writes)assert(x>=0x31000&&x<0x41000);
    NabuSlpi::publish_smp2p(m,at);assert(u32(m.b,at+8)==0x30000);assert(u32(m.b,at+4)==0x101);
    assert(!memcmp(m.b.data()+at+20,"master-kernel",14));
    NabuSmemItem item;assert(!NabuSlpi::find(m.view(),AndroidIncoming,item));
    assert(NabuSlpi::find(m.view(),AndroidOutgoing,item)&&item.offset==at);
    uint32_t incoming;assert(NabuSlpi::allocate(m.view(),m,AndroidIncoming,340,incoming));
    m.put(incoming,0x504d5324);m.put(incoming+4,0x101);m.put(incoming+8,3);m.put(incoming+12,0x10010);
    memcpy(m.b.data()+incoming+20,"slave-kernel",13);m.put(incoming+36,2);
    Bytes before=m.b;m.writes.clear();
    assert(NabuSlpi::peer(m.view()).valid&&NabuSlpi::peer(m.view()).state==2);
    assert(m.b==before&&m.writes.empty()); // DSP-owned item is read-only to APPS.
    for(uint32_t state:{1u,6u,8u,128u}){
        m.put(incoming+36,state);assert(NabuSlpi::peer(m.view()).state==state);
    }
    m.put(incoming+8,2);assert(!NabuSlpi::peer(m.view()).valid);
}
struct Operations {
    std::string fail;
    bool released=false,shutdown_called=false,probed=false;
    bool yes(const char *s){return fail!=s;}
    bool prepare(){return yes("prepare");}bool aop_vote(bool on){return yes(on?"on":"off");}
    bool proxy_vote(){return yes("proxy");}bool init_image(){return yes("init");}
    bool memory_setup(){return yes("memory");}bool copy_segments(){return yes("copy");}
    bool auth_reset(){return yes("auth");}bool wait_ready(){return yes("ready");}
    void observe(){}void probe(){probed=true;}bool request_stop(){return yes("stop");}
    bool shutdown(){shutdown_called=true;return yes("shutdown");}void release(){released=true;}
};
static void lifecycle_test(){
    for(const char *f:{"","prepare","on","proxy","init","memory","copy","auth","ready","stop","shutdown","off"}){
        Operations o;o.fail=f;auto r=NabuSlpi::run(o);
        if(o.fail=="shutdown"){assert(r.retained&&!o.released);}
        else assert(o.released&&!r.retained);
        if(o.fail=="ready")assert(!o.probed&&o.shutdown_called);
        if(o.fail.empty())assert(r.ready&&r.shutdown&&r.stop_ack&&r.off&&o.probed);
    }
}
struct Wire {
    Bytes b=Bytes(0xa000);
    unsigned rings=0,announcements=0;
    uint32_t read32(uint32_t at){return u32(b,at);}
    void write32(uint32_t at,uint32_t x){p32(b,at,x);}
    uint8_t read8(uint32_t at){return b.at(at);}void write8(uint32_t at,uint8_t x){b.at(at)=x;}
    void ring(){++rings;}
    void server(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t){++announcements;}
    void rx(uint16_t cmd,uint16_t cid,uint32_t value,const Bytes &extra={}){
        Bytes p((8+extra.size()+7)&~size_t(7));p16(p,0,cmd);p16(p,2,cid);p32(p,4,value);
        for(size_t i=0;i<extra.size();++i)p[8+i]=extra[i];
        uint32_t at=read32(12);for(auto c:p){b.at(0x5000+at)=c;at=(at+1)%0x4000;}write32(12,at);
    }
    void qrtr(uint32_t command,uint32_t service=0,uint32_t node=0,uint32_t port=0,bool fragmented=false){
        Bytes p(52);p32(p,0,1);p32(p,4,command);p32(p,8,9);p32(p,12,0xfffffffe);
        p32(p,20,20);p32(p,24,1);p32(p,28,0xfffffffe);p32(p,32,command);
        p32(p,36,service);p32(p,40,1);p32(p,44,node);p32(p,48,port);
        Bytes a(8+(fragmented?20:p.size()));p32(a,0,a.size()-8);p32(a,4,fragmented?p.size()-20:0);
        memcpy(a.data()+8,p.data(),a.size()-8);rx(9,6,1,a);
        if(fragmented){Bytes c(8+p.size()-20);p32(c,0,p.size()-20);memcpy(c.data()+8,p.data()+20,p.size()-20);rx(12,6,1,c);}
    }
    void opened(NabuSlpiGlink::Link<Wire> &link){
        assert(link.begin(0,0x1000,0x4000,0x5000,0x4000));
        rx(1,1,1);rx(2,6,7,Bytes{'I','P','C','R','T','R',0});rx(4,1,0);
        Bytes pair(8);p32(pair,0,8192);p32(pair,4,0);rx(5,6,1,pair);link.step(0);
        assert(link.result().opened&&!link.result().broken);
        qrtr(2);rx(14,6,0);link.step(10);assert(!link.result().broken);
    }
};
static void glink_test(){
    Wire w;NabuSlpiGlink::Link<Wire> l(w);w.opened(l);
    w.qrtr(4,400,9,12,true);l.step(20);
    assert(l.result().ssc_found&&l.result().ssc_node==9&&l.result().ssc_port==12&&l.result().close_sent);
    w.rx(11,1,0);l.step(30);assert(l.done()&&l.result().close_ack&&!l.result().timeout);
    Wire empty;NabuSlpiGlink::Link<Wire> no_sensors(empty);empty.opened(no_sensors);
    no_sensors.step(10000);assert(no_sensors.result().timeout&&no_sensors.result().close_sent);
    no_sensors.step(11000);assert(no_sensors.done()&&!no_sensors.result().ssc_found);
    Wire silent;NabuSlpiGlink::Link<Wire> none(silent);assert(none.begin(0,0x1000,0x4000,0x5000,0x4000));none.step(5000);assert(none.done()&&none.result().timeout);
    Wire invalid;NabuSlpiGlink::Link<Wire> broken(invalid);invalid.opened(broken);invalid.rx(9,6,11,Bytes(8));broken.step(20);assert(broken.done()&&broken.result().broken);
}
int main(int argc,char **argv){
    assert(argc==2);std::ifstream f(argv[1],std::ios::binary);Bytes b((std::istreambuf_iterator<char>(f)),{});
    NabuSlpi::Image image;assert(NabuSlpi::parse_image(b.data(),b.size(),image));
    assert(image.relocated&&image.link_base==0x97300000&&image.load_bytes==0x1400000&&image.count==20);
    assert(image.segments[0].original==0x97300000&&image.segments[0].physical==0x97b00000);
    auto last=image.segments[image.count-1];assert(last.physical+last.memory_bytes==NabuSlpi::MemoryEnd);
    b.resize(100);assert(!NabuSlpi::parse_image(b.data(),b.size(),image));
    memory_test();lifecycle_test();glink_test();
    puts("PASS: Android DT SMP2P direction/ownership, real slpi_nb MDT relocation, host3 isolation, start/unwind failures, GLINK fragmented SSC discovery and absent-service deadlines");
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware',type=Path,required=True)
    p.add_argument('--device-tree',type=Path,required=True,
                   help='Captured Android device-tree.tar; qcom,smem is inbound then outbound')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    source=a.output/'slpi-host.cpp';binary=a.output/'slpi-host'
    dt_path='base/soc/qcom,smp2p-dsps@1799000c/qcom,smem'
    with tarfile.open(a.device_tree) as tree:
        incoming,outgoing=struct.unpack('>II',tree.extractfile(dt_path).read())
    source.write_text(HARNESS.replace('@@INCOMING@@',str(incoming)).replace('@@OUTGOING@@',str(outgoing)),encoding='utf-8')
    command=host_command(['g++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
                         '-fsanitize=address,undefined','-fno-omit-frame-pointer','-g',
                         '-I'+host_path(ROOT/'patches/nabu-sensors'),host_path(source),'-o',host_path(binary)])
    compiled=subprocess.run(command,capture_output=True)
    (a.output/'compile.log').write_bytes(compiled.stdout+compiled.stderr)
    if compiled.returncode:raise SystemExit(compiled.stderr.decode(errors='replace'))
    result=subprocess.run(host_command([host_path(binary),host_path(a.firmware/'slpi_nb.mdt')]),
                          capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15)
    report=dict(command=command,result=result.stdout,stderr=result.stderr,passed=result.returncode==0,
                android_device_tree=str(a.device_tree),dt_property=dt_path,
                smp2p_incoming=incoming,smp2p_outgoing=outgoing,device_execution=False,
                limitation='Host substitutes MMIO and time; no secure firmware, DSP, sensor_pd or iPadOS sensor API executed.')
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(result.stdout)
    if result.returncode:raise SystemExit(result.stderr)


if __name__=='__main__':main()
