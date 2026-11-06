#!/usr/bin/env python3
"""Exercise production TFTP negotiation, range reads, acknowledgements and retries."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <vector>
#include "NabuTftp.h"
static std::vector<uint8_t> request(const char *name, bool options) {
    std::vector<uint8_t> p{0,1};
    for(const char *s:{name,"octet"})p.insert(p.end(),s,s+strlen(s)+1);
    if(options)for(const char *s:{"blksize","4000","wsize","4","tsize","0","seek","777","rsize","8234"})p.insert(p.end(),s,s+strlen(s)+1);
    return p;
}
int main() {
    std::vector<uint8_t> file(12555);for(unsigned i=0;i<file.size();++i)file[i]=(i*7)%251;
    for(bool options:{false,true}) {
        auto p=request("/readonly/firmware/image/wlanmdsp.mbn",options);NabuTftp t{};
        assert(t.begin(p.data(),p.size(),file.data(),file.size()));
        std::vector<uint8_t> received;
        unsigned rounds=0;
        while(t.active&&rounds++<100) {
            assert(t.pending);unsigned op=t.payload[1];
            if(op==3)received.insert(received.end(),t.payload+4,t.payload+t.payload_bytes);
            else assert(op==6&&options);
            t.sent();uint8_t ack[]={0,4,(uint8_t)(t.block>>8),(uint8_t)t.block};
            t.acknowledge(ack,sizeof(ack));
        }
        assert(t.complete&&received.size()==(options?8234:file.size()));
        assert(!memcmp(received.data(),file.data()+(options?777:0),received.size()));
        assert(t.delivered==received.size());
    }
    auto p=request("/readonly/firmware/image/wlanmdsp.mbn",true);NabuTftp t{};
    assert(t.begin(p.data(),p.size(),file.data(),file.size()));t.sent();
    for(unsigned i=0;i<1000;++i)t.tick();assert(t.pending&&t.payload[1]==6&&t.retries==1);
    t.sent();uint8_t bad[]={0,4,0,9};t.acknowledge(bad,4);assert(t.block==0&&!t.pending);
    for(unsigned n=0;n<3;++n){for(unsigned i=0;i<1000;++i)t.tick();if(t.pending)t.sent();}
    assert(!t.active);
    auto missing=request("/readonly/firmware/image/missing.bin",false);t=NabuTftp{};
    assert(t.begin(missing.data(),missing.size(),file.data(),file.size())&&t.payload[1]==5&&t.payload[3]==1);
    p[1]=2;t=NabuTftp{};assert(t.begin(p.data(),p.size(),file.data(),file.size())&&t.payload[3]==2);
    puts("TFTP: full/ranged bytes, option negotiation, ACK progression, retries and read-only errors passed");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    source=args.output/'tftp.cpp';source.write_text(HARNESS);binary=args.output/'tftp-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (args.output/'test.log').write_bytes(result.stdout);(args.output/'test.stderr').write_bytes(result.stderr)
    result.check_returncode();report={'production_tftp_tested':True,'sanitizers':['address','undefined'],
        'hardware_tested':False,'result':result.stdout.decode().strip()}
    (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
