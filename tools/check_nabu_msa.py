#!/usr/bin/env python3
"""Exercise the production MSA owner assignments and reverse-order reclaim."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path

ROOT=Path(__file__).resolve().parents[1]
PREFIX=r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include "NabuWlfw.h"
static void IOSleep(unsigned){}
static void nabu_wireless_log(const char*,...){}
struct Assignment{uint64_t address,size;std::vector<uint32_t> from,to;};
static std::vector<Assignment> calls;
static int fail=-1;
extern "C" bool nabu_assign_memory(uint64_t address,uint64_t size,const uint32_t *from,unsigned n,const uint32_t *to,unsigned m){
    calls.push_back({address,size,{from,from+n},{to,to+m}});return (int)calls.size()!=fail;
}
'''
TEST=r'''
int main(){
    NabuWlfw::Region regions[]={{0x8bc00000,0x4000,true},{0x8bc04000,0x17c000,false}};
    assert(nabu_msa_prepare(regions,2)&&calls.size()==2);
    assert(calls[0].from==std::vector<uint32_t>{3}&&calls[0].to==(std::vector<uint32_t>{15,24}));
    assert(calls[1].to==(std::vector<uint32_t>{15,24,25}));
    nabu_msa_finish();assert(calls.size()==4&&assigned_count==0);
    assert(calls[2].address==0x8bc04000&&calls[2].from==(std::vector<uint32_t>{15,24,25})&&calls[2].to==std::vector<uint32_t>{3});
    assert(calls[3].address==0x8bc00000&&calls[3].from==(std::vector<uint32_t>{15,24}));
    calls.clear();fail=2;assert(!nabu_msa_prepare(regions,2)&&assigned_count==1);fail=-1;
    nabu_msa_finish();assert(calls.size()==3&&calls[2].address==0x8bc00000&&assigned_count==0);
    puts("MSA: exact secure/nonsecure VMIDs, reverse reclaim and partial grant cleanup passed");
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);src=(ROOT/'patches/nabu-wireless/NabuMsa.cpp').read_text();src=src[src.index('static NabuWlfw::Region'):]
    source=a.output/'msa.cpp';source.write_text(PREFIX+src+TEST);binary=a.output/'msa-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (a.output/'test.log').write_bytes(result.stdout);(a.output/'test.stderr').write_bytes(result.stderr);result.check_returncode()
    report={'production_msa_tested':True,'sanitizers':['address','undefined'],'result':result.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
