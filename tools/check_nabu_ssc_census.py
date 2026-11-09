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
#include "NabuSscCensus.h"
using Bytes=std::vector<uint8_t>;
static Bytes unhex(const std::string &s){
    Bytes b;for(size_t i=0;i<s.size();i+=2)b.push_back(uint8_t(std::stoul(s.substr(i,2),nullptr,16)));return b;
}
struct IO {
    std::vector<Bytes> sent;
    unsigned events=0;
    bool blocked=false;
    bool send_ssc(uint32_t node,uint32_t port,uint32_t from,const uint8_t *p,uint32_t n){
        assert(node==9&&port==12&&from==0x100);
        if(blocked)return false;
        sent.emplace_back(p,p+n);return true;
    }
    void ssc_event(unsigned,NabuSsc::Suid,uint32_t,uint64_t,NabuSsc::Span){++events;}
};
int main(int argc,char **argv){
    assert(argc==2);
    static IO io;static NabuSsc::Census<IO> live(io);
    live.start(9,12,100);live.tick(100);assert(io.sent.size()==7);
    std::ifstream f(argv[1]);assert(f.good());
    std::string line;std::vector<Bytes> expected;Bytes first_response,first_indication;
    while(std::getline(f,line)){
        auto bytes=unhex(line.substr(2));
        if(line[0]=='T'){expected.push_back(bytes);continue;}
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
    static IO missing_io;static NabuSsc::Census<IO> missing(missing_io);
    missing.start(9,12,10);missing.tick(10);missing.tick(3010);
    assert(missing.result.done&&missing.stream_count==0);
    for(const auto &d:missing.discovery)assert(d.state==NabuSsc::State::Timeout);
    static IO busy_io;static NabuSsc::Census<IO> busy(busy_io);
    busy_io.blocked=true;busy.start(9,12,0);busy.tick(0);assert(busy.result.sent==0);
    busy_io.blocked=false;busy.tick(10);assert(busy.result.sent==7&&busy_io.sent.size()==7);
    puts("PASS: actual Android requests/replies/samples, absent and incomplete endpoints, identity/transaction checks, send backpressure and bounded disable drain");
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
