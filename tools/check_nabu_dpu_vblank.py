#!/usr/bin/env python3
"""Execute the production DPU IRQ engine on host fixtures and compile its kernel binding.

No device access, kernel execution, downloads, deployment or file hash audits.
Uses the existing WSL clang++ toolchain on Windows. --kernel-command reuses a
known build's ARM64 flags; --kernel checks the actual undefined symbol imports.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from check_darwinboot_8796 import host_command, host_path
from check_capacity_kernel import symbols

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / 'patches/nabu-display/NabuDpuVBlank.cpp'
REFERENCE = ROOT / 'log/host/gpu-v187/irq-reference'
ANDROID = ROOT / 'log/host/gpu-zero-copy/source/android'

HARNESS = r'''
#include "NabuDpuVBlank.h"
#include <cassert>
#include <cstdio>
#include <map>
#include <vector>
using namespace NabuDpuVBlank;
struct Access {char kind; uint32_t offset, value;};
struct Fixture {
    std::map<uint32_t,uint32_t> regs;
    std::vector<Access> accesses, posted;
    unsigned failAt=0, operations=0;
    uint32_t otherRoot=0;
    bool otherMdp=false, suppressEnable=false;
    Fixture(uint32_t first=100) {
        regs[Intf1]=regs[Intf2]=1;
        regs[Intf1+0xac]=regs[Intf2+0xac]=first;
        regs[Intf1+0xb0]=4;regs[Intf2+0xb0]=5;
        regs[TopEnable]=(1u<<6); // unrelated interrupt remains owned elsewhere
    }
    bool fail() {return ++operations==failAt;}
    static bool rd(void *p,uint32_t at,uint32_t *out) {
        auto &f=*static_cast<Fixture *>(p);
        assert(at+4<=MdssBytes && !(at&3));
        assert(at!=Intf1+0xa8 && at!=Intf2+0xa8); // COUNT_EN is not status
        f.accesses.push_back({'r',at,0});
        if(f.fail())return false;
        if(at==RootStatus) *out=f.otherRoot|((f.otherMdp||(f.regs[TopStatus]&f.regs[TopEnable]))?1:0);
        else *out=f.regs[at];
        return true;
    }
    static bool wr(void *p,uint32_t at,uint32_t value) {
        auto &f=*static_cast<Fixture *>(p);
        assert(at==TopEnable || at==TopClear);
        if(at==TopClear)assert((value&~Owned)==0 && value!=0);
        else assert((value&~Owned)==(f.regs[TopEnable]&~Owned));
        f.accesses.push_back({'w',at,value});
        if(f.fail())return false;
        f.posted.push_back({'w',at,value});return true;
    }
    static bool barrier(void *p) {
        auto &f=*static_cast<Fixture *>(p);
        f.accesses.push_back({'b',0,0});
        if(f.fail())return false;
        for(auto a:f.posted) {
            if(a.offset==TopEnable)f.regs[TopEnable]=a.value&~(f.suppressEnable?MasterVSync:0);
            else f.regs[TopStatus]&=~a.value;
        }
        f.posted.clear();return true;
    }
    Core::Io io(){return {this,rd,wr,barrier};}
    void frame(uint32_t a,uint32_t b){regs[Intf1+0xac]=a;regs[Intf2+0xac]=b;}
    void ready(Core::State &s) {
        assert(Core::prepare(io(),s)==None);
        assert(Core::enable(io(),s)==None && s.enabled);
        accesses.clear();operations=0;
    }
    bool irq(Core::State &s,uint32_t bits,uint64_t when) {
        regs[TopStatus]|=bits;
        return Core::interrupt(io(),s,when);
    }
};
int main() {
    std::printf("REG %llx %x %x %x %x %x %x %x %x %x %x %x %x\n",
        (unsigned long long)MdssPhysical, Interrupt, RootStatus, TopEnable, TopStatus, TopClear,
        Intf1, Intf2, MasterVSync, SlaveVSync, MasterUnderrun, SlaveUnderrun, Owned);
    unsigned groups=0;
    {
        Fixture f;Core::State s{};
        f.regs[TopStatus]=Owned|(1u<<7);f.regs[TopEnable]|=Owned;
        assert(Core::prepare(f.io(),s)==None);
        assert(f.regs[TopStatus]==(1u<<7) && f.regs[TopEnable]==(1u<<6));
        assert(s.sample.masterSequence==0 && s.sample.masterTimestamp==0);
        ++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);
        assert(s.sample.masterSequence==0 && s.sample.masterTimestamp==0);
        f.frame(101,100);assert(f.irq(s,MasterVSync,10));
        assert(s.sample.masterSequence==1 && s.sample.masterTimestamp==10);
        assert(s.sample.vsync[0]==1 && s.sample.vsync[1]==0 && s.sample.fault==0);
        assert(f.regs[TopStatus]==0 && f.posted.empty());
        f.frame(101,101);assert(f.irq(s,SlaveVSync,11));
        assert(s.sample.masterSequence==1 && s.sample.masterTimestamp==10 && s.sample.irqTimestamp==11);
        // This is the snapshot a delayed callback sees after coalescing. Master
        // advancement remains visible although the last IRQ was slave-only.
        const Sample delivered=s.sample;
        assert(delivered.masterSequence==1 && delivered.topStatus==SlaveVSync);
        assert(f.irq(s,MasterVSync,12)); // stale same-counter interrupt
        assert(s.sample.masterSequence==1 && s.sample.masterTimestamp==10);
        ++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);
        f.frame(101,101);assert(f.irq(s,SlaveVSync,20));
        assert(s.sample.frame[0]==101 && s.sample.masterSequence==0);
        assert(f.irq(s,MasterVSync,21)); // slave counter read must not steal master
        assert(s.sample.masterSequence==1);
        f.frame(104,104);assert(f.irq(s,MasterVSync|SlaveVSync,22));
        assert(s.sample.masterSequence==4 && s.sample.vsync[0]==2 && s.sample.vsync[1]==2);
        ++groups;
    }
    {
        Fixture f(UINT32_MAX-1);Core::State s{};f.ready(s);
        f.frame(UINT32_MAX,UINT32_MAX);assert(f.irq(s,MasterVSync|SlaveVSync,30));
        f.frame(0,0);assert(f.irq(s,MasterVSync|SlaveVSync,31));
        assert(s.sample.masterSequence==2 && s.sample.fault==0);++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);
        f.frame(5,5);assert(f.irq(s,MasterVSync,32));
        assert(s.sample.fault==CounterDiscontinuity && s.sample.masterSequence==0);++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);
        assert(f.irq(s,MasterUnderrun|SlaveUnderrun,40));
        assert(s.sample.underrun[0]==1 && s.sample.underrun[1]==1);
        assert(s.sample.masterSequence==0 && s.sample.fault==None);
        assert(!f.irq(s,0,41) && s.sample.spurious==1);++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);
        f.frame(101,101);assert(f.irq(s,MasterVSync,42));
        assert(Core::disable(f.io(),s)==None && !s.enabled);
        assert(f.regs[TopEnable]==(1u<<6));
        f.accesses.clear();
        // An in-flight IRQ after pause cannot access MDSS or queue work.
        f.frame(110,110);assert(!f.irq(s,Owned,43));
        assert(f.accesses.empty() && s.sample.irqCount==1);
        f.regs[TopStatus]|=1u<<7;
        assert(Core::rearm(f.io(),s)==None && s.enabled);
        assert(s.sample.topStatus==(Owned|(1u<<7)));
        assert(f.regs[TopStatus]==(1u<<7)); // no foreign acknowledgement
        assert(s.countedMaster==110 && s.sample.masterSequence==1);
        assert(s.sample.masterTimestamp==42 && s.sample.irqCount==1);
        assert(s.sample.underrun[0]==0 && s.sample.underrun[1]==0);
        assert(f.irq(s,MasterVSync,44)); // stale same-frame event is not a new frame
        assert(s.sample.masterSequence==1 && s.sample.masterTimestamp==42);
        f.frame(111,111);assert(f.irq(s,MasterVSync,45));
        assert(s.sample.masterSequence==2 && s.sample.masterTimestamp==45);
        ++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);
        assert(Core::disable(f.io(),s)==None);
        f.regs[Intf2]=0;
        assert(Core::rearm(f.io(),s)==TimingStopped && !s.enabled);
        assert(f.regs[TopEnable]==(1u<<6) && s.sample.masterSequence==0);
        ++groups;
    }
    {
        Fixture baseline;Core::State original{};baseline.ready(original);
        assert(Core::disable(baseline.io(),original)==None);
        baseline.operations=0;baseline.regs[TopStatus]=Owned;
        assert(Core::rearm(baseline.io(),original)==None);
        const unsigned count=baseline.operations;
        for(unsigned fail=1;fail<=count;++fail) {
            Fixture f;Core::State s{};f.ready(s);
            assert(Core::disable(f.io(),s)==None);
            f.operations=0;f.failAt=fail;f.regs[TopStatus]=Owned;
            assert(Core::rearm(f.io(),s)!=None && !s.enabled);
            assert(s.sample.masterSequence==0);
        }
        ++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);
        f.regs[TopStatus]=1u<<7; // foreign RAW pending, but disabled
        f.frame(101,101);assert(f.irq(s,MasterVSync,50));
        assert(s.sample.fault==None && s.sample.masterSequence==1 && f.regs[TopStatus]==1u<<7);
        f.regs[TopEnable]|=1u<<7;
        assert(f.irq(s,SlaveVSync,51));
        assert(s.sample.fault==ForeignTop && f.regs[TopStatus]==1u<<7);
        assert((f.regs[TopEnable]&~Owned)==((1u<<6)|(1u<<7)));++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);f.otherRoot=1u<<4;
        f.frame(101,101);assert(f.irq(s,MasterVSync,60));
        assert(s.sample.fault==ForeignRoot && s.sample.masterSequence==0);
        assert(f.otherRoot==1u<<4 && f.regs[TopStatus]==0);++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);f.otherMdp=true;
        f.frame(101,101);assert(f.irq(s,MasterVSync,70));
        assert(s.sample.fault==None && s.sample.masterSequence==1);
        assert(f.irq(s,0,71)); // residual level from another MDP group
        assert(s.sample.fault==UnhandledMdp && f.otherMdp);++groups;
    }
    {
        Fixture f;Core::State s{};f.regs[Intf2]=0;
        assert(Core::prepare(f.io(),s)==TimingStopped && !s.enabled);
        for(auto a:f.accesses)assert(a.kind=='r');
        f.regs[Intf2]=1;f.ready(s);f.regs[Intf1]=0;
        assert(f.irq(s,MasterVSync,80) && s.sample.fault==TimingStopped);
        assert(s.sample.masterSequence==0);++groups;
    }
    {
        Fixture f;Core::State s{};f.ready(s);f.regs[TopStatus]=Owned|(1u<<7);
        f.regs[TopEnable]|=1u<<8; // preserve another owner's intervening enable
        assert(Core::disable(f.io(),s)==None && !s.enabled);
        assert(f.regs[TopEnable]==((1u<<6)|(1u<<8)) && f.regs[TopStatus]==1u<<7);
        const unsigned before=f.operations;
        assert(!f.irq(s,MasterVSync,90) && f.operations==before);
        ++groups;
    }
    unsigned injected=0;
    for(int phase=0;phase<4;++phase) {
        Fixture baseline;Core::State state{};
        if(phase)baseline.ready(state);
        if(phase==0 || phase==3)baseline.regs[TopStatus]=Owned|(1u<<7);
        if(phase==0)assert(Core::prepare(baseline.io(),state)==None);
        if(phase==1)assert(Core::enable(baseline.io(),state)==None);
        if(phase==2){baseline.frame(101,101);assert(baseline.irq(state,MasterVSync,100));}
        if(phase==3)assert(Core::disable(baseline.io(),state)==None);
        for(unsigned fault=1;fault<=baseline.operations;++fault) {
            Fixture f;Core::State s{};
            if(phase)f.ready(s);
            if(phase==0 || phase==3)f.regs[TopStatus]=Owned|(1u<<7);
            if(phase==1)s.enabled=false;
            f.failAt=fault;
            if(phase==0)assert(Core::prepare(f.io(),s)&RegisterIo);
            if(phase==1)assert(Core::enable(f.io(),s)&RegisterIo);
            if(phase==2){f.frame(101,101);assert(f.irq(s,MasterVSync,100));}
            if(phase==3)assert(Core::disable(f.io(),s)&RegisterIo);
            assert(s.sample.fault&RegisterIo);
            assert(s.sample.masterSequence==0 && s.sample.masterTimestamp==0);
            if(phase!=2)assert(!s.enabled);
            ++injected;
        }
    }
    {
        Fixture f;Core::State s{};assert(Core::prepare(f.io(),s)==None);
        f.suppressEnable=true;
        assert(Core::enable(f.io(),s)==RegisterIo && !s.enabled);++groups;
    }
    std::printf("PASS %u behavioral groups and %u injected register failures\n",groups,injected);
}
'''


def run(command):
    result = subprocess.run(host_command(command), capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed:\n{result.stdout}\n{result.stderr}')
    return result.stdout


def literal_defines(path):
    return {name: int(number, 16) for name, number in re.findall(
        r'^#define\s+(\w+)\s+(0x[0-9a-fA-F]+)\b', path.read_text(), re.M)}


def check_reference(output):
    hw = literal_defines(REFERENCE / 'sde_hwio.h')
    irq = literal_defines(ANDROID / 'sde_hw_interrupts.c')
    bit = {name: 1 << int(n) for name, n in re.findall(
        r'^#define\s+(\w+)\s+BIT\((\d+)\)', (ANDROID / 'sde_hw_interrupts.c').read_text(), re.M)}
    bits = [bit[f'SDE_INTR_INTF_{i}_{event}'] for event in ('VSYNC', 'UNDERRUN') for i in (1, 2)]
    top = irq['MDP_SSPP_TOP0_OFF']
    dt = (ANDROID / 'sm8150-sde.dtsi').read_text()
    spi = int(re.search(r'interrupts\s*=\s*<0 (\d+) 0>', dt)[1])
    assert '#define IRQ_SOURCE_MDP\t\tBIT(0)' in (REFERENCE / 'sde_hw_interrupts.h').read_text()
    actual = [int(x, 16) for x in output.splitlines()[0].split()[1:]]
    expected = [0xae00000, spi + 32, irq['HW_INTR_STATUS'], top + hw['INTR_EN'],
                top + hw['INTR_STATUS'], top + hw['INTR_CLEAR'], irq['MDP_INTF_1_OFF'],
                irq['MDP_INTF_2_OFF'], *bits, sum(bits)]
    assert actual == expected, (actual, expected)
    return len(expected)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel-command', type=Path)
    ap.add_argument('--kernel', type=Path)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    source = CPP.read_text()
    assert 'thread_call_enter_delayed' not in source and 'IOSleep' not in source
    assert 'THREAD_CALL_OPTIONS_ONCE' in source
    assert 'gic_v3_spi_attach(Interrupt, false, arrived, b)' in source
    assert 'if (b->state.sample.fault) gic_v3_spi_mask(Interrupt)' in source
    stop = source[source.index('void stop(Binding *b)'):]
    assert stop.index('gic_v3_spi_mask') < stop.index('Core::disable') < stop.index('gic_v3_spi_detach')
    assert stop.index('IOSimpleLockUnlockEnableInterrupt') < stop.index('gic_v3_spi_detach')
    assert stop.index('gic_v3_spi_detach') < stop.index('thread_call_cancel_wait') < stop.index('release(b)')
    pause = source[source.index('uint32_t pauseForHandover('):source.index('uint32_t resumeAfterHandover(')]
    assert pause.index('b->paused = true') < pause.index('gic_v3_spi_mask') < pause.index('Core::disable')
    assert pause.index('IOSimpleLockUnlockEnableInterrupt') < pause.index('thread_call_cancel_wait')
    assert 'const bool live = b->live && !b->paused' in source and 'if (!b->live || b->paused)' in source
    display = (CPP.parent / 'NabuDpuDisplay.cpp').read_text()
    handover = display[display.index('static IOReturn initializeMapper('):display.index('static void finishRecord(')]
    assert handover.index('pauseForHandover') < handover.index('Scan::quiesce') < handover.index('activateAfterQuiesce')
    assert handover.index('activateAfterQuiesce') < handover.index('Scan::resume') < handover.index('resumeAfterHandover')
    # Check the actual XNU implementation: the header's older cancel_wait
    # description omits ONCE, but this kernel explicitly cancels and waits it.
    thread_call = (REFERENCE / 'thread_call.c').read_text()
    cancel = thread_call[thread_call.index('thread_call_cancel_wait(thread_call_t call)'):]
    assert 'thread_call_wait_once_locked(call, s)' in cancel[:2500]
    results = {'scope': 'Local production-engine/source checks; no real IRQ, scanout acceptance or deployment'}
    with tempfile.TemporaryDirectory(prefix='nabu-dpu-vblank-') as tmp:
        temp = Path(tmp)
        harness, binary = temp / 'fixture.cpp', temp / 'fixture'
        harness.write_text(HARNESS)
        compiler = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
        run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-DNABU_DPU_VBLANK_HOST_TEST',
             '-I' + host_path(CPP.parent), host_path(CPP), host_path(harness), '-o', host_path(binary)])
        output = run([host_path(binary)])
        results['reference_constants'] = check_reference(output)
        results['host_result'] = output.splitlines()[-1]
        results['arm64_kernel_compiled'] = False
        if args.kernel_command:
            original = json.loads(args.kernel_command.read_text())
            command, index = [], 0
            while index < len(original):
                arg = original[index]
                if arg in ('-c', '-o', '-include'):
                    index += 2
                else:
                    command.append(arg)
                    index += 1
            target = temp / 'NabuDpuVBlank.o'
            command += ['-I' + host_path(CPP.parent), '-c', host_path(CPP), '-o', host_path(target)]
            run(command)
            sizes = [int(x.split('\t')[1]) for x in target.with_suffix('.su').read_text().splitlines() if '\t' in x]
            results['max_function_stack_bytes'] = max(sizes)
            assert max(sizes) <= 1024
            ir = temp / 'NabuDpuVBlank.ll'
            run(command[:-2] + ['-o', host_path(ir), '-S', '-emit-llvm'])
            llvm = ir.read_text()
            assert re.search(r'\bload volatile i32\b', llvm) and re.search(r'\bstore volatile i32\b', llvm)
            asm = re.findall(r'\basm sideeffect\s+"([^"]*)"', llvm)
            assert 'dmb oshld' in asm and 'dsb sy' in asm
            undefined = run(['llvm-nm-18', '--undefined-only', host_path(target)])
            imports = [line.split()[-1] for line in undefined.splitlines() if line.strip()]
            for name in ('_gic_v3_spi_attach', '_gic_v3_spi_mask', '_gic_v3_spi_unmask', '_gic_v3_spi_detach',
                         '_thread_call_allocate_with_options', '_thread_call_cancel_wait'):
                assert name in imports, name
            if args.kernel:
                kernel_symbols, _ = symbols(args.kernel.read_bytes())
                missing = [name for name in imports if name not in kernel_symbols]
                assert not missing, missing
                results['actual_kernel_imports_resolved'] = len(imports)
            results['imports'] = imports
            results['arm64_kernel_compiled'] = True
    results['passed'] = True
    text = json.dumps(results, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
