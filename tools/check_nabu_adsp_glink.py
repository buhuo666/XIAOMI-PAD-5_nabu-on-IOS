#!/usr/bin/env python3
"""Exercise the production ADSP GLINK/APR state machine with fake SMEM and time.

Only the memory/doorbell provider is replaced. The host neither boots a DSP nor
executes firmware, and passing tests do not establish PCM or acoustic output.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def run(command):
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{command!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout


HARNESS = r'''
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "NabuAdspGlink.h"
using Bytes = std::vector<uint8_t>;
static unsigned checks;
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr,"line %d: %s\n",__LINE__,#x); std::abort(); } ++checks; } while (0)
static uint16_t u16(const Bytes &b, size_t p) { return b.at(p) | uint16_t(b.at(p+1)) << 8; }
static uint32_t u32(const Bytes &b, size_t p) { return u16(b,p) | uint32_t(u16(b,p+2)) << 16; }
static void put16(Bytes &b, size_t p, uint16_t v) { b.at(p)=v; b.at(p+1)=v>>8; }
static void put32(Bytes &b, size_t p, uint32_t v) { put16(b,p,v); put16(b,p+2,v>>16); }
static Bytes frame(uint16_t cmd, uint16_t cid, uint32_t value, const Bytes &extra={}) {
    Bytes b((8+extra.size()+7)&~size_t(7),0); put16(b,0,cmd); put16(b,2,cid); put32(b,4,value);
    std::copy(extra.begin(),extra.end(),b.begin()+8); return b;
}
static Bytes open_frame(uint16_t cid, const char *name="apr_audio_svc") {
    Bytes b(name,name+std::strlen(name)+1); return frame(2,cid,b.size(),b);
}
static Bytes intent_frame(uint16_t cid, uint32_t id, uint32_t size=512) {
    Bytes b(8); put32(b,0,size); put32(b,4,id); return frame(5,cid,1,b);
}
static Bytes data_frame(uint16_t cid, uint32_t iid, const Bytes &b, uint32_t left=0, uint16_t cmd=9) {
    Bytes extra(8+b.size()); put32(extra,0,b.size()); put32(extra,4,left);
    std::copy(b.begin(),b.end(),extra.begin()+8); return frame(cmd,cid,iid,extra);
}
static Bytes reply(uint32_t token, uint32_t state=1) {
    Bytes b(24); put16(b,0,0x150); put16(b,2,24);
    b[4]=3; b[5]=4; b[8]=3; b[9]=5; put32(b,12,token); put32(b,16,0x1290d); put32(b,20,state); return b;
}
static Bytes basic_reply(uint32_t token, uint32_t status, uint32_t command=0x1290c) {
    Bytes b=reply(token); b.resize(28); put16(b,2,28); put32(b,16,0x110e8);
    put32(b,20,command); put32(b,24,status); return b;
}
static Bytes extended_reply(uint32_t token,uint32_t state=1) {
    Bytes b=reply(token,state); b.insert(b.begin()+20,12,0); put16(b,0,0x81); put16(b,2,b.size()); return b;
}
static Bytes version_reply(uint32_t token,unsigned count=3) {
    Bytes b=extended_reply(token); b.resize(52+count*12); put16(b,2,b.size()); put32(b,16,0x1292d);
    for(unsigned i=0;i<4;++i)put32(b,32+i*4,10+i);
    put32(b,48,count);
    for(unsigned i=0;i<count;++i) {
        put32(b,52+i*12,i==0?4:i==1?7:i==2?8:0x100+i);
        put32(b,56+i*12,2+i); put32(b,60+i*12,5+i);
    }
    return b;
}

struct FakeIO {
    static constexpr uint32_t desc=0x100, tx=0x1000, rx=0x4000;
    std::array<uint8_t,65536> memory{};
    uint32_t size=4096, bells=0, writes=0;
    explicit FakeIO(uint32_t ring_size=4096):size(ring_size) {}
    uint8_t read8(uint32_t at) { return memory.at(at); }
    uint32_t read32(uint32_t at) {
        CHECK(!(at&3)); return uint32_t(memory.at(at)) | uint32_t(memory.at(at+1))<<8 |
            uint32_t(memory.at(at+2))<<16 | uint32_t(memory.at(at+3))<<24;
    }
    void peer_word(uint32_t at,uint32_t v) { for(unsigned i=0;i<4;++i) memory.at(at+i)=v>>(i*8); }
    void write8(uint32_t at,uint8_t v) {
        CHECK(at>=tx && at<tx+size); memory.at(at)=v; ++writes;
    }
    void write32(uint32_t at,uint32_t v) {
        CHECK(at==desc+4 || at==desc+8); CHECK(v<size && !(v&7)); peer_word(at,v); ++writes;
    }
    void ring() { ++bells; }
    void initial_position(uint32_t pos) { for(unsigned i=0;i<4;++i) peer_word(desc+i*4,pos); }
    void inject(const Bytes &b) {
        CHECK(!(b.size()&7)); uint32_t head=read32(desc+12),tail=read32(desc+8);
        CHECK(b.size() < (tail+size-head-1)%size+1);
        for(size_t i=0;i<b.size();++i) memory.at(rx+(head+i)%size)=b[i];
        peer_word(desc+12,(head+b.size())%size);
    }
    std::vector<Bytes> take() {
        uint32_t head=read32(desc+4),tail=read32(desc);
        Bytes pending; while(tail!=head) { pending.push_back(memory.at(tx+tail)); tail=(tail+1)%size; }
        peer_word(desc,tail); std::vector<Bytes> out;
        for(size_t p=0;p<pending.size();) {
            CHECK(pending.size()-p>=8); uint16_t cmd=u16(pending,p); size_t n=8;
            if(cmd==2)n+=u32(pending,p+4);
            if(cmd==5)n+=8*u32(pending,p+4);
            if(cmd==9 || cmd==12)n+=8+u32(pending,p+8);
            n=(n+7)&~size_t(7); CHECK(n<=pending.size()-p);
            out.emplace_back(pending.begin()+p,pending.begin()+p+n); p+=n;
        }
        return out;
    }
};
struct Fixture {
    FakeIO io;
    NabuAdspGlink::Link<FakeIO> link;
    uint16_t peer=37;
    uint32_t peer_iid=91;
    explicit Fixture(uint32_t size=4096,uint32_t start=0,bool versions=false,bool mapping=false):io(size),link(io) {
        io.initial_position(start);
        CHECK(link.begin(FakeIO::desc,FakeIO::tx,size,FakeIO::rx,size,versions,mapping?0x110000000ULL:0,mapping?16384:0));
        auto first=io.take(); CHECK(first.size()==1 && first[0]==frame(0,1,1));
    }
    std::vector<Bytes> step(uint32_t time) { link.step(time); return io.take(); }
    void establish(uint32_t feature=1,bool remote_first=false) {
        if(remote_first)io.inject(open_frame(peer));
        io.inject(frame(0,1,feature)); io.inject(frame(1,1,feature));
        auto tx=step(0); CHECK(tx.size()==(remote_first?3:2));
        CHECK(tx[remote_first?1:0]==frame(1,1,feature));
        CHECK(tx.back()==open_frame(2));
        io.inject(frame(4,peer,0));
        CHECK(step(0).empty()); CHECK(!link.result().local_open_ack);
        if(!remote_first)io.inject(open_frame(peer));
        io.inject(frame(4,2,0));
        tx=step(0); CHECK(tx.size()==(remote_first?1:2));
        if(!remote_first)CHECK(tx[0]==frame(4,peer,0));
        const auto &offered=tx.back(); CHECK(u16(offered,0)==5 && u16(offered,2)==2 && u32(offered,4)==20);
        CHECK(offered.size()==168);
        for(unsigned i=0;i<20;++i) { CHECK(u32(offered,8+i*8)==512); CHECK(u32(offered,12+i*8)==i+1); }
        CHECK(link.result().negotiated && link.result().opened && link.result().features==feature);
        CHECK(!link.result().apr_sent);
    }
    uint32_t ask(uint32_t time=100) {
        io.inject(intent_frame(peer,peer_iid));
        auto tx=step(time); CHECK(tx.size()==1); const auto &q=tx[0];
        CHECK(u16(q,0)==9 && u16(q,2)==2 && u32(q,4)==peer_iid);
        CHECK(u32(q,8)==20 && u32(q,12)==0 && q.size()==40);
        uint32_t token=u32(q,28); CHECK(token!=0 && token==link.result().token);
        Bytes expected={0x50,0x02,0x14,0x00,0x03,0x05,0x00,0x00,0x03,0x04,0x00,0x00,0,0,0,0,0x0c,0x29,0x01,0x00};
        put32(expected,12,token); CHECK(std::equal(expected.begin(),expected.end(),q.begin()+16));
        CHECK(link.result().apr_sent); return token;
    }
    void finish(uint32_t time=120) {
        io.inject(frame(11,peer,0)); CHECK(step(time).empty()); CHECK(!link.done());
        io.inject(frame(3,peer,0)); io.inject(frame(11,2,0));
        auto tx=step(time+1); CHECK(tx.size()==1 && tx[0]==frame(11,peer,0));
        CHECK(link.done() && link.result().close_ack && link.result().remote_closed && !link.result().broken);
    }
};

static void success_and_wrap() {
    for(unsigned wrapped=0;wrapped<2;++wrapped) {
        Fixture f(4096,wrapped?4088:0); f.establish(1,wrapped);
        CHECK(f.step(99).empty()); uint32_t token=f.ask();
        if(wrapped) { f.io.peer_word(FakeIO::desc+8,4088); f.io.peer_word(FakeIO::desc+12,4088); }
        f.io.inject(data_frame(f.peer,20,reply(token)));
        auto tx=f.step(110); CHECK(tx.size()==2 && tx[0]==frame(14,2,20) && tx[1]==frame(3,2,0));
        CHECK(f.link.result().apr_response && f.link.result().apr_ready && f.link.result().apr_state==1);
        CHECK(f.link.result().close_sent); f.finish();
    }
}
static void negotiation_and_channels() {
    Fixture f; f.io.inject(frame(1,1,0));
    auto tx=f.step(0); CHECK(tx.size()==1 && tx[0]==frame(0,1,0)); CHECK(!f.link.result().negotiated);
    f.io.inject(frame(1,1,0)); tx=f.step(1); CHECK(tx.size()==1 && tx[0]==open_frame(2));
    f.io.inject(open_frame(99,"IPCRTR")); CHECK(f.step(2).empty()); CHECK(f.link.result().unknown_channels==1);
    f.io.inject(open_frame(f.peer)); f.io.inject(frame(4,2,0)); tx=f.step(3); CHECK(tx.size()==2);
    f.io.inject(intent_frame(2,77)); CHECK(f.step(103).size()==1); CHECK(!f.link.result().apr_sent);
    uint32_t t=f.ask(104); f.io.inject(data_frame(f.peer,1,reply(t))); tx=f.step(105);
    CHECK(tx.size()==3 && tx[0]==frame(6,2,1) && tx[1]==intent_frame(2,1) && tx[2]==frame(3,2,0));
    f.finish(106);
    Fixture rejected; rejected.io.inject(frame(1,0,0)); rejected.step(0);
    CHECK(rejected.link.done() && rejected.link.result().error==NabuAdspGlink::VersionRejected);
}
static void identity_and_lengths() {
    Fixture f; f.establish(); uint32_t token=f.ask();
    // Each complete unrelated packet must release its receive intent without satisfying our command.
    std::vector<Bytes> wrong;
    for(unsigned field:{4u,5u,6u,8u,9u,10u}) { Bytes b=reply(token); b[field]^=1; wrong.push_back(b); }
    CHECK(token==1); Bytes b=reply(token+1); wrong.push_back(b);
    b=reply(0); wrong.push_back(b); // Vendor sends token zero; it cannot satisfy this host's token one.
    b=reply(token); put16(b,0,0x152); wrong.push_back(b);
    b=reply(token); put16(b,0,0x140); wrong.push_back(b);
    b=reply(token); put16(b,2,19); wrong.push_back(b);
    b=reply(token); put16(b,2,28); wrong.push_back(b);
    b=reply(token); b.resize(22); put16(b,2,22); wrong.push_back(b);
    b=reply(token); b.resize(16); wrong.push_back(b);
    b=reply(token); put32(b,16,0x12906); wrong.push_back(b);
    b=basic_reply(token,0,0x9999); wrong.push_back(b);
    for(const auto &packet:wrong) {
        f.io.inject(data_frame(f.peer,3,packet)); auto tx=f.step(110);
        CHECK(tx.size()==1 && tx[0]==frame(14,2,3)); CHECK(!f.link.result().apr_response && !f.link.result().apr_ready);
    }
    CHECK(f.link.result().apr_ignored==wrong.size());
    f.io.inject(data_frame(2,3,reply(token))); CHECK(f.step(111).empty()); CHECK(!f.link.result().apr_response);
    // Header-length extension: state is at encoded header length, never assumed offset 20.
    b=reply(token,2); b.insert(b.begin()+20,4,0); put16(b,0,0x160); put16(b,2,28);
    f.io.inject(data_frame(f.peer,3,b)); auto tx=f.step(112);
    CHECK(tx.size()==2 && f.link.result().apr_response && f.link.result().apr_ready && f.link.result().apr_state==2);
    f.finish();
    // The original vendor dispatches this opcode without a type==CMD_RSP gate.
    // Version one is also accepted by its APR parser; retain the actual fields.
    for(uint16_t field:{uint16_t(0x050),uint16_t(0x150),uint16_t(0x251),uint16_t(0x350)}) {
        Fixture compatible; compatible.establish(); auto current=compatible.ask();
        Bytes packet=reply(current); put16(packet,0,field);
        compatible.io.inject(data_frame(compatible.peer,1,packet)); compatible.step(110);
        CHECK(compatible.link.result().apr_ready && compatible.link.result().apr_field==field);
        CHECK(compatible.link.result().apr_type==((field>>8)&3)); compatible.finish();
    }
}
static void fragments_and_partial_frames() {
    Fixture f; f.establish(); uint32_t token=f.ask(); Bytes b=reply(token);
    Bytes first(b.begin(),b.begin()+10),last(b.begin()+10,b.end());
    f.io.inject(data_frame(f.peer,4,first,14)); CHECK(f.step(110).empty()); CHECK(!f.link.result().apr_response);
    f.io.inject(data_frame(f.peer,4,last,0,12)); auto tx=f.step(111); CHECK(tx.size()==2 && f.link.result().apr_ready); f.finish();

    Fixture partial; partial.establish(); token=partial.ask(); b=data_frame(partial.peer,1,reply(token));
    uint32_t tail=partial.io.read32(FakeIO::desc+8);
    partial.io.inject(Bytes(b.begin(),b.begin()+8)); CHECK(partial.step(110).empty()); CHECK(partial.io.read32(FakeIO::desc+8)==tail);
    partial.io.inject(Bytes(b.begin()+8,b.begin()+24)); CHECK(partial.step(111).empty()); CHECK(partial.io.read32(FakeIO::desc+8)==tail);
    partial.io.inject(Bytes(b.begin()+24,b.end())); tx=partial.step(112); CHECK(tx.size()==2 && partial.link.result().apr_ready); partial.finish();

    for(unsigned scenario=0;scenario<5;++scenario) {
        Fixture bad; bad.establish(); token=bad.ask();
        if(scenario==0)bad.io.inject(data_frame(bad.peer,1,Bytes(513,0)));
        if(scenario==1)bad.io.inject(data_frame(bad.peer,1,Bytes(510,0),3));
        if(scenario==2)bad.io.inject(data_frame(bad.peer,1,Bytes(8,0),0,12));
        if(scenario==3) { bad.io.inject(data_frame(bad.peer,1,Bytes(8,0),16)); bad.step(110); bad.io.inject(data_frame(bad.peer,1,Bytes(8,0),0,12)); }
        if(scenario==4)bad.io.inject(data_frame(bad.peer,21,reply(token)));
        bad.step(111); CHECK(bad.link.done() && bad.link.result().broken && !bad.link.result().apr_ready);
    }
}
static void states_basic_and_peer_intents() {
    for(unsigned reuse=0;reuse<2;++reuse) {
        Fixture f; f.establish(); uint32_t first=f.ask();
        f.io.inject(data_frame(f.peer,1,reply(first,0))); auto tx=f.step(110);
        CHECK(tx.size()==1 && !f.link.result().apr_ready && f.link.result().apr_response && f.link.result().apr_state==0);
        f.io.inject(frame(reuse?14:6,f.peer,f.peer_iid)); tx=f.step(160);
        CHECK(tx.size()==1);
        if(reuse)CHECK(u16(tx[0],0)==9 && u32(tx[0],4)==f.peer_iid);
        else { CHECK(tx[0]==frame(7,2,20)); f.io.inject(intent_frame(f.peer,123,20)); tx=f.step(161); CHECK(tx.size()==1 && u32(tx[0],4)==123); }
        uint32_t second=f.link.result().token; CHECK(second!=first);
        f.io.inject(data_frame(f.peer,2,reply(first))); f.step(170); CHECK(!f.link.result().apr_ready);
        f.io.inject(data_frame(f.peer,2,reply(second))); f.step(171); CHECK(f.link.result().apr_ready); f.finish(180);
    }
    for(uint32_t status:{0u,2u}) {
        Fixture f; f.establish(); uint32_t token=f.ask();
        f.io.inject(data_frame(f.peer,1,basic_reply(token,status))); auto tx=f.step(110);
        CHECK(tx.size()==1 && f.link.result().basic_responses==1 && f.link.result().basic_status==status);
        CHECK(!f.link.result().apr_response && !f.link.result().apr_ready);
        f.io.inject(frame(14,f.peer,f.peer_iid)); tx=f.step(160); CHECK(tx.size()==1 && u16(tx[0],0)==9);
        CHECK(f.link.result().token!=token); f.io.inject(data_frame(f.peer,2,reply(f.link.result().token)));
        f.step(170); CHECK(f.link.result().apr_ready); f.finish(180);
    }
}
static void zero_peer_intent_lifecycle() {
    for(bool reuse:{true,false}) {
        Fixture f; f.establish(); f.peer_iid=0;
        CHECK(f.link.result().peer_intents==0);
        // The peer's ID is not our local pool index: peer 0 is a valid
        // advertised receive buffer while our receive IDs remain 1..20.
        f.io.inject(intent_frame(f.peer,0,512));
        CHECK(f.step(99).empty()); CHECK(!f.link.result().broken && !f.link.result().apr_sent);
        CHECK(f.link.result().peer_intents==1 && f.link.result().last_peer_iid==0 &&
              f.link.result().last_peer_size==512 && f.link.result().intent_invalid_reason==NabuAdspGlink::IntentValid);
        auto tx=f.step(100); CHECK(tx.size()==1);
        CHECK(u16(tx[0],0)==9 && u16(tx[0],2)==2 && u32(tx[0],4)==0);
        uint32_t first=f.link.result().token; CHECK(first!=0 && f.link.result().queries==1);
        f.io.inject(data_frame(f.peer,1,reply(first,0))); tx=f.step(110);
        CHECK(tx.size()==1 && tx[0]==frame(14,2,1));
        CHECK(f.link.result().apr_response && !f.link.result().apr_ready);
        if(reuse) {
            // A completion on the local CID must not release the peer's IID 0.
            f.io.inject(frame(14,2,0)); tx=f.step(160);
            CHECK(tx.size()==1 && tx[0]==frame(7,2,20) && f.link.result().queries==1);
            f.io.inject(frame(14,f.peer,0)); tx=f.step(161);
        } else {
            f.io.inject(frame(6,f.peer,0)); tx=f.step(160);
            CHECK(tx.size()==1 && tx[0]==frame(7,2,20) && f.link.result().queries==1);
            // RX_DONE retired it; a late reuse event cannot recreate an intent.
            f.io.inject(frame(14,f.peer,0)); CHECK(f.step(161).empty());
            CHECK(f.link.result().queries==1);
            f.io.inject(intent_frame(f.peer,0,512)); tx=f.step(162);
        }
        CHECK(tx.size()==1 && u16(tx[0],0)==9 && u16(tx[0],2)==2 && u32(tx[0],4)==0);
        CHECK(f.link.result().peer_intents==(reuse?1u:2u));
        uint32_t second=f.link.result().token; CHECK(second!=first && f.link.result().queries==2);
        f.io.inject(data_frame(f.peer,20,reply(second))); tx=f.step(170);
        CHECK(tx.size()==2 && tx[0]==frame(14,2,20) && tx[1]==frame(3,2,0));
        CHECK(f.link.result().apr_ready && !f.link.result().broken); f.finish(180);
    }
    Fixture local_zero; local_zero.establish(); local_zero.peer_iid=0;
    auto token=local_zero.ask(); local_zero.io.inject(data_frame(local_zero.peer,0,reply(token)));
    local_zero.step(110); CHECK(local_zero.link.done() && local_zero.link.result().error==NabuAdspGlink::InvalidFrame);
    CHECK(!local_zero.link.result().apr_ready);
    Fixture empty; empty.establish(); empty.io.inject(intent_frame(empty.peer,0,0)); empty.step(99);
    CHECK(empty.link.result().error==NabuAdspGlink::InvalidFrame && empty.link.result().peer_intents==1);
    CHECK(empty.link.result().last_peer_iid==0 && empty.link.result().last_peer_size==0 &&
          empty.link.result().intent_invalid_reason==NabuAdspGlink::IntentZeroSize);
}
static void many_peer_intents() {
    for(bool batched:{false,true}) {
        Fixture f(4096,4088); f.establish();
        // The real DSP advertised IID 0..64 before our initial query. Keep
        // receiving beyond that point, including a single multi-pair frame.
        Bytes pairs;
        for(unsigned i=0;i<160;++i) {
            if(batched) {
                size_t p=pairs.size(); pairs.resize(p+8); put32(pairs,p,512); put32(pairs,p+4,i);
            } else {
                f.io.inject(intent_frame(f.peer,i)); CHECK(f.step(1).empty());
                CHECK(!f.link.result().broken);
            }
        }
        if(batched) { f.io.inject(frame(5,f.peer,160,pairs)); CHECK(f.step(1).empty()); }
        CHECK(!f.link.result().broken && !f.link.result().apr_sent && f.link.result().peer_intents==160);
        CHECK(f.io.read32(FakeIO::desc+8)==f.io.read32(FakeIO::desc+12));
        auto tx=f.step(100); CHECK(tx.size()==1 && u16(tx[0],0)==9 && u32(tx[0],4)==0);
        auto token=f.link.result().token;
        f.io.inject(data_frame(f.peer,1,reply(token))); tx=f.step(110);
        CHECK(tx.size()==2 && f.link.result().apr_ready && !f.link.result().broken); f.finish();
    }
    // A full cache of buffers too small for GET_STATE must admit a usable one.
    Fixture small; small.establish();
    for(unsigned i=0;i<64;++i) { small.io.inject(intent_frame(small.peer,i,8)); small.step(1); }
    small.io.inject(intent_frame(small.peer,0x12345678,20)); auto tx=small.step(100);
    CHECK(tx.size()==1 && u16(tx[0],0)==9 && u32(tx[0],4)==0x12345678);
    small.io.inject(data_frame(small.peer,1,reply(small.link.result().token))); small.step(110); small.finish();

    for(bool reuse:{false,true}) {
        Fixture f; f.establish();
        for(unsigned i=0;i<64;++i) { f.io.inject(intent_frame(f.peer,i)); f.step(1); }
        tx=f.step(100); CHECK(tx.size()==1 && u32(tx[0],4)==0);
        auto first=f.link.result().token;
        // More advertisements and a repeated busy IID must not release IID 0.
        f.io.inject(intent_frame(f.peer,0));
        for(unsigned i=64;i<96;++i) f.io.inject(intent_frame(f.peer,i));
        f.io.inject(data_frame(f.peer,1,reply(first,0))); f.step(110);
        tx=f.step(160); CHECK(tx.size()==1 && u16(tx[0],0)==9 && u32(tx[0],4)==1);
        auto second=f.link.result().token;
        f.io.inject(frame(reuse?14:6,f.peer,0));
        f.io.inject(data_frame(f.peer,1,reply(second,0))); f.step(170);
        tx=f.step(220); CHECK(tx.size()==1 && u16(tx[0],0)==9 && u32(tx[0],4)==(reuse?0u:2u));
        f.io.inject(data_frame(f.peer,1,reply(f.link.result().token))); f.step(230);
        CHECK(f.link.result().apr_ready && !f.link.result().broken); f.finish(240);
    }
    // With one suitable buffer in flight, admit a new suitable advertisement
    // by replacing an unused undersized entry, never the busy buffer.
    Fixture busy; busy.establish(); busy.peer_iid=0; auto first=busy.ask();
    for(unsigned i=1;i<64;++i) { busy.io.inject(intent_frame(busy.peer,i,8)); busy.step(101); }
    busy.io.inject(intent_frame(busy.peer,999,20));
    busy.io.inject(data_frame(busy.peer,1,reply(first,0))); busy.step(110);
    tx=busy.step(160); CHECK(tx.size()==1 && u16(tx[0],0)==9 && u32(tx[0],4)==999);
    busy.io.inject(frame(14,busy.peer,0));
    busy.io.inject(data_frame(busy.peer,1,reply(busy.link.result().token,0))); busy.step(170);
    tx=busy.step(220); CHECK(tx.size()==1 && u16(tx[0],0)==9 && u32(tx[0],4)==0);
    busy.io.inject(data_frame(busy.peer,1,reply(busy.link.result().token))); busy.step(230); busy.finish(240);
}
static uint32_t start_version_query(Fixture &f) {
    f.establish(); auto ready_token=f.ask();
    f.io.inject(frame(14,f.peer,f.peer_iid));
    f.io.inject(data_frame(f.peer,1,extended_reply(ready_token)));
    auto tx=f.step(110); CHECK(tx.size()==2 && tx[0]==frame(14,2,1));
    const auto &q=tx[1]; CHECK(u16(q,0)==9 && u16(q,2)==2 && u32(q,4)==f.peer_iid);
    CHECK(u32(q,8)==20 && u32(q,12)==0 && u16(q,16)==0x250 && u32(q,32)==0x1292c);
    auto version_token=u32(q,28); CHECK(version_token!=ready_token);
    CHECK(f.link.result().apr_ready && f.link.result().token==ready_token && f.link.result().apr_field==0x81);
    CHECK(f.link.result().version_sent && f.link.result().version_token==version_token && !f.link.result().close_sent);
    return version_token;
}
static void framework_versions() {
    for(unsigned count:{0u,3u,25u}) {
        Fixture f(4096,4088,true); auto token=start_version_query(f);
        auto packet=version_reply(token,count);
        // Preserve matching rules during the second command: stale ready
        // and version tokens, wrong endpoints/opcodes cannot satisfy it.
        auto wrong=version_reply(f.link.result().token,count);
        f.io.inject(data_frame(f.peer,1,wrong)); f.step(111);
        wrong=packet; wrong[4]=7; f.io.inject(data_frame(f.peer,1,wrong)); f.step(112);
        wrong=extended_reply(token); f.io.inject(data_frame(f.peer,1,wrong)); f.step(113);
        wrong=basic_reply(token,0,0x1290c); f.io.inject(data_frame(f.peer,1,wrong)); f.step(114);
        CHECK(!f.link.result().version_response && !f.link.result().version_basic_response);
        CHECK(f.link.result().apr_ready && f.link.result().apr_ignored==4);
        size_t split=std::min(size_t(64),packet.size());
        f.io.inject(data_frame(f.peer,20,Bytes(packet.begin(),packet.begin()+split),packet.size()-split));
        // Small count zero uses one frame; the others cross a GLINK fragment.
        if(packet.size()>64) {
            CHECK(f.step(120).empty() && !f.link.result().version_response);
            f.io.inject(data_frame(f.peer,20,Bytes(packet.begin()+64,packet.end()),0,12));
        }
        auto tx=f.step(121); CHECK(tx.size()==2 && tx.back()==frame(3,2,0));
        const auto &r=f.link.result(); CHECK(r.apr_ready && r.apr_state==1 && r.queries==1);
        CHECK(r.version_response && r.service_count==count && r.version_field==0x81 && r.version_type==0);
        for(unsigned i=0;i<4;++i)CHECK(r.build_version[i]==10+i);
        for(unsigned i=0;i<count;++i)CHECK(r.services[i].id==(i==0?4u:i==1?7u:i==2?8u:0x100+i) && r.services[i].api==2+i && r.services[i].branch==5+i);
        CHECK(!r.version_timeout && !r.version_invalid); f.finish(130);
    }
    for(unsigned scenario=0;scenario<3;++scenario) {
        Fixture f(4096,0,true); auto token=start_version_query(f); auto packet=version_reply(token);
        if(scenario==0)packet.resize(48);
        if(scenario==1)put32(packet,48,26);
        if(scenario==2)packet.resize(packet.size()-1);
        put16(packet,2,packet.size()); f.io.inject(data_frame(f.peer,1,packet)); auto tx=f.step(120);
        CHECK(tx.size()==2 && f.link.result().version_invalid==scenario+1 && !f.link.result().version_response);
        CHECK(f.link.result().apr_ready && !f.link.result().broken); f.finish(130);
    }
    for(unsigned status:{0u,3u}) {
        Fixture f(4096,0,true); auto token=start_version_query(f);
        f.io.inject(data_frame(f.peer,1,basic_reply(token,status,0x1292c))); auto tx=f.step(120);
        CHECK(tx.size()==2 && f.link.result().version_basic_response && f.link.result().version_status==status);
        CHECK(f.link.result().apr_ready && !f.link.result().version_response && !f.link.result().basic_responses); f.finish(130);
    }
    Fixture silent(4096,0,true); start_version_query(silent);
    CHECK(silent.step(609).empty()); auto tx=silent.step(610);
    CHECK(tx.size()==1 && tx[0]==frame(3,2,0)); CHECK(silent.link.result().apr_ready && silent.link.result().version_timeout);
    CHECK(!silent.link.result().version_response); silent.finish(620);
    Fixture no_buffer(4096,0,true); no_buffer.establish(); auto token=no_buffer.ask();
    no_buffer.io.inject(data_frame(no_buffer.peer,1,extended_reply(token))); tx=no_buffer.step(110);
    CHECK(tx.size()==2 && tx[1]==frame(7,2,20) && !no_buffer.link.result().version_sent);
    no_buffer.step(1110); CHECK(no_buffer.link.result().version_timeout && no_buffer.link.result().apr_ready); no_buffer.finish(1120);
}
static Bytes asm_map_reply(uint32_t token,uint32_t handle=0x1234) {
    auto packet=extended_reply(token,handle);packet[4]=packet[8]=7;put32(packet,16,0x10d93);return packet;
}
static Bytes asm_basic(uint32_t token,uint32_t status,uint32_t opcode) {
    auto packet=basic_reply(token,status,opcode);packet[4]=packet[8]=7;return packet;
}
static uint32_t start_mapping(Fixture &f) {
    auto version_token=start_version_query(f);auto packet=version_reply(version_token);
    put32(packet,68,2); // Actual Nabu ASM API2.
    f.io.inject(frame(14,f.peer,f.peer_iid));f.io.inject(data_frame(f.peer,1,packet));
    auto tx=f.step(120);CHECK(tx.size()==2&&tx[0]==frame(14,2,1));const auto &map=tx[1];
    CHECK(u16(map,0)==9&&u32(map,4)==f.peer_iid&&u32(map,8)==40&&map.size()==56);
    CHECK(map[20]==7&&map[21]==5&&map[24]==7&&map[25]==4&&u32(map,32)==0x10d92);
    CHECK(u16(map,36)==3&&u16(map,38)==1&&u32(map,40)==0);
    CHECK(u32(map,44)==0x10000000&&u32(map,48)==1&&u32(map,52)==16384);
    CHECK(f.link.result().map_sent&&!f.link.result().map_response&&f.link.result().apr_ready);
    return u32(map,28);
}
static void memory_mapping() {
    for(unsigned unmap_status:{0u,5u}) {
        Fixture f(4096,4088,true,true);auto token=start_mapping(f);
        auto wrong=asm_map_reply(token);wrong[4]=3;f.io.inject(data_frame(f.peer,1,wrong));f.step(121);
        f.io.inject(data_frame(f.peer,1,asm_map_reply(token-1)));f.step(122);
        f.io.inject(data_frame(f.peer,1,asm_map_reply(token,0)));f.step(123);
        CHECK(!f.link.result().map_response&&f.link.result().apr_ignored==3);
        f.io.inject(data_frame(f.peer,1,asm_basic(token,0,0x10d92)));auto tx=f.step(130);
        CHECK(tx.size()==1&&f.link.result().map_basic_response&&!f.link.result().map_response&&!f.link.result().close_sent);
        f.io.inject(frame(14,f.peer,f.peer_iid));f.io.inject(data_frame(f.peer,1,asm_map_reply(token)));
        tx=f.step(140);CHECK(tx.size()==2);const auto &unmap=tx[1];
        CHECK(u16(unmap,0)==9&&u32(unmap,8)==24&&unmap.size()==40&&u32(unmap,32)==0x10d94&&u32(unmap,36)==0x1234);
        auto ut=u32(unmap,28);CHECK(ut!=token&&f.link.result().map_response&&f.link.result().map_handle==0x1234);
        f.io.inject(data_frame(f.peer,1,asm_basic(token,0,0x10d94)));f.step(141);CHECK(!f.link.result().unmap_response);
        f.io.inject(data_frame(f.peer,1,asm_basic(ut,unmap_status,0x10d94)));tx=f.step(150);
        CHECK(tx.size()==2&&f.link.result().unmap_response&&f.link.result().unmap_status==unmap_status);
        CHECK(f.link.result().apr_ready&&f.link.result().version_response);f.finish(160);
    }
    {Fixture f(4096,0,true,true);auto token=start_mapping(f);
        f.io.inject(data_frame(f.peer,1,asm_basic(token,3,0x10d92)));auto tx=f.step(130);
        CHECK(tx.size()==2&&f.link.result().map_status==3&&!f.link.result().map_response&&!f.link.result().unmap_sent);f.finish(140);}
    {Fixture f(4096,0,true,true);start_mapping(f);auto tx=f.step(1120);
        CHECK(tx.size()==1&&f.link.result().map_timeout&&!f.link.result().unmap_sent);f.finish(1130);}
    {Fixture f(4096,0,true,true);auto token=start_mapping(f);
        f.io.inject(frame(14,f.peer,f.peer_iid));f.io.inject(data_frame(f.peer,1,asm_map_reply(token)));f.step(140);
        auto tx=f.step(1140);CHECK(tx.size()==1&&f.link.result().map_response&&f.link.result().unmap_timeout&&!f.link.result().unmap_response);f.finish(1150);}
    {Fixture f(4096,0,true,true);auto token=start_version_query(f);
        f.io.inject(data_frame(f.peer,1,version_reply(token)));auto tx=f.step(120); // ASM API3 is not this validated contract.
        CHECK(tx.size()==2&&!f.link.result().map_sent&&f.link.result().version_response);f.finish(130);}
}
static void timeouts_close_and_failure() {
    Fixture no_peer; CHECK(no_peer.step(4999).empty() && !no_peer.link.done());
    CHECK(no_peer.step(5000).empty() && no_peer.link.done() && no_peer.link.result().timeout);
    Fixture half; half.io.inject(frame(1,1,1)); half.step(0);
    auto tx=half.step(5000); CHECK(tx.size()==1 && tx[0]==frame(3,2,0)); CHECK(!half.link.done());
    CHECK(half.step(5999).empty() && !half.link.done()); half.step(6000); CHECK(half.link.done());

    Fixture unavailable; unavailable.establish(); tx=unavailable.step(100); CHECK(tx.size()==1 && tx[0]==frame(7,2,20));
    unavailable.io.inject(frame(8,2,0)); CHECK(unavailable.step(101).empty() && !unavailable.link.result().close_sent);
    unavailable.io.inject(frame(8,unavailable.peer,0)); tx=unavailable.step(102);
    CHECK(tx.size()==1 && tx[0]==frame(3,2,0) && unavailable.link.result().error==NabuAdspGlink::IntentUnavailable);
    unavailable.finish();

    Fixture silent; silent.establish(); silent.ask();
    CHECK(silent.step(599).empty()); CHECK(silent.step(600).empty());
    tx=silent.step(650); CHECK(tx.size()==1 && tx[0]==frame(7,2,20));
    tx=silent.step(3000); CHECK(tx.size()==1 && tx[0]==frame(3,2,0) && silent.link.result().timeout);
    silent.step(3999); CHECK(!silent.link.done()); silent.step(4000); CHECK(silent.link.done() && !silent.link.result().apr_ready);

    Fixture remote_close; remote_close.establish(); remote_close.io.inject(frame(3,remote_close.peer,0));
    tx=remote_close.step(10); CHECK(tx.size()==2 && tx[0]==frame(11,remote_close.peer,0) && tx[1]==frame(3,2,0));
    remote_close.io.inject(frame(11,2,0)); remote_close.step(11); CHECK(remote_close.link.done() && remote_close.link.result().remote_closed);
    Fixture aborted; aborted.link.abort(); CHECK(aborted.link.done() && aborted.link.result().error==NabuAdspGlink::Aborted);
    auto writes=aborted.io.writes; aborted.step(10000); CHECK(aborted.io.writes==writes);

    Fixture pointer; pointer.io.peer_word(FakeIO::desc+12,4096); pointer.step(1);
    CHECK(pointer.link.done() && pointer.link.result().error==NabuAdspGlink::InvalidPointer);
    Fixture malformed; malformed.io.inject(frame(5,37,0xffffffff)); malformed.step(1);
    CHECK(malformed.link.done() && malformed.link.result().error==NabuAdspGlink::InvalidFrame);
    Fixture unknown; unknown.io.inject(frame(10,1,0)); unknown.step(1);
    CHECK(unknown.link.done() && unknown.link.result().error==NabuAdspGlink::UnknownCommand);
    Fixture notify; auto bells=notify.io.bells; notify.io.inject(frame(13,0,0)); CHECK(notify.step(1).empty()); CHECK(notify.io.bells==bells+1);
}
static void tx_capacity_and_work_budget() {
    // Complete OPEN while only 64 TX bytes are free: its ACK fits, the full
    // intent advertisement does not. The failure must not re-enter Querying.
    Fixture full(256); full.io.inject(frame(1,1,1)); full.step(0);
    full.io.inject(open_frame(full.peer)); full.io.inject(frame(4,2,0));
    uint32_t head=full.io.read32(FakeIO::desc+4);
    full.io.peer_word(FakeIO::desc,(head+64)%full.io.size);
    full.link.step(1);
    CHECK(full.link.done() && full.link.result().broken && full.link.result().error==NabuAdspGlink::TxFull);
    CHECK(!full.link.result().apr_sent); auto writes=full.io.writes;
    full.link.step(10000); CHECK(full.io.writes==writes);

    Fixture budget;
    for(unsigned i=0;i<65;++i)budget.io.inject(frame(15,99,i));
    CHECK(budget.step(1).empty() && budget.link.result().rx==64);
    CHECK((budget.io.read32(FakeIO::desc+12)+budget.io.size-budget.io.read32(FakeIO::desc+8))%budget.io.size==8);
    CHECK(budget.step(2).empty() && budget.link.result().rx==65);
    CHECK(budget.io.read32(FakeIO::desc+12)==budget.io.read32(FakeIO::desc+8));
}
int main() {
    success_and_wrap(); negotiation_and_channels(); identity_and_lengths();
    fragments_and_partial_frames(); states_basic_and_peer_intents(); zero_peer_intent_lifecycle();
    many_peer_intents(); framework_versions(); memory_mapping(); timeouts_close_and_failure(); tx_capacity_and_work_budget();
    std::printf("PASS: production GLINK/APR; %u assertions; ring, CID/IID, state, deadline and close cases\n",checks);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    harness = args.output / "adsp-glink-harness.cpp"
    harness.write_text(HARNESS, encoding="utf-8")
    binary = args.output / "adsp-glink-harness"
    command = ["clang++", "-std=c++17", "-O1", "-g", "-fsanitize=address,undefined",
               "-fno-omit-frame-pointer", "-Wall", "-Wextra", "-Werror",
               "-I" + host_path(ROOT / "patches/nabu-audio"), host_path(harness), "-o", host_path(binary)]
    run(host_command(command))
    result = run(host_command([host_path(binary)]))
    report = {"status": "passed", "production_source": "patches/nabu-audio/NabuAdspGlink.h",
              "fixture": "actual Link<FakeIO>; only shared-memory, peer wire input, doorbells and elapsed time are simulated",
              "host_result": result.strip(), "sanitizers": ["address", "undefined"],
              "coverage": ["bidirectional CID/IID", "VERSION feature negotiation", "Nabu DT 20x512 intents",
                           "exact APR request", "endpoint/token/length isolation", "raw GET_STATE including non-one",
                           "basic error separation", "wrap and fragments", "RX_DONE and reuse", "timeouts and close",
                           "peer IID 0 transmit/reuse/retirement and local IID 0 rejection",
                           "160 peer intents before first query, individually and batched across wrap",
                           "full intent cache consumes surplus, admits usable sizes and preserves busy IDs",
                           "actual field 0x81 extended-header readiness, CORE framework-version request/reply",
                           "0/3/25 service entries, fragments, malformed counts/lengths, stale token isolation",
                           "version unsupported/basic/timeout preserves proven readiness and closes",
                           "exact ASM2 map/unmap tagged IOVA bytes and handle, basic success without handle, endpoint/token isolation",
                           "map refusal, map/unmap timeout, unmap error and unsupported ASM API stay distinct",
                           "TX exhaustion stays finished", "64-frame per-step budget"],
              "device_executed": False, "pcm_or_sound_verified": False}
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
