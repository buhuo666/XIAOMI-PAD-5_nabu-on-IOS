#!/usr/bin/env python3
"""Validate the actual diagnostic stream's framing, ownership and rectangle coverage."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    source=out/'clear-stream.cpp';exe=out/'clear-stream'
    source.write_text(r'''
#include "NabuA640Clear.h"
#include <cassert>
#include <cstdio>
int main() {
    NabuA640ClearCommands commands;commands.build(0x302400,0x300020);
    assert(commands.count<=160);
    AdrenoPM4Packet packets[80]{};size_t count=0;
    assert(AdrenoPM4Plan(commands.words,commands.count,packets,80,&count)==AdrenoPM4Success);
    unsigned blits=0,coverage[512]={};uint32_t tl=0,br=0;
    bool destination=false,flushed=false;
    for(size_t i=0;i<count;++i) {
        const auto &p=packets[i];const uint32_t *v=commands.words+p.header_word+1;
        if(p.type==4) {
            if(p.identifier==0x8c17) {
                assert(p.payload_words==4 && v[0]==0x30 && v[1]==0x302400 && v[2]==0 && v[3]==2);
                destination=true;
            }
            if(p.identifier==0x8405) {assert(p.payload_words==2);tl=v[0];br=v[1];}
        } else {
            assert(p.identifier==0x26 || p.identifier==0x65 || p.identifier==0x46 || p.identifier==0x2c);
            if(p.identifier==0x2c) {
                assert(destination && p.payload_words==1 && v[0]==3);
                unsigned x0=tl&0xffff,y0=tl>>16,x1=br&0xffff,y1=br>>16;
                assert(x0<=x1 && x1<32 && y0<=y1 && y1<16);
                for(unsigned y=y0;y<=y1;++y)for(unsigned x=x0;x<=x1;++x)++coverage[y*32+x];
                ++blits;
            }
            if(p.identifier==0x46 && v[0]==0x1d) {
                assert(blits==4 && p.payload_words==4 && v[1]==0x300020 && v[2]==0);
                flushed=true;
            }
        }
    }
    for(unsigned value:coverage)assert(value==1);
    assert(blits==4 && flushed);
    printf("PASS %zu words, %zu packets; four bounded raster rectangles cover 512 pixels once; CCU flush; no CP_MEM_WRITE\n",commands.count,count);
}
''',encoding='utf-8',newline='\n')
    pm4=ROOT/'src/nabu/gpu/upstream/AdrenoPM4'
    cmd=['clang++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
         '-I'+host_path(ROOT/'patches/nabu-gpu'),'-I'+host_path(pm4),host_path(source),'-x','c++',host_path(pm4/'AdrenoPM4.c'),'-o',host_path(exe)]
    subprocess.run(host_command(cmd),check=True)
    r=subprocess.run(host_command([host_path(exe)]),capture_output=True,check=True)
    (out/'test.log').write_bytes(r.stdout+r.stderr)
    report={'passed':True,'test_output':r.stdout.decode().strip(),'scope':'Production PM4 builder/decoder with ASan/UBSan; no GPU or pixel-rendering claim'}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
