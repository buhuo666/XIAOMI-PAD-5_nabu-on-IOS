#!/usr/bin/env python3
"""Exercise trace scopes through early returns, disabled capture and errno changes."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path
from nabu_metal_submit_trace import stage_submit_trace

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <atomic>
#include <cerrno>
#include <cstdint>
#include <cassert>
#include <vector>
#include <cstdio>
static std::atomic<bool> gCaPresentTrace{false};
struct Row {uint64_t id, stage, ptr, cpu;};
static std::vector<Row> rows;
static void nabu_ca_trace_marker(uint32_t event,uint64_t id,uint64_t a,uint64_t b,uint64_t c) {
 assert(event==127);rows.push_back({id,a,b,c});errno=EINVAL;
}
#include "NativeMetalSubmitTrace.inc"
static unsigned calls;
static bool original(bool result){++calls;errno=EIO;return result;}
static bool submit(bool result) {
 NabuMetalSubmitSpan outer(16,17,7,0x1234);
 NabuMetalSubmitSpan inner(20,21,7,0x1234);
 return original(result);
}
int main(int argc,char **) {
 if(argc>1) {
  setenv("NABU_METAL_SUBMIT_TRACE","1",1);
  errno=ENOENT;
  assert(!gCaPresentTrace.load()&&submit(true)&&errno==EIO&&calls==1&&rows.size()==4);
  puts("PASS: process launch option enables backboardd markers without the App setter");
  return 0;
 }
 unsetenv("NABU_METAL_SUBMIT_TRACE");
 errno=EAGAIN;assert(submit(true)&&calls==1&&errno==EIO&&rows.empty());
 gCaPresentTrace=true;
 for(bool result:{false,true}) {
  rows.clear();errno=EAGAIN;assert(submit(result)==result&&errno==EIO);
  assert(rows.size()==4);
  const uint64_t stages[]={16,20,21,17};
  for(unsigned i=0;i<4;++i){assert(rows[i].stage==stages[i]&&rows[i].id==7&&rows[i].ptr==0x1234&&rows[i].cpu>0);}
  for(unsigned i=1;i<4;++i)assert(rows[i].cpu>=rows[i-1].cpu);
 }
 assert(calls==3);
 rows.clear();errno=ENOENT;
 {NabuMetalSubmitSpan span(22,23,8,0x2345);assert(errno==ENOENT);gCaPresentTrace=false;errno=ESRCH;}
 assert(errno==ESRCH&&rows.size()==2&&rows[1].stage==23);
 puts("PASS: disabled, early return true/false, paired capture toggle, original errno and monotonic thread CPU");
}
'''


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    out = a.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    staged = out / 'frontend'; staged.mkdir(exist_ok=True)
    shutil.copyfile(a.input / 'frontend-source/NativeBridgeMetalFrontend.mm', staged / 'NativeBridgeMetalFrontend.mm')
    schema = stage_submit_trace(ROOT, staged)
    source = out / 'submit.cpp'; source.write_text(HARNESS, encoding='utf-8')
    binary = out / 'submit'
    command = ['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-I'+host_path(staged), host_path(source), '-o', host_path(binary)]
    r = subprocess.run(host_command(command), capture_output=True)
    (out / 'compile.log').write_bytes(r.stdout+r.stderr)
    if r.returncode: raise RuntimeError(r.stderr.decode(errors='replace'))
    r = subprocess.run(host_command([host_path(binary)]), capture_output=True)
    (out / 'run.log').write_bytes(r.stdout+r.stderr)
    if r.returncode: raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
    result = r.stdout.decode().strip()
    r = subprocess.run(host_command([host_path(binary),'--process-option']),capture_output=True)
    (out / 'process-option.log').write_bytes(r.stdout+r.stderr)
    if r.returncode: raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
    result += '\n' + r.stdout.decode().strip()
    (out / 'report.json').write_text(json.dumps(dict(result='pass',schema=schema,checks=result),indent=2)+'\n')
    print(result)


if __name__ == '__main__': main()
