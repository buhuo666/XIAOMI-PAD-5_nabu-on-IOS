#!/usr/bin/env python3
"""Run the production scanout core against the GPU185 baseline and register/fence fixtures.

Local only: no device access, deployment, source downloads or integration edits.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / 'patches/nabu-display/NabuDpuScanoutCore.cpp'
SNAPSHOT = ROOT / 'log/host/gpu-v185/dpu-snapshot.json'
REF = ROOT / 'log/host/gpu-zero-copy/source/android'

HARNESS = r'''
#include "NabuDpuScanoutCore.h"
#include <cassert>
#include <cstdio>
#include <map>
#include <tuple>
#include <vector>
using namespace NabuDpuScanout;
struct Fake {
    std::map<std::pair<Region,uint32_t>,uint32_t> regs;
    std::vector<std::tuple<Region,uint32_t,uint32_t>> writes;
    uint64_t now=0, nextLatch=0, haltReady=0, period=8333;
    uint32_t active[2]={GopPhysical,GopPhysical}, frameBase=100;
    bool flushing=false, clearFlush=true, slaveRuns=true, haltAck=true, partialAck=false;
    unsigned failWrite=0, writeDelay=0;
    Fake() { BASELINE
        regs[{Vbif,HaltRequest}]=0x20; regs[{Mdss,Vig0ForceClock}]=0xa0;
        regs[{Mdss,Vig1ForceClock}]=0xb1;
    }
    void advance() {
        if(flushing && clearFlush && now>=nextLatch) {
            active[0]=regs[{Mdss,Vig0+SrcAddress}];active[1]=regs[{Mdss,Vig1+SrcAddress}];
            flushing=false;
        }
    }
    static bool read(void *p,Region r,uint32_t at,uint32_t *out) {
        auto &f=*static_cast<Fake *>(p);f.advance();
        assert(!(at&3) && at+4<=(r==Mdss?MdssBytes:VbifBytes));
        if(r==Mdss && at==Ctl0+CtlFlush) {*out=f.flushing?3:0;return true;}
        if(r==Mdss && (at==Intf1+0xac || at==Intf2+0xac)) {
            *out=f.frameBase+uint32_t((at==Intf2+0xac && !f.slaveRuns)?0:f.now/f.period);return true;
        }
        if(r==Mdss && (at==Intf1+0xb0 || at==Intf2+0xb0)) {*out=uint32_t(f.now%f.period)*2758/f.period;return true;}
        if(r==Vbif && at==HaltStatus) {
            *out=(f.haltAck && f.now>=f.haltReady)?(f.regs[{Vbif,HaltRequest}]&(f.partialAck?1:XinMask)):0;return true;
        }
        auto it=f.regs.find({r,at});assert(it!=f.regs.end());*out=it->second;return true;
    }
    static bool write(void *p,Region r,uint32_t at,uint32_t value) {
        auto &f=*static_cast<Fake *>(p);assert(writable(r,at));
        f.now+=f.writeDelay;f.advance();
        f.writes.push_back({r,at,value});f.regs[{r,at}]=value;
        if(r==Mdss && at==Ctl0+CtlFlush) {
            assert(value==3);f.flushing=true;f.nextLatch=(f.now/f.period+1)*f.period;
        }
        if(r==Vbif && at==HaltRequest) f.haltReady=f.now+100;
        // A failed callback may already have reached hardware: no software rollback.
        return !f.failWrite || f.writes.size()!=f.failWrite;
    }
    static bool barrier(void *p) {static_cast<Fake *>(p)->advance();return true;}
    static uint64_t clock(void *p) {return static_cast<Fake *>(p)->now;}
    static void wait(void *p,unsigned us) {assert(us==50);static_cast<Fake *>(p)->now+=us;}
    Io io() {return {this,read,write,barrier,clock,wait};}
};
static Frame frame(uint32_t iova=0x80000000,uint64_t sequence=1) {
    return {iova,6400,16384000,sequence,1600,2560,BgraFourcc,4,0,true};
}
int main() {
    size_t n;auto *expected=inheritedRegisters(&n);
    for(size_t i=0;i<n;++i)std::printf("EXPECTED %x %x\n",expected[i].offset,expected[i].value);
    std::printf("CONSTANTS %x %x %x %x %x %x %x %x\n",HaltRequest,HaltStatus,XinMask,
        Vig0ForceClock,Vig1ForceClock,SrcAddress,SrcStride,CtlFlush);
    Diagnostic d={};
    { Fake f;State s={};assert(initialize(f.io(),s,&d)==Ok && f.writes.empty());
      f.regs[{Mdss,0x2004}]=0x01000005;State other={};
      assert(initialize(f.io(),other,&d)==TopologyMismatch && d.offset==0x2004 && f.writes.empty()); }
    { Fake f;State s={};initialize(f.io(),s,&d);Frame bad=frame();bad.pixel_format=0x52474241;
      assert(submit(f.io(),s,bad,&d)==Argument && f.writes.empty());
      bad=frame();bad.width=800;assert(submit(f.io(),s,bad,&d)==Argument);
      bad=frame();bad.linear=false;assert(submit(f.io(),s,bad,&d)==Argument);
      bad=frame();bad.mapped_bytes--;assert(submit(f.io(),s,bad,&d)==Argument);
      bad=frame(0xfffff000);assert(submit(f.io(),s,bad,&d)==Argument); }
    { Fake f;State s={};initialize(f.io(),s,&d);
      assert(submit(f.io(),s,frame(),&d)==Pending && f.writes.size()==5);
      assert(std::get<1>(f.writes.back())==Ctl0+CtlFlush);
      assert(std::get<2>(f.writes[0])==std::get<2>(f.writes[1]));
      assert(f.active[0]==GopPhysical && f.active[1]==GopPhysical);
      assert(submit(f.io(),s,frame(0x82000000,2),&d)==StateError);
      Acceptance a={};assert(poll(f.io(),s,a,&d)==Pending && !a.accepted);
      assert(waitAccepted(f.io(),s,20000,a,&d)==Ok && a.accepted);
      assert(a.retired_iova==GopPhysical && a.current_iova==0x80000000 && a.sequence==1);
      assert(f.active[0]==0x80000000 && f.active[1]==0x80000000);
      assert(submit(f.io(),s,frame(0x82000000,2),&d)==Pending);
      assert(waitAccepted(f.io(),s,20000,a,&d)==Ok && a.retired_iova==0x80000000 && a.retired_sequence==1);
      for(auto w:f.writes)assert(std::get<0>(w)==Mdss && std::get<1>(w)!=0x201c); }
    { Fake f;State s={};initialize(f.io(),s,&d);f.writeDelay=2500;
      assert(submit(f.io(),s,frame(),&d)==Pending);
      // One edge occurred while both SSPP shadow registers were being staged.
      assert(f.active[0]==GopPhysical && f.active[1]==GopPhysical);
      Acceptance a={};assert(waitAccepted(f.io(),s,20000,a,&d)==Ok && a.accepted); }
    for(unsigned failure=0;failure<2;++failure) {
      Fake f;State s={};initialize(f.io(),s,&d);
      if(failure==0)f.clearFlush=false;else f.slaveRuns=false;
      assert(submit(f.io(),s,frame(),&d)==Pending);Acceptance a={};
      assert(waitAccepted(f.io(),s,20000,a,&d)==Timeout && !a.accepted && s.phase==Failed);
      assert(s.current_iova==GopPhysical && s.pending.display_iova==0x80000000);
    }
    { Fake f;State s={};initialize(f.io(),s,&d);f.frameBase=UINT32_MAX;
      assert(submit(f.io(),s,frame(),&d)==Pending);Acceptance a={};
      assert(waitAccepted(f.io(),s,20000,a,&d)==Ok && a.accepted); }
    { Fake f;State s={};initialize(f.io(),s,&d);f.failWrite=2;
      assert(submit(f.io(),s,frame(),&d)==IoError && s.phase==Failed && f.writes.size()==2);
      assert(s.current_iova==GopPhysical && s.pending.display_iova==0x80000000);
      assert(resume(f.io(),s,&d)==StateError); }
    { Fake f;State s={};initialize(f.io(),s,&d);
      assert(quiesce(f.io(),s,HaltTimeoutUs,&d)==Ok && s.phase==Quiesced && f.now>=100);
      assert(f.regs.at({Vbif,HaltRequest})==0x31);
      assert(f.regs.at({Mdss,Vig0ForceClock})==0xa1 && f.regs.at({Mdss,Vig1ForceClock})==0xb1);
      assert(submit(f.io(),s,frame(),&d)==StateError);
      f.regs[{Mdss,Vig0ForceClock}]|=0x400; // unrelated bit changed while held
      assert(resume(f.io(),s,&d)==Ok && s.phase==Ready);
      assert(f.regs.at({Vbif,HaltRequest})==0x20);
      assert(f.regs.at({Mdss,Vig0ForceClock})==0x4a0 && f.regs.at({Mdss,Vig1ForceClock})==0xb1);
      assert(f.active[0]==GopPhysical && f.active[1]==GopPhysical); }
    { Fake f;State s={};initialize(f.io(),s,&d);f.partialAck=true;
      assert(quiesce(f.io(),s,1000,&d)==Timeout && s.phase==Failed);
      assert(f.regs.at({Vbif,HaltRequest})==0x31 && d.observed==1);
      assert(resume(f.io(),s,&d)==StateError); }
    assert(!writable(Mdss,0x201c) && !writable(Mdss,Intf1) && !writable(Vbif,HaltStatus));
    std::puts("PASS inherited topology, BGRA layout, shared shadow flush, dual-frame retirement, wrap, failures, halt ACK and resume preservation");
}
'''


def run(command):
    r = subprocess.run(host_command(command), capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError(f'{command[0]}: {r.stdout}\n{r.stderr}')
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel-command', type=Path)
    args = ap.parse_args()
    snapshot = json.loads(SNAPSHOT.read_text())['registers']
    registers = {v['offset']: v['value'] for name, block in snapshot.items()
                 if name.startswith(('MDSS', 'CTL', 'LM', 'SSPP', 'INTF')) for v in block.values()}
    baseline = '\n'.join(f'regs[{{Mdss,0x{k:x}}}]=0x{v:x};' for k, v in registers.items())
    with tempfile.TemporaryDirectory(prefix='nabu-scanout-core-') as folder:
        folder = Path(folder)
        fixture = folder / 'fixture.cpp'; binary = folder / 'fixture'
        fixture.write_text(HARNESS.replace('BASELINE', baseline))
        compiler = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
        run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-O1', '-g',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I' + host_path(CPP.parent),
             host_path(CPP), host_path(fixture), '-o', host_path(binary)])
        output = run([host_path(binary)])
        expected_count = 0
        for line in output.splitlines():
            if line.startswith('EXPECTED '):
                _, at, value = line.split()
                assert registers[int(at, 16)] == int(value, 16), line
                expected_count += 1
        constants = next(line for line in output.splitlines() if line.startswith('CONSTANTS '))
        actual = [int(x, 16) for x in constants.split()[1:]]
        defs = {}
        for name in ['sde_hw_vbif.c', 'sde_hw_sspp.c', 'sde_hw_ctl.c']:
            defs.update({k: int(v, 16) for k, v in re.findall(r'^#define\s+(\w+)\s+(0x[\da-fA-F]+)',
                         (REF / name).read_text(), re.M)})
        assert actual == [defs['VBIF_XIN_HALT_CTRL0'], defs['VBIF_XIN_HALT_CTRL1'], 0x11,
                          0x1000 + 0x2ac, 0x1000 + 0x2b4, defs['SSPP_SRC0_ADDR'],
                          defs['SSPP_SRC_YSTRIDE0'], defs['CTL_FLUSH']]
        dts = (REF / 'sm8150-sde.dtsi').read_text()
        assert 'qcom,sde-sspp-xin-id = <0 4 8 12' in dts and '<0x2ac 0>, <0x2b4 0>' in dts
        vbif = (REF / 'sde_hw_vbif.c').read_text()
        assert 'SDE_REG_READ(c, VBIF_XIN_HALT_CTRL1)' in vbif and 'reg_val & BIT(xin_id)' in vbif
        sspp_table = (REF / 'sde_hw_ctl.c').read_text()
        assert re.search(r'sspp_tbl\[SSPP_MAX\]\s*=\s*\{ SDE_NONE, 0, 1,', sspp_table)
        kernel = False; stack_max = None
        if args.kernel_command:
            raw = json.loads(args.kernel_command.read_text()); flags = []; i = 0
            while i < len(raw):
                if raw[i] in ['-c', '-o', '-include']:
                    i += 2
                else:
                    flags.append(raw[i]); i += 1
            target = folder / 'core.o'
            run(flags + ['-Wall', '-Wextra', '-Werror', '-I' + host_path(CPP.parent),
                         '-c', host_path(CPP), '-o', host_path(target)])
            stack_max = max(int(x.split('\t')[1]) for x in target.with_suffix('.su').read_text().splitlines())
            assert stack_max <= 1024
            kernel = True
        print(json.dumps({'passed': True, 'inherited_registers_verified_against_gpu185': expected_count,
                          'reference_register_constants_verified': len(actual),
                          'host_result': output.splitlines()[-1], 'arm64_kernel_compiled': kernel,
                          'max_function_stack_bytes': stack_max,
                          'scope': 'Production callback core under host fixtures; no physical DPU writes or hardware acceptance qualification'}, indent=2))


if __name__ == '__main__':
    main()
