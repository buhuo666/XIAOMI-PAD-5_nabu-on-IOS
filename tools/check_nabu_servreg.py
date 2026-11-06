#!/usr/bin/env python3
"""Query the production registry using the original Nabu protection-domain table."""
import argparse
import json
from pathlib import Path
import subprocess
from nabu_servreg import encode
from check_darwinboot_8796 import host_command,host_path

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <vector>
#include "NabuServreg.h"
int main(int argc,char **argv) {
    assert(argc==2);std::ifstream f(argv[1],std::ios::binary);std::vector<uint8_t> table{std::istreambuf_iterator<char>(f),{}};
    NabuServreg r{};assert(r.load(table.data(),table.size()));uint8_t out[1024];
    for(const char *name:{"wlan/fw","kernel/elf_loader","tms/servreg","no/service"}) {
        unsigned n=strlen(name);std::vector<uint8_t> p{0,9,0,0x21,0,(uint8_t)(n+3),0,1,(uint8_t)n,0};p.insert(p.end(),name,name+n);
        unsigned bytes=r.answer(p.data(),p.size(),out);assert(bytes>=24&&!out[10]&&NabuRmtfs::u16(out+5)==bytes-7);
        unsigned len=0;const uint8_t *total=NabuRmtfs::tlv(out,bytes,0x10,len);assert(total&&len==2);
        if(!strcmp(name,"no/service")){assert(NabuRmtfs::u16(total)==0);continue;}
        const uint8_t *list=NabuRmtfs::tlv(out,bytes,0x12,len);assert(list&&list[0]>=1);
        if(!strcmp(name,"wlan/fw")||!strcmp(name,"kernel/elf_loader")) {
            const char *domain="msm/modem/wlan_pd";assert(list[0]==1&&list[1]==strlen(domain));
            assert(!memcmp(list+2,domain,list[1])&&NabuRmtfs::u32(list+2+list[1])==180);
        }
    }
    puts("SERVREG: original Nabu WLAN/ELF/registry/absent-service queries and QMI result lengths passed");
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--registry',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);source=a.output/'servreg.cpp';source.write_text(HARNESS);binary=a.output/'servreg-test';table=a.output/'table.bin';table.write_bytes(encode(a.registry))
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary),host_path(table)]),capture_output=True)
    (a.output/'test.log').write_bytes(result.stdout);(a.output/'test.stderr').write_bytes(result.stderr);result.check_returncode()
    report={'production_registry_tested':True,'sanitizers':['address','undefined'],'result':result.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
