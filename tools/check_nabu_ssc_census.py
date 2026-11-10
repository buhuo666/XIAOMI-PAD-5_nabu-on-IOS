#!/usr/bin/env python3
"""Replay captured Android QMI packets through the live XNU SSC census."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>
#include "NabuSscNative.h"
using Bytes=std::vector<uint8_t>;
static Bytes unhex(const std::string &s){
    Bytes b;for(size_t i=0;i<s.size();i+=2)b.push_back(uint8_t(std::stoul(s.substr(i,2),nullptr,16)));return b;
}
struct IO {
    std::vector<Bytes> sent;
    unsigned events=0;
    bool blocked=false;
    std::vector<NabuSensorRecord> records;
    std::vector<unsigned> invalidated;
    bool send_ssc(uint32_t node,uint32_t port,uint32_t from,const uint8_t *p,uint32_t n){
        assert(node==9&&port==12&&from==0x100);
        if(blocked)return false;
        sent.emplace_back(p,p+n);return true;
    }
    void ssc_event(unsigned,NabuSsc::Suid,uint32_t,uint64_t,NabuSsc::Span){++events;}
    int32_t native_submit(const NabuSensorDescription &d,const NabuSensorRecord &r){
        assert(d.kind==r.kind&&d.product[0]&&d.manufacturer[0]);
        assert(d.physical_suid[0]||d.physical_suid[1]);
        records.push_back(r);return 0;
    }
    void native_invalidate(unsigned kind,int32_t reason){assert(reason);invalidated.push_back(kind);}
    uint64_t native_timeout_ms(unsigned){return 2000;}
};
int main(int argc,char **argv){
    assert(argc==2);
    static IO io;static NabuSsc::Census<IO> live(io);
    live.start(9,12,100);live.tick(100);assert(io.sent.size()==7);
    std::ifstream f(argv[1]);assert(f.good());
    std::string line;std::vector<Bytes> expected,received;Bytes first_response,first_indication;
    while(std::getline(f,line)){
        auto bytes=unhex(line.substr(2));
        if(line[0]=='T'){expected.push_back(bytes);continue;}
        received.push_back(bytes);
        if(bytes[0]==2&&first_response.empty())first_response=bytes;
        if(bytes[0]==4&&first_indication.empty())first_indication=bytes;
        live.receive(9,12,0x100,bytes.data(),bytes.size());live.tick(100);
    }
    assert(live.result.invalid==0&&live.result.foreign==0&&live.result.qmi_failures==0&&live.result.errors==0);
    assert(live.stream_count==4);
    assert(live.discovery[4].state==NabuSsc::State::Absent&&live.discovery[5].state==NabuSsc::State::Absent);
    assert(live.discovery[6].state==NabuSsc::State::Incomplete);
    for(unsigned i=0;i<live.stream_count;++i){
        const auto &s=live.streams[i];assert(s.configured&&s.samples&&s.nonmonotonic==0);
        printf("stream %s: samples=%u first=%llu last=%llu accuracy=%u\n",live.type(s.type),s.samples,
               (unsigned long long)s.first,(unsigned long long)s.last,s.latest.status);
    }
    // Reject a stale destination, a foreign QMI client, and a duplicate/unknown response.
    unsigned before=io.events;
    live.receive(8,12,0x100,first_indication.data(),first_indication.size());
    assert(live.result.foreign==1&&io.events==before);
    auto foreign=first_indication;foreign[10]^=1;
    live.receive(9,12,0x100,foreign.data(),foreign.size());
    assert(live.result.foreign==2&&io.events==before);
    live.receive(9,12,0x100,first_response.data(),first_response.size());assert(live.result.invalid==1);
    auto unknown=first_response;NabuSsc::put16(unknown.data()+1,1000);
    live.receive(9,12,0x100,unknown.data(),unknown.size());assert(live.result.invalid==2);
    live.tick(8100);assert(live.result.stopping&&!live.result.done);
    assert(io.sent==expected); // Exact lookup, attribute, configuration and disable bytes from Android.
    live.tick(8600);assert(live.result.done);
    static IO continuous_io;static NabuSsc::Census<IO> continuous(continuous_io);
    static NabuSsc::Native<IO> native(continuous_io);
    unsigned samples[7]{};
    struct Receiver {IO &io;NabuSsc::Census<IO> &census;NabuSsc::Native<IO> &native;unsigned *samples;};
    Receiver receiver{continuous_io,continuous,native,samples};
    continuous.stream([](void *ctx,unsigned type,NabuSsc::Suid suid,uint64_t ticks,const NabuSsc::Sample &sample){
        auto &r=*static_cast<Receiver *>(ctx);assert(type<4&&sample.count);++r.samples[type];
        const size_t before=r.io.records.size();
        // Zero denotes an unvalidated clock: physical data alone may not publish.
        r.native.sample(r.census,type,suid,ticks,sample,0,100);assert(r.io.records.size()==before);
        // Host-only clock fixture. No device epoch is inferred by this replay.
        r.native.sample(r.census,type,suid,ticks,sample,ticks+1000,100);
        assert(r.io.records.size()==before+1);
        const auto &out=r.io.records.back();
        assert(out.ssc_ticks==ticks&&out.mach_timestamp==ticks+1000&&out.accuracy==sample.status);
        assert(!memcmp(out.value_bits,sample.values,out.value_count*4));
    },&receiver);
    continuous.start(9,12,100);continuous.tick(100);
    assert(continuous_io.records.empty());
    for(const auto &bytes:received){continuous.receive(9,12,0x100,bytes.data(),bytes.size());continuous.tick(100);}
    for(unsigned i=0;i<live.stream_count;++i){
        unsigned kind=live.streams[i].type;
        assert(samples[kind]==live.streams[i].samples&&native.accepted[kind]==samples[kind]&&native.active(kind));
    }
    native.tick(continuous,2099,-1,-2);assert(continuous_io.invalidated.empty());
    native.tick(continuous,2100,-1,-2);
    assert(continuous_io.invalidated.size()==3&&!native.active(0)&&!native.active(1)&&!native.active(2));
    assert(native.active(3)); // unchanged on-change ALS is not a missing periodic stream.
    size_t actual_records=continuous_io.records.size();
    for(const auto &bytes:received)if(bytes[0]==4)continuous.receive(9,12,0x100,bytes.data(),bytes.size());
    assert(continuous_io.records.size()==actual_records); // duplicate timestamps cannot revive streams.
    continuous.tick(8100);assert(!continuous.result.stopping&&!continuous.result.done);
    continuous.finish(8100);continuous.tick(8100);assert(continuous_io.sent==expected);
    native.tick(continuous,8100,-1,-2);assert(!native.active(3)&&continuous_io.invalidated.size()==4);
    native.stop(-3);assert(continuous_io.invalidated.size()==4);
    continuous.tick(8600);assert(continuous.result.done);
    // Change only one captured configuration ACK to a real QMI error. Later
    // captured samples for that failed stream must never reach the native sink.
    uint16_t failed_transaction=0;
    for(const auto &bytes:expected){
        NabuSsc::Reader body({bytes.data()+12,NabuSsc::u16(bytes.data()+10)});NabuSsc::Field field;
        while(body.next(field))if(field.number==2&&field.integer==NabuSsc::StreamConfig&&!failed_transaction)
            failed_transaction=NabuSsc::u16(bytes.data()+1);
    }
    assert(failed_transaction);
    static IO failed_io;static NabuSsc::Census<IO> failed(failed_io);unsigned failed_samples=0;
    failed.stream([](void *ctx,unsigned,NabuSsc::Suid,uint64_t,const NabuSsc::Sample &){++*static_cast<unsigned *>(ctx);},&failed_samples);
    failed.start(9,12,100);failed.tick(100);
    for(auto bytes:received){
        if(bytes[0]==2&&NabuSsc::u16(bytes.data()+1)==failed_transaction){
            bool replaced=false;
            for(size_t at=7;at<bytes.size();){
                unsigned type=bytes[at],size=NabuSsc::u16(bytes.data()+at+1);at+=3;
                if(type==2){assert(size==4);NabuSsc::put16(bytes.data()+at,1);NabuSsc::put16(bytes.data()+at+2,42);replaced=true;}
                at+=size;
            }
            assert(replaced);
        }
        failed.receive(9,12,0x100,bytes.data(),bytes.size());failed.tick(100);
    }
    unsigned failed_streams=0,delivered=0;
    for(unsigned i=0;i<failed.stream_count;++i){
        const auto &stream=failed.streams[i];
        if(stream.failed){++failed_streams;assert(!stream.samples&&!stream.configured);}
        else delivered+=stream.samples;
    }
    assert(failed_streams==1&&failed.result.qmi_failures==1&&failed_samples==delivered);
    static IO missing_io;static NabuSsc::Census<IO> missing(missing_io);
    missing.start(9,12,10);missing.tick(10);missing.tick(3010);
    assert(missing.result.done&&missing.stream_count==0);
    for(const auto &d:missing.discovery)assert(d.state==NabuSsc::State::Timeout);
    static IO busy_io;static NabuSsc::Census<IO> busy(busy_io);
    busy_io.blocked=true;busy.start(9,12,0);busy.tick(0);assert(busy.result.sent==0);
    busy_io.blocked=false;busy.tick(10);assert(busy.result.sent==7&&busy_io.sent.size()==7);
    puts("PASS: actual Android packets, native raw sample forwarding, unknown clock rejection, stale/on-change distinction, failed ACK isolation and bounded disable drain");
}
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--capture',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    events=[]
    for line in a.capture.read_text().splitlines():
        row=json.loads(line)
        if row['kind']=='tx':events.append('T '+row['hex'])
        if row['kind']=='rx' and row['node']==9 and row['port']==12:events.append('R '+row['hex'])
    fixture=a.output/'android-replay.txt';fixture.write_text('\n'.join(events)+'\n',newline='\n')
    source=a.output/'ssc-census.cpp';source.write_text(HARNESS)
    binary=a.output/'ssc-census'
    command=host_command(['g++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
                          '-fsanitize=address,undefined','-fno-omit-frame-pointer','-g',
                          '-I'+host_path(ROOT/'patches/nabu-sensors'),host_path(source),'-o',host_path(binary)])
    compiled=subprocess.run(command,capture_output=True)
    (a.output/'compile.log').write_bytes(compiled.stdout+compiled.stderr)
    if compiled.returncode:raise SystemExit(compiled.stderr.decode(errors='replace'))
    result=subprocess.run(host_command([host_path(binary),host_path(fixture)]),capture_output=True,timeout=30)
    (a.output/'run.log').write_bytes(result.stdout+result.stderr)
    report=dict(passed=result.returncode==0,capture=str(a.capture),packets=len(events),command=command,
                stdout=result.stdout.decode(errors='replace'),device_execution=False)
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['stdout'])
    if result.returncode:raise SystemExit(result.stderr.decode(errors='replace'))

if __name__=='__main__':main()
