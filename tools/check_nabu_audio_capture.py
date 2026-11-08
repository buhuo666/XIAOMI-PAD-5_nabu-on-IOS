#!/usr/bin/env python3
"""Exercise capture APR wire layouts, lifecycle and requested PCM gain."""
import argparse
import json
from pathlib import Path
from check_nabu_adsp_glink import run
from check_darwinboot_8796 import host_command, host_path
ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cmath>
#include <cstdio>
#include <vector>
#include <algorithm>
#include "NabuAsmCapture.h"
#include "NabuPcmGain.h"
using namespace NabuAsmCapture;
using Bytes=std::vector<uint8_t>;
struct Packet {uint8_t service;uint16_t port;uint32_t op,token;Bytes p;};
struct Peer {
    std::vector<Packet> sent;unsigned delivered=0,frames=0;bool writable=true;
    bool capture_send(uint8_t s,uint16_t p,uint32_t op,uint32_t t,const uint8_t *data,uint32_t n) {
        if(!writable)return false;sent.push_back({s,p,op,t,Bytes(data,data+n)});return true;
    }
    void capture_data(unsigned period,uint32_t off,uint32_t size) {
        assert(period<4&&off+size<=1920);++delivered;frames+=size/2;
    }
};
static Bytes response(const Packet &q,uint32_t op,const Bytes &payload) {
    Bytes p(32+payload.size());p16(p.data(),0x181);p16(p.data()+2,p.size());
    p[4]=p[8]=q.service;p[5]=4;p[9]=5;p16(p.data()+6,q.port);p16(p.data()+10,q.port);
    p32(p.data()+12,q.token);p32(p.data()+16,op);std::copy(payload.begin(),payload.end(),p.begin()+32);return p;
}
struct Fixture {
    Peer peer;Stream<Peer> s{peer};unsigned now=0;
    Fixture() {s.prepare(0x110000000ULL,0x1234,0);}
    Packet command() {auto n=peer.sent.size();s.step(++now);assert(peer.sent.size()==n+1);return peer.sent.back();}
    void ack(const Packet &q,unsigned status=0) {
        Bytes payload(8);p32(payload.data(),q.op);p32(payload.data()+4,status);
        if(q.op==0x10326&&!status) {p32(payload.data(),0);p16(payload.data()+4,0);} // COPP0 is valid.
        auto p=response(q,q.op==0x10326&&!status?0x10329:0x110e8,payload);
        assert(s.receive(p.data(),p.size(),++now));
    }
    void prepare() {
        for(unsigned i=0;i<21;++i) {
            auto q=command();assert(q.service==4&&q.port==0&&q.op==0x100fc);
            assert(u32(q.p.data()+16)==0x10234&&u32(q.p.data()+20)==0);
            if(i<18) {
                assert(q.p.size()==52&&u32(q.p.data()+24)==0x10236);
                assert(u32(q.p.data()+36)==Registers[i].address&&u32(q.p.data()+40)==Registers[i].type);
                assert(u16(q.p.data()+48)==8&&u16(q.p.data()+50)==Registers[i].scale);
            } else {
                const unsigned id[]={0x10296,0x10235,0x10237};assert(u32(q.p.data()+24)==id[i-18]);
                if(i==19)assert(u32(q.p.data()+36)==0x02500100&&u32(q.p.data()+40)==0x217&&u16(q.p.data()+46)==16);
            }
            ack(q);
        }
        assert(s.ready()&&s.result().configured);
    }
    void startup() {
        s.start();const unsigned op[]={0x10db4,0x10c10,0x10326,0x10325,0x100fa,0x100fa,0x100e5,0x10daa};
        for(unsigned i=0;i<8;++i) {
            auto q=command();assert(q.op==op[i]);
            if(i==0)assert(q.port==0x201&&q.p.size()==20&&u16(q.p.data()+16)==16);
            if(i==1)assert(u16(q.p.data()+16)==1&&u32(q.p.data()+20)==48000&&q.p[28]==3);
            if(i==2)assert(q.port==0x4001&&u16(q.p.data()+2)==2&&u16(q.p.data()+12)==1&&q.p[20]==3);
            if(i==3)assert(u32(q.p.data())==1&&u16(q.p.data()+8)==2&&u16(q.p.data()+12)==0);
            if(i==5)assert(q.p.size()==60&&u16(q.p.data())==0x4001&&q.p[48]==134&&u32(q.p.data()+56)==48000);
            ack(q);
        }
        assert(s.result().run&&s.result().copp==0);
    }
    std::vector<Packet> reads() {
        auto n=peer.sent.size();s.step(++now);assert(peer.sent.size()==n+4);
        std::vector<Packet> v(peer.sent.begin()+n,peer.sent.end());
        for(unsigned i=0;i<4;++i) {
            auto &q=v[i];assert(q.op==0x10dac&&q.port==0x201&&q.p.size()==20);
            assert(u32(q.p.data())==0x10004000+i*4096&&u32(q.p.data()+4)==1&&u32(q.p.data()+8)==0x1234);
            assert(u32(q.p.data()+12)==1920&&(q.token&0xf0000000)==0x40000000);
        }
        return v;
    }
    Bytes done(const Packet &q,unsigned bytes=1920,unsigned offset=0) {
        Bytes p(44);std::copy(q.p.begin(),q.p.begin()+12,p.begin()+4);p32(p.data()+16,bytes);p32(p.data()+20,offset);
        p32(p.data()+36,1);return response(q,0x10d9a,p);
    }
    void deliver(const Bytes &p) {assert(s.receive(p.data(),p.size(),++now));}
    void close(unsigned failure=0) {
        s.finish();const unsigned op[]={0x10bcd,0x10327,0x100e6};
        for(unsigned i=0;i<3;++i) {auto q=command();assert(q.op==op[i]);ack(q,failure==i+1?3:0);}
        assert(!s.busy());
        assert(s.result().closed==(failure!=1));assert(s.result().copp_closed==(failure!=2));
        assert(s.result().port_stopped==(failure!=3));assert(s.result().mapping_retained==(failure==1));
    }
};
static void capture() {
    Fixture f;f.prepare();f.startup();auto q=f.reads();
    auto wrong=f.done(q[0]);p16(wrong.data()+6,0x101);f.deliver(wrong);
    wrong=f.done(q[0]);p32(wrong.data()+44,0x5555);f.deliver(wrong);
    assert(f.peer.delivered==0&&f.s.result().pending==15);
    for(auto it=q.rbegin();it!=q.rend();++it)f.deliver(f.done(*it));
    assert(f.peer.frames==3840&&f.s.result().pending==0);f.reads();
    f.close();assert(f.s.ready());
    f.startup();auto restarted=f.reads();
    f.deliver(f.done(q[0]));assert(f.s.result().pending==15); // Old run cannot consume a new slot.
    f.deliver(f.done(restarted[0],1880,40));assert(f.peer.frames==4780);
    f.close();assert(f.s.result().starts==2&&f.s.result().stops==2);
    for(unsigned failure=1;failure<=3;++failure) {
        Fixture x;x.prepare();x.startup();x.reads();x.close(failure);assert(x.s.result().failed);
    }
    {Fixture x;x.prepare();x.startup();auto v=x.reads();x.deliver(x.done(v[0],1920,2));
        assert(x.s.result().failed);x.close();assert(!x.s.result().mapping_retained);}
    {Fixture x;x.prepare();x.startup();x.reads();x.now+=5000;x.s.finish();
        auto q=x.command();assert(q.op==0x10bcd&&!x.s.result().timeout);x.ack(q);
        x.ack(x.command());x.ack(x.command());assert(x.s.ready());}
    {Fixture x;x.prepare();x.s.start();auto open=x.command();x.s.finish();x.ack(open);
        auto close=x.command();assert(close.op==0x10bcd);x.ack(close);assert(x.s.ready()&&!x.s.result().port_on);}
    {Fixture x;x.prepare();x.startup();x.reads();x.s.finish();x.command();x.now+=1100;x.s.step(x.now);
        auto q=x.command();assert(q.op==0x10327);x.ack(q);x.ack(x.command());
        assert(x.s.result().timeout&&x.s.result().mapping_retained&&!x.s.result().closed);}
}
static void gain() {
    using namespace NabuPcmGain;
    for(unsigned below=0;below<=384;++below) {
        double reference=std::pow(10.0,(24.0-below/8.0)/20.0);
        auto g=NabuPcmGain::gain(below,false);assert(std::abs(g/(double)(1<<24)-reference)<0.00002);
        assert(NabuPcmGain::gain(below,true)==0);
        for(int value=-32768;value<=32767;value+=127) {
            uint64_t clips=0;int got=sample(int16_t(value),g,clips);
            double expect=std::max(-32768.0,std::min(32767.0,std::trunc(value*reference)));
            assert(std::abs(got-expect)<=1);assert(clips<=1);assert(!value||got*int64_t(value)>=0);
        }
    }
    uint64_t clips=0;assert(sample(3000,Maximum,clips)==32767&&sample(-3000,Maximum,clips)==-32768&&clips==2);
    assert(sample(32767,0,clips)==0);
}
int main() {capture();gain();std::puts("PASS: AFE original codec config, mono TX134, COPP0, capture/restart/late events, real close failures/timeouts, +24dB gain and saturation");}
'''
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    source=a.output/'capture.cpp';binary=a.output/'capture';source.write_text(HARNESS)
    run(host_command(['clang++-18','-std=c++17','-O1','-g','-fsanitize=address,undefined',
        '-fno-omit-frame-pointer','-Wall','-Wextra','-Werror','-I'+host_path(ROOT/'patches/nabu-audio'),
        host_path(source),'-o',host_path(binary)]))
    result=run(host_command([host_path(binary)]))
    report={'status':'passed','result':result.strip(),'device_executed':False,'sanitizers':['address','undefined']}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
