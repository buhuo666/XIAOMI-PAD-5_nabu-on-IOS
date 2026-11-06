#!/usr/bin/env python3
"""Restore the actual board snapshots with the production sparse decoder and compare bytes."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path
from nabu_rmtfs_sparse import pack, unpack

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <fstream>
#include <iterator>
#include <vector>
#include "NabuRmtfsSparse.h"
int main(int argc,char **argv) {
    assert(argc==3);std::ifstream a(argv[1],std::ios::binary),b(argv[2],std::ios::binary);
    std::vector<uint8_t> packed{std::istreambuf_iterator<char>(a),{}},original{std::istreambuf_iterator<char>(b),{}};
    std::vector<uint8_t> output(original.size());assert(nabu_rmtfs_unpack(packed.data(),packed.size(),output.data(),output.size()));
    assert(output==original);packed[0]=0;assert(!nabu_rmtfs_unpack(packed.data(),packed.size(),output.data(),output.size()));
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--snapshot',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);source=a.output/'unpack.cpp';source.write_text(HARNESS);binary=a.output/'unpack-test'
    subprocess.run(host_command(['clang++-18','-std=c++17','-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),'-o',host_path(binary)]),check=True)
    files=[]
    for f in json.loads((a.snapshot/'snapshot.json').read_text())['files']:
        raw=a.snapshot/f['file'];data=raw.read_bytes();packed=pack(data);assert unpack(packed)==data
        destination=a.output/(f['file']+'.packed');destination.write_bytes(packed)
        result=subprocess.run(host_command([host_path(binary),host_path(destination),host_path(raw)]),capture_output=True)
        (a.output/(f['file']+'.stderr')).write_bytes(result.stderr);result.check_returncode()
        files.append({'file':f['file'],'original_bytes':len(data),'packed_bytes':len(packed),'restored_equal':True})
    report={'production_decoder_tested':True,'sanitizers':['address','undefined'],'files':files,'packed_total':sum(f['packed_bytes'] for f in files)}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
