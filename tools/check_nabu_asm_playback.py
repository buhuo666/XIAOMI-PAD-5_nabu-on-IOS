#!/usr/bin/env python3
"""Check real ADM/ASM playback encoders, period ownership, EOS and close sequence."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]


def run(command):
    result=subprocess.run(command,capture_output=True,text=True,encoding="utf-8",errors="replace")
    if result.returncode:
        raise RuntimeError(f"{command!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout


HARNESS=r'''
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "NabuAsmPlayback.h"
#include "nabu_playback_vendor_wire.h"
namespace V=NabuPlaybackVendorFixture;
using Bytes=std::vector<uint8_t>;
static unsigned checks;
#define CHECK(x) do{if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::abort();}++checks;}while(0)
static uint16_t u16(const Bytes&b,size_t p){return b.at(p)|uint16_t(b.at(p+1))<<8;}
static uint32_t u32(const Bytes&b,size_t p){return u16(b,p)|uint32_t(u16(b,p+2))<<16;}
static void w16(Bytes&b,size_t p,uint16_t n){b.at(p)=n;b.at(p+1)=n>>8;}
static void w32(Bytes&b,size_t p,uint32_t n){w16(b,p,n);w16(b,p+2,n>>16);}
template<class T>static Bytes raw(const T&v){auto*p=reinterpret_cast<const uint8_t*>(&v);return Bytes(p,p+sizeof(v));}
template<class T>static Bytes payload(const T&v){auto p=raw(v);p.erase(p.begin(),p.begin()+20);return p;}
struct Packet{uint8_t service;uint16_t port;uint32_t opcode,token;Bytes data;};
struct Fill{unsigned period;uint32_t first,frames;};
struct IO{
    bool accept=true;uint32_t busy=0;std::vector<Packet> sent;std::vector<Fill> fills;
    void playback_fill(unsigned period,uint32_t first,uint32_t frames){
        CHECK(period<4&&!(busy&(1u<<period))&&frames==1024);fills.push_back({period,first,frames});
    }
    bool playback_send(uint8_t svc,uint16_t port,uint32_t op,uint32_t token,const uint8_t*p,uint32_t n){
        if(!accept)return false;CHECK(n<=32);sent.push_back({svc,port,op,token,Bytes(p,p+n)});
        if(op==0x10dab){unsigned index=(u32(sent.back().data,0)-0x10000000)/4096;
            CHECK(index<4&&!(busy&(1u<<index)));busy|=1u<<index;}
        return true;
    }
};
static Packet expected(unsigned stage,uint16_t copp=2){
    switch(stage){
    case 0:{V::adm_cmd_device_open_v5 v{};v.mode_of_operation=1;v.endpoint_id_1=0x9030;v.endpoint_id_2=0xffff;
        v.topology_id=0x10312;v.dev_num_channel=2;v.bit_width=24;v.sample_rate=48000;
        v.dev_channel_mapping[0]=1;v.dev_channel_mapping[1]=2;return{8,0x9030,0x10326,0,payload(v)};}
    case 1:{V::asm_stream_cmd_open_write_v3 v{};v.bits_per_sample=16;v.postprocopo_id=0x10c68;v.dec_fmt_id=0x10da5;
        return{7,0x101,0x10db3,0,payload(v)};}
    case 2:{V::adm_cmd_matrix_map_routings_v5 v{};v.matrix_id=0;v.num_sessions=1;Bytes p=payload(v);
        auto n=raw(V::adm_session_map_node_v5{1,1});p.insert(p.end(),n.begin(),n.end());p.resize(16);w16(p,12,copp);
        return{8,0,0x10325,0,p};}
    case 3:{V::asm_multi_channel_pcm_fmt_blk_v2 v{};v.fmt_blk.fmt_blk_size=20;v.num_channels=2;v.bits_per_sample=16;
        v.sample_rate=48000;v.is_signed=1;v.channel_mapping[0]=1;v.channel_mapping[1]=2;return{7,0x101,0x10d98,0,payload(v)};}
    case 4:{V::asm_session_cmd_run_v2 v{};return{7,0x101,0x10daa,0,payload(v)};}
    case 5:return{7,0x101,0x10bdb,0,{}};
    case 6:return{7,0x101,0x10bcd,0,{}};
    case 7:return{8,copp,0x10327,0,{}};
    default:std::abort();
    }
}
static Bytes response(const Packet&q,uint32_t opcode,const Bytes&p,bool ext=true){
    uint32_t h=ext?32:20;Bytes b(h,0);w16(b,0,ext?0x81:0x150);w16(b,2,h+p.size());
    b[4]=q.service;b[5]=4;w16(b,6,q.port);b[8]=q.service;b[9]=5;w16(b,10,q.port);
    w32(b,12,q.token);w32(b,16,opcode);b.insert(b.end(),p.begin(),p.end());return b;
}
struct Fixture{
    IO io;NabuAsmPlayback::Trial<IO> trial{io};uint32_t now=0;size_t consumed=0;
    Fixture(){trial.begin(0x110000000ULL,0x6a,now);}
    void receive(const Bytes&b){trial.receive(b.data(),b.size(),now);}
    Packet take(unsigned stage){trial.step(now);CHECK(io.sent.size()==consumed+1);auto q=io.sent.at(consumed++),e=expected(stage);
        CHECK(q.service==e.service&&q.port==e.port&&q.opcode==e.opcode&&q.data==e.data);return q;}
    void basic(const Packet&q,uint32_t status=0){Bytes p(8);w32(p,0,q.opcode);w32(p,4,status);receive(response(q,0x110e8,p));}
    void pass(unsigned stage){auto q=take(stage);if(stage==0){receive(response(q,0x10329,raw(V::adm_cmd_rsp_device_open_v5{0,2,0})));}
        else basic(q);++now;}
    void startup(){for(unsigned i=0;i<5;++i)pass(i);CHECK(trial.ready());CHECK(io.sent.size()==5);}
    std::vector<Packet> writes(){trial.step(now);std::vector<Packet> out;
        while(consumed<io.sent.size()){auto q=io.sent.at(consumed++);CHECK(q.opcode==0x10dab&&q.service==7&&q.port==0x101);
            unsigned index=(u32(q.data,0)-0x10000000)/4096;uint32_t seq=q.token&0x7fffffff;
            V::asm_data_cmd_write_v2 v{};v.buf_addr_lsw=0x10000000+index*4096;v.buf_addr_msw=1;
            v.mem_map_handle=0x6a;v.buf_size=4096;v.seq_id=seq;CHECK(q.data==payload(v));
            CHECK(io.fills.at(seq-1).period==index&&io.fills.at(seq-1).first==(seq-1)*1024);out.push_back(q);}
        return out;}
    Bytes done_event(const Packet&q,uint32_t status=0){return response(q,0x10d99,raw(V::asm_data_event_write_done_v2{
        u32(q.data,0),u32(q.data,4),0x6a,status}));}
    void complete(const Packet&q){unsigned i=(u32(q.data,0)-0x10000000)/4096;io.busy&=~(1u<<i);receive(done_event(q));}
    void close(){pass(6);pass(7);CHECK(trial.done());CHECK(trial.result().closed&&trial.result().copp_closed);}
};
static void wire_and_recycle(bool rendered_first){
    static_assert(sizeof(V::adm_cmd_device_open_v5)==48);static_assert(sizeof(V::asm_stream_cmd_open_write_v3)==36);
    static_assert(sizeof(V::asm_multi_channel_pcm_fmt_blk_v2)==44);static_assert(sizeof(V::asm_data_cmd_write_v2)==52);
    Fixture f;f.startup();f.now+=90000;f.trial.step(f.now);CHECK(f.trial.ready()&&f.io.sent.size()==5);
    f.trial.play();auto pending=f.writes();CHECK(pending.size()==4&&f.trial.result().pending_mask==15);
    // Basic success does not return a data period. Neither does wrong address.
    f.basic(pending[2]);auto bad=f.done_event(pending[2]);w32(bad,32,0x10000000);f.receive(bad);
    CHECK(f.trial.result().completions==0);CHECK(f.writes().empty());
    f.complete(pending[2]);CHECK(f.trial.result().pending_mask==11);auto refill=f.writes();CHECK(refill.size()==1);
    CHECK(u32(refill[0].data,0)==0x10002000);auto old=pending[2];pending[2]=refill[0];f.receive(f.done_event(old));
    CHECK(f.trial.result().completions==1);CHECK(f.writes().empty());
    // Recycle returned periods in a different order from their addresses.
    unsigned at=1;
    while(f.trial.result().writes<141){at=(at+1)%pending.size();auto q=pending.at(at);pending.erase(pending.begin()+at);
        f.now+=21;f.complete(q);auto tx=f.writes();CHECK(tx.size()==1);pending.insert(pending.end(),tx.begin(),tx.end());}
    CHECK(f.trial.result().writes==141&&pending.size()==4);
    auto eos=f.take(5);f.basic(eos);CHECK(f.trial.result().eos_acked&&!f.trial.result().rendered);
    Packet event=eos;event.token=0;auto rendered=response(event,0x10c1c,{});
    if(rendered_first)f.receive(rendered);
    f.trial.step(f.now);CHECK(!f.trial.result().close_sent);
    for(auto&q:pending){f.now+=21;f.complete(q);}
    CHECK(f.trial.result().completions==141&&f.trial.result().pending_mask==0);
    if(!rendered_first){f.trial.step(f.now);CHECK(!f.trial.result().close_sent);f.receive(rendered);}
    f.trial.step(f.now);f.close();const auto&r=f.trial.result();
    CHECK(!r.failed&&!r.mapping_retained&&r.bytes_sent==577536&&r.bytes_completed==577536&&r.eos_event_token==0);
    CHECK(f.io.fills.size()==141&&f.io.busy==0);
    for(const auto&q:f.io.sent)CHECK(q.opcode!=0x10d94); // mapping belongs to the root lifetime
}
static void necessary_close_paths(){
    // A failed format still closes the opened stream and actual COPP.
    Fixture format;format.pass(0);format.pass(1);format.pass(2);auto q=format.take(3);format.basic(q,7);format.close();
    CHECK(format.trial.result().failed&&!format.trial.result().mapping_retained);
    // An early finish drains only the four periods really queued.
    Fixture early;early.startup();early.trial.play();auto p=early.writes();early.trial.finish();auto eos=early.take(5);
    for(auto&w:p)early.complete(w);early.receive(response(eos,0x10c1c,{}));early.trial.step(early.now);early.close();
    CHECK(early.trial.result().writes==4&&early.trial.result().completions==4);
    // A close timeout retains the DMA mapping even if COPP close later succeeds.
    Fixture close;close.startup();close.trial.finish();close.take(6);close.now+=1000;close.trial.step(close.now);close.pass(7);
    CHECK(close.trial.done()&&!close.trial.result().closed&&close.trial.result().mapping_retained);
    // WRITE error isn't a successful completion and exits through actual CLOSE.
    Fixture write;write.startup();write.trial.play();auto queued=write.writes();write.receive(write.done_event(queued[0],9));write.close();
    CHECK(write.trial.result().failed&&write.trial.result().completions==0);
}
int main(){wire_and_recycle(false);wire_and_recycle(true);necessary_close_paths();
    std::printf("PASS: ADM/ASM production playback, %u assertions; vendor wire, 141 real completions and required close paths\n",checks);}
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    harness=args.output/"asm-playback-harness.cpp";harness.write_text(HARNESS,encoding="utf-8")
    binary=args.output/"asm-playback-harness"
    run(host_command(["clang++","-std=c++17","-O1","-g","-fsanitize=address,undefined",
        "-fno-omit-frame-pointer","-Wall","-Wextra","-Werror",
        "-I"+host_path(ROOT/"patches/nabu-audio"),"-I"+host_path(ROOT/"tools/fixtures"),
        host_path(harness),"-o",host_path(binary)]))
    result=run(host_command([host_path(binary)]))
    report={"status":"passed","host_result":result.strip(),"production_source":"patches/nabu-audio/NabuAsmPlayback.h",
        "vendor_fixture":"tools/fixtures/nabu_playback_vendor_wire.h",
        "vendor_revision":"d41f8e1a6827294af6a61adbe18544518e750166",
        "sanitizers":["address","undefined"],"coverage":["original ADM/ASM packet layouts",
            "four-slot ownership and out-of-order WRITE_DONE recycling","141 periods/577536 bytes",
            "EOS basic acknowledgement distinguished from rendered completion",
            "rendered-before/after-last-WRITE_DONE","early finish, write error and required stream/COPP close",
            "unconfirmed stream close retains mapping; unmap remains caller-owned"],
        "device_executed":False,"audible_output_verified":False}
    (args.output/"report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
