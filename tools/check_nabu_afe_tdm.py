#!/usr/bin/env python3
"""Check production AFE TDM wire packets and rollback with pinned vendor structs.

The fake transport replaces only APR I/O and time. No DSP or pins are touched.
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
#include <cstddef>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>
#include "NabuAfeTdm.h"
#include "nabu_afe_vendor_wire.h"
using Bytes=std::vector<uint8_t>;
namespace V=NabuAfeVendorFixture;
static unsigned checks;
#define CHECK(x) do {if(!(x)){std::fprintf(stderr,"line %d: %s\n",__LINE__,#x);std::abort();}++checks;}while(0)
static void w16(Bytes &b,size_t p,uint16_t n){b.at(p)=n;b.at(p+1)=n>>8;}
static void w32(Bytes &b,size_t p,uint32_t n){w16(b,p,n);w16(b,p+2,n>>16);}
template<class T> static Bytes raw(const T &v){const uint8_t *p=reinterpret_cast<const uint8_t *>(&v);return Bytes(p,p+sizeof(v));}
static void append(Bytes &a,const Bytes &b){a.insert(a.end(),b.begin(),b.end());}
struct Packet {uint32_t opcode,token;Bytes payload;};
struct IO {
    bool accept=true;unsigned rejected=0;std::vector<Packet> sent;
    bool afe_send(uint32_t opcode,uint32_t token,const uint8_t *p,uint32_t bytes){
        CHECK(bytes<=76);if(!accept){++rejected;return false;}
        sent.push_back({opcode,token,Bytes(p,p+bytes)});return true;
    }
};
// Prefix layout and data are taken independently from the original packed
// structs and DT, not from the production encoder's offsets or constants.
static Packet svc(uint32_t module,uint32_t param,const Bytes &data){
    V::afe_svc_cmd_set_param_v2 prefix{};prefix.payload_size=sizeof(V::param_hdr_v3)+data.size();
    V::param_hdr_v3 header{module,0,0,param,uint32_t(data.size())};
    Bytes p=raw(prefix);p.erase(p.begin(),p.begin()+sizeof(V::apr_hdr));append(p,raw(header));append(p,data);
    return {0x100fc,0,p};
}
static Packet port(uint32_t module,uint32_t param,const Bytes &data){
    V::afe_port_cmd_set_param_v3 prefix{};prefix.port_id=0x9030;
    prefix.payload_size=sizeof(V::param_hdr_v3)+data.size();
    V::param_hdr_v3 header{module,0,0,param,uint32_t(data.size())};
    Bytes p=raw(prefix);p.erase(p.begin(),p.begin()+sizeof(V::apr_hdr));append(p,raw(header));append(p,data);
    return {0x100fa,0,p};
}
static Packet expected(unsigned stage){
    switch(stage){
    case 0:return port(0x1020c,0x102b4,raw(V::afe_param_id_island_cfg_t{1,0}));
    case 1:case 9:return svc(0x1028f,0x10290,raw(V::afe_clk_set{1,0x206,12288000,4,0,stage==1?1u:0u}));
    case 2:return svc(0x10254,0x1029e,raw(V::afe_param_id_group_device_tdm_cfg{
        1,0x9130,0,{0x9030,0x9032,0xffff,0xffff,0xffff,0xffff,0xffff,0xffff},8,48000,32,8,32,0xff}));
    case 3:case 8:return svc(0x10254,0x10256,raw(V::afe_group_device_enable{0x9130,uint16_t(stage==3?1:0)}));
    case 4:return port(0x1020c,0x1029d,raw(V::afe_param_id_tdm_cfg{1,2,48000,24,0,1,1,8,0,1,1,32,3}));
    case 5:return port(0x1028a,0x10297,raw(V::afe_param_id_slot_mapping_cfg{1,2,24,0,{0,4,0xffff,0xffff,0xffff,0xffff,0xffff,0xffff}}));
    case 6:{V::afe_port_cmd_device_start x{};x.port_id=0x9030;Bytes p=raw(x);p.erase(p.begin(),p.begin()+20);return {0x100e5,0,p};}
    case 7:{V::afe_port_cmd_device_stop x{};x.port_id=0x9030;Bytes p=raw(x);p.erase(p.begin(),p.begin()+20);return {0x100e6,0,p};}
    default:std::abort();
    }
}
static Bytes response(const Packet &q,uint32_t status=0,bool extended=false){
    const uint32_t h=extended?32:20;Bytes b(h+8,0);
    w16(b,0,extended?0x81:0x150);w16(b,2,b.size());b[4]=4;b[5]=4;b[8]=4;b[9]=5;
    w32(b,12,q.token);w32(b,16,0x110e8);
    if(extended)std::fill(b.begin()+20,b.begin()+32,0xa5);
    w32(b,h,q.opcode);w32(b,h+4,status);return b;
}
struct Fixture {
    IO io;NabuAfeTdm::Trial<IO> trial{io};uint32_t now=0;size_t consumed=0;
    explicit Fixture(uint32_t start=0):now(start){trial.begin(now);}
    Packet take(unsigned stage){
        trial.step(now);CHECK(io.sent.size()==consumed+1);Packet q=io.sent.at(consumed++),e=expected(stage);
        CHECK(q.opcode==e.opcode);CHECK(q.payload==e.payload);CHECK(q.token==0x200+consumed-1);
        return q;
    }
    void reply(const Packet &q,uint32_t status=0,bool extended=false){Bytes b=response(q,status,extended);trial.receive(b.data(),b.size(),now);}
    void pass(unsigned stage,bool extended=false){auto q=take(stage);reply(q,0,extended);++now;}
    void startup(){for(unsigned i=0;i<7;++i)pass(i,(i&1)==1);CHECK(trial.ready());}
    void cleanup(bool started,bool group,bool clock){
        if(started)pass(7,true);if(group)pass(8);if(clock)pass(9,true);CHECK(trial.done());CHECK(!trial.ready());
    }
};
static void vendor_layouts(){
    static_assert(sizeof(V::apr_hdr)==20);static_assert(sizeof(V::param_hdr_v3)==16);
    static_assert(sizeof(V::afe_clk_set)==20);static_assert(sizeof(V::afe_param_id_group_device_tdm_cfg)==44);
    static_assert(sizeof(V::afe_param_id_tdm_cfg)==36);static_assert(sizeof(V::afe_param_id_slot_mapping_cfg)==28);
    static_assert(sizeof(V::afe_svc_cmd_set_param_v2)==36);static_assert(sizeof(V::afe_port_cmd_set_param_v3)==40);
    static_assert(offsetof(V::afe_svc_cmd_set_param_v2,payload_size)==32);
    static_assert(offsetof(V::afe_port_cmd_set_param_v3,payload_size)==36);
    uint16_t endian=1;CHECK(*reinterpret_cast<uint8_t *>(&endian)==1);
    // Explicit bytes independently pin the non-obvious clock attr, root and rate.
    const Bytes clock={0,0,0,0,0,0,0,0,0,0,0,0,36,0,0,0,
        0x8f,2,1,0,0,0,0,0,0x90,2,1,0,20,0,0,0,
        1,0,0,0,6,2,0,0,0,0x80,0xbb,0,4,0,0,0,1,0,0,0};
    CHECK(expected(1).payload==clock);CHECK(expected(2).payload.size()==76);
}
static void success_hold_wrap(){
    for(uint32_t start:{0u,0xfffffff0u}){
        Fixture f(start);f.startup();const auto &r=f.trial.result();
        CHECK(r.island_configured&&r.clock_on&&r.group_configured&&r.group_on&&r.port_configured&&r.slots_configured&&r.started);
        f.now+=90000;f.trial.step(f.now);CHECK(f.trial.ready());CHECK(f.io.sent.size()==7);CHECK(!r.timeout);
        f.trial.finish();CHECK(!f.trial.ready());auto stop=f.take(7);
        f.now+=999;f.trial.step(f.now);CHECK(f.io.sent.size()==8&&!f.trial.done());f.reply(stop,0,true);
        ++f.now;f.pass(8,true);f.pass(9);CHECK(f.trial.done());
        CHECK(r.stopped&&r.group_off&&r.clock_off&&!r.failed&&!r.cleanup_failed&&r.commands==10);
        f.trial.finish();f.trial.step(f.now+100000);CHECK(f.io.sent.size()==10);
    }
}
static void rejected_responses(){
    Fixture f;auto q=f.take(0);const Bytes good=response(q);
    // Corrupt one endpoint/token/opcode/original-command or length at a time.
    for(unsigned kind=0;kind<14;++kind){Bytes b=good;switch(kind){
        case 0:b[4]=7;break;case 1:b[5]=5;break;case 2:b[6]=1;break;
        case 3:b[8]=3;break;case 4:b[9]=4;break;case 5:b[10]=1;break;
        case 6:b[12]^=1;break;case 7:b[16]^=1;break;case 8:b[20]^=1;break;
        case 9:b.resize(19);break;case 10:b[0]=0x12;break;
        case 11:w16(b,2,40);break;case 12:w16(b,2,19);break;case 13:w16(b,2,27);break;
    }f.trial.receive(b.data(),b.size(),f.now);CHECK(!f.trial.result().island_configured);}
    CHECK(f.trial.result().ignored==14);f.reply(q,0,true);CHECK(f.trial.result().island_configured);
    auto next=f.take(1);f.reply(q,17);CHECK(!f.trial.result().failed);f.reply(next);++f.now;
    for(unsigned i=2;i<7;++i)f.pass(i);
    f.reply(next,23);CHECK(f.trial.ready()&&!f.trial.result().failed);
    f.trial.finish();f.cleanup(true,true,true);
}
static void startup_failures(){
    for(unsigned fail=0;fail<7;++fail)for(unsigned mode=0;mode<3;++mode){
        Fixture f;for(unsigned i=0;i<fail;++i)f.pass(i);
        const bool queued=mode!=2;
        if(queued){auto q=f.take(fail);if(mode==0)f.reply(q,0x45,true);}
        else {f.io.accept=false;f.trial.step(f.now);CHECK(f.io.rejected==1);}
        if(mode){f.now+=1000;f.trial.step(f.now);f.io.accept=true;}
        const bool clock=fail>1||(fail==1&&queued),group=fail>3||(fail==3&&queued),start=fail==6&&queued;
        f.cleanup(start,group,clock);const auto &r=f.trial.result();
        CHECK(r.failed&&r.timeout==(mode!=0)&&r.status==(mode?0xffffffff:0x45));
        CHECK(r.clock_sent==clock&&r.group_sent==group&&r.start_sent==start);
        CHECK(r.clock_off==clock&&r.group_off==group&&r.stopped==start);CHECK(!r.cleanup_failed);
    }
}
static void early_finish(){
    for(unsigned last=0;last<7;++last){
        Fixture f;for(unsigned i=0;i<last;++i)f.pass(i);
        auto pending=f.take(last);f.trial.finish();f.reply(pending); // late startup ACK cannot advance startup
        f.cleanup(last==6,last>=3,last>=1);CHECK(!f.trial.result().failed);
        CHECK(f.trial.result().ignored==1);
    }
    Fixture f;f.trial.finish();CHECK(f.trial.done());f.trial.step(100);CHECK(f.io.sent.empty());
}
static void cleanup_failures(){
    for(unsigned fail=7;fail<10;++fail)for(unsigned mode=0;mode<3;++mode){
        Fixture f;f.startup();f.now+=90000;f.trial.finish();
        for(unsigned i=7;i<fail;++i)f.pass(i);
        if(mode!=2){auto q=f.take(fail);if(mode==0)f.reply(q,9);}
        else {f.io.accept=false;f.trial.step(f.now);}
        if(mode){f.now+=1000;f.trial.step(f.now);f.io.accept=true;}
        ++f.now;for(unsigned i=fail+1;i<10;++i)f.pass(i,true);
        CHECK(f.trial.done());const auto &r=f.trial.result();CHECK(r.failed&&r.cleanup_failed);
        CHECK(r.stopped==(fail!=7)&&r.group_off==(fail!=8)&&r.clock_off==(fail!=9));
        CHECK(r.cleanup_status==(mode?0xffffffff:9));
    }
    // Every cleanup command can time out; the sequence still reaches a truthful done.
    Fixture f;f.startup();f.trial.finish();
    for(unsigned i=7;i<10;++i){f.take(i);f.now+=1000;f.trial.step(f.now);}
    CHECK(f.trial.done()&&f.trial.result().cleanup_failed&&!f.trial.result().stopped&&!f.trial.result().group_off&&!f.trial.result().clock_off);
}
static void send_backpressure(){
    Fixture f;f.io.accept=false;f.trial.step(0);f.trial.step(900);CHECK(f.io.sent.empty());
    f.io.accept=true;f.now=999;auto q=f.take(0);CHECK(q.token==0x200);f.reply(q);++f.now;
    for(unsigned i=1;i<7;++i)f.pass(i);f.trial.finish();f.cleanup(true,true,true);
}
int main(){vendor_layouts();success_hold_wrap();rejected_responses();startup_failures();early_finish();cleanup_failures();send_backpressure();
    std::printf("PASS: production AFE TDM, pinned vendor structs, %u assertions\n",checks);}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    harness = args.output / "afe-tdm-harness.cpp"
    harness.write_text(HARNESS, encoding="utf-8")
    binary = args.output / "afe-tdm-harness"
    command = ["clang++", "-std=c++17", "-O1", "-g", "-fsanitize=address,undefined",
               "-fno-omit-frame-pointer", "-Wall", "-Wextra", "-Werror",
               "-I" + host_path(ROOT / "patches/nabu-audio"),
               "-I" + host_path(ROOT / "tools/fixtures"),
               host_path(harness), "-o", host_path(binary)]
    run(host_command(command))
    result = run(host_command([host_path(binary)]))
    report = {"status": "passed", "production_source": "patches/nabu-audio/NabuAfeTdm.h",
              "vendor_fixture": "tools/fixtures/nabu_afe_vendor_wire.h",
              "vendor_revision": "d41f8e1a6827294af6a61adbe18544518e750166",
              "host_result": result.strip(), "sanitizers": ["address", "undefined"],
              "coverage": ["all 10 command payloads against original packed structs",
                           "independent exact clock bytes, instance headers and command prefixes",
                           "20/32-byte APR responses, endpoint/token/opcode/status/length filters",
                           "90-second hold then fresh teardown deadline, uint32 time wrap",
                           "each startup failure, lost response and unsent/backpressure timeout",
                           "early finish and late startup responses",
                           "each teardown error/lost response/send timeout continues remaining cleanup",
                           "sent-but-unconfirmed enables are revoked, unsent enables are not invented"],
              "device_executed": False, "clock_measured": False, "audio_output_verified": False}
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
