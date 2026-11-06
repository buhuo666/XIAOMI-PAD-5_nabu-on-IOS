#!/usr/bin/env python3
"""Run the production RMTFS QMI decoder against in-memory files and shared buffers."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include "NabuRmtfs.h"
static std::vector<uint8_t> qmi(unsigned id) { return {0,7,0,(uint8_t)id,0,0,0}; }
static void add(std::vector<uint8_t> &p,unsigned type,const void *data,unsigned n) {
    p.push_back(type);p.push_back(n);p.push_back(n>>8);p.insert(p.end(),(const uint8_t*)data,(const uint8_t*)data+n);
    p[5]=p.size()-7;p[6]=(p.size()-7)>>8;
}
int main() {
    uint8_t file[8192],buffer[4096],out[64];for(unsigned i=0;i<sizeof(file);++i)file[i]=i%251;memset(buffer,0,sizeof(buffer));
    NabuRmtfs r{};r.files[0]={"/boot/modem_fs1",file,sizeof(file),false};r.buffer=buffer;r.physical=0x99100000;r.buffer_size=sizeof(buffer);
    auto p=qmi(1);add(p,1,r.files[0].path,strlen(r.files[0].path));assert(r.answer(p.data(),p.size(),out)==21&&out[17]==1&&!out[10]);
    p=qmi(4);uint32_t wanted=4096;add(p,2,&wanted,4);assert(r.answer(p.data(),p.size(),out)==25&&NabuRmtfs::u32(out+17)==r.physical);
    auto io=[&](unsigned sector,unsigned count,bool write) {
        auto p=qmi(3);uint32_t caller=1;uint8_t dir=write;uint8_t vec[13]={1};uint32_t values[]={sector,r.physical,count};
        memcpy(vec+1,values,12);add(p,1,&caller,4);add(p,2,&dir,1);add(p,3,vec,13);return p;
    };
    p=io(2,4,false);assert(r.answer(p.data(),p.size(),out)==14&&!out[10]&&r.reads==1&&!memcmp(buffer,file+1024,2048));
    memset(buffer,0x43,1024);p=io(4,2,true);r.answer(p.data(),p.size(),out);assert(!out[10]&&r.writes==1);
    for(unsigned i=2048;i<3072;++i)assert(file[i]==0x43);
    p=io(15,2,false);r.answer(p.data(),p.size(),out);assert(out[10]==1&&out[12]==2);
    p=io(0,9,false);r.answer(p.data(),p.size(),out);assert(out[10]==1);
    p=qmi(2);uint32_t id=1;add(p,1,&id,4);r.answer(p.data(),p.size(),out);assert(!r.files[0].open);
    p=io(0,1,false);r.answer(p.data(),p.size(),out);assert(out[10]==1);
    p=qmi(1);const char *missing="/boot/no-file";add(p,1,missing,strlen(missing));r.answer(p.data(),p.size(),out);assert(out[10]==1);
    p.pop_back();assert(r.answer(p.data(),p.size(),out)==0);
    puts("RMTFS: open/allocate/read/write/close, range errors and QMI lengths passed; writes only touched RAM");
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);source=a.output/'rmtfs.cpp';source.write_text(HARNESS);binary=a.output/'rmtfs-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (a.output/'test.log').write_bytes(result.stdout);(a.output/'test.stderr').write_bytes(result.stderr);result.check_returncode()
    report={'production_rmtfs_tested':True,'sanitizers':['address','undefined'],'hardware_tested':False,'result':result.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
