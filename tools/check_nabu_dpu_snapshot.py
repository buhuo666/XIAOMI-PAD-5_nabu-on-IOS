#!/usr/bin/env python3
"""Check the production DPU read plan against pinned sources and execute it on host fixtures.

No device access, downloads, MMIO, hooks or build-system edits. Temporary binaries
are removed on exit. Requires the existing clang++ toolchain (WSL on Windows).
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
CPP = ROOT / 'patches/nabu-display/NabuDpuSnapshot.cpp'
HEADER = CPP.with_suffix('.h')
REFERENCE = ROOT / 'log/host/gpu-zero-copy/source'

HARNESS = r'''
#include "NabuDpuSnapshot.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <tuple>
#include <vector>
using namespace NabuDpuSnapshot;
struct Fixture {
    std::map<std::pair<int,uint32_t>,uint32_t> values;
    std::vector<std::pair<int,uint32_t>> reads;
    std::map<std::tuple<std::string,unsigned,std::string>,uint64_t> notes;
    uint64_t now=0, period=0;
    uint32_t initial=0;
    bool countEnabled=false, frozen=false, zeroEnableReadback=false;
    static bool rd(void *p, Space s, uint32_t at, uint32_t *out) {
        auto &f=*static_cast<Fixture *>(p);
        assert(rangeFits(s,at)); f.reads.push_back({int(s),at});
        if(s==Mdss && (at==0x6b800 || at==0x6c000)) {*out=f.countEnabled?1:0;return true;}
        if(s==Mdss && (at==0x6b8a8 || at==0x6c0a8)) {*out=(f.countEnabled&&!f.zeroEnableReadback)?3:0;return true;}
        if(s==Mdss && (at==0x6b8ac || at==0x6c0ac)) {
            *out=f.initial+((f.period && !f.frozen)?uint32_t(f.now/f.period):0);return true;
        }
        if(s==Mdss && (at==0x6b8b0 || at==0x6c0b0)) {*out=uint32_t(f.now%2560);return true;}
        auto it=f.values.find({int(s),at}); *out=it==f.values.end()?0:it->second;return true;
    }
    static uint64_t clock(void *p) {return static_cast<Fixture *>(p)->now;}
    static void sleep(void *p,unsigned ms) {assert(ms==1);static_cast<Fixture *>(p)->now+=ms*1000;}
    static void emit(void *p,Space,const char *block,unsigned index,const char *name,uint32_t off,uint64_t value) {
        if(off==UINT32_MAX) static_cast<Fixture *>(p)->notes[{block,index,name}]=value;
    }
    Reader reader() {return {this,rd,clock,sleep,emit};}
    uint64_t note(const char *block,unsigned index,const char *name) {return notes.at({block,index,name});}
    bool has(const char *block,unsigned index,const char *name) {return notes.count({block,index,name})!=0;}
    void geometry(uint32_t id0=(1u<<27)|(15u<<9)|94u,uint32_t id1=(6u<<28)|80u) {
        values[{Apps,0x20}]=id0; values[{Apps,0x24}]=id1; values[{Apps,0x28}]=1u<<12;
    }
    void route(unsigned slot,uint16_t sid,uint16_t mask,unsigned bank,unsigned type=0) {
        values[{Apps,0x800+4*slot}]=(1u<<31)|(uint32_t(mask)<<16)|sid;
        values[{Apps,0xc00+4*slot}]=(type<<16)|bank;
    }
};
int main() {
    std::printf("BASE %llx %x %x %llx %x\n", (unsigned long long)MdssPhysical, MdssBytes,
                DpuChildOffset, (unsigned long long)AppsPhysical, AppsBytes);
    size_t count;const Plan *p=plans(&count);
    assert(count==23);
    unsigned total=0;
    for(size_t i=0;i<count;++i) for(size_t j=0;j<p[i].count;++j) {
        assert(p[i].registers[j].offset+4<=p[i].bytes);
        assert(rangeFits(Mdss,p[i].base+p[i].registers[j].offset));++total;
        std::printf("PLAN %s %u %x %x %s\n",p[i].block,p[i].index,p[i].base,p[i].registers[j].offset,p[i].registers[j].name);
    }
    assert(rangeFits(Mdss,MdssBytes-4) && !rangeFits(Mdss,MdssBytes));
    assert(!rangeFits(Mdss,1) && !rangeFits(Apps,AppsBytes) && !rangeFits(static_cast<Space>(2),0));
    Fixture basic;basic.geometry();capture(basic.reader(),0,Identify);
    unsigned appsReads=0;
    for(auto r:basic.reads) if(r.first==Apps) {assert(r.second==0x20 || r.second==0x48);++appsReads;}
    assert(appsReads==2 && basic.note("APPS",0,"route_reads_skipped")==1);
    assert(basic.reads.size()==total+2);
    uint32_t gr1,cb;
    assert(contextBase((6u<<28)|80u,3,&gr1,&cb) && gr1==0x1000 && cb==0x83000);
    assert(!contextBase((1u<<31)|(6u<<28)|80u,3,&gr1,&cb));
    assert(!contextBase((7u<<28)|80u,3,&gr1,&cb));
    assert(!contextBase((6u<<28)|80u,80,&gr1,&cb));
    const uint32_t id0=(1u<<27)|(15u<<9)|94u;
    assert(overlapsDisplay(id0,0x84200800,3));
    assert(overlapsDisplay(id0,0x80000c20,7)); // exact member of the masked display set
    assert(!overlapsDisplay(id0,0x80000900,7));
    assert(!overlapsDisplay(id0,0x04200800,3)); // invalid legacy SMR
    assert(overlapsDisplay(id0|(1u<<8),0x04200800,(1u<<10)|3));
    assert(!overlapsDisplay(id0|(1u<<8),0x04200800,3));
    Fixture deep;deep.geometry();
    deep.route(1,0x800,0x420,3);deep.route(2,0xc20,0,3);
    deep.route(3,0x900,0,4);deep.route(4,0x800,0x420,5,1);
    capture(deep.reader(),0,Contexts);
    assert(deep.note("APPS",0,"overlapping_routes")==3);
    unsigned cbReads=0;
    for(auto r:deep.reads) if(r.first==Apps) {
        if(r.second>=0x800 && r.second<0xc00) assert(r.second<0x800+94*4);
        if(r.second>=0xc00 && r.second<0x1000) assert(r.second<0xc00+94*4);
        if(r.second>=0x80000) {assert(r.second>=0x83000 && r.second<=0x83058);++cbReads;}
    }
    assert(cbReads==10); // same matching CB captured once; bypass never dereferenced
    Fixture routes;routes.geometry();routes.route(1,0x800,0x420,3);capture(routes.reader(),0,Routes);
    for(auto r:routes.reads) if(r.first==Apps) assert(r.second<0x1000);
    Fixture bad;bad.geometry(id0,(7u<<28)|80u);bad.route(1,0x800,0x420,3);capture(bad.reader(),0,Contexts);
    assert(bad.note("CB",3,"unknown_geometry_skipped")==1);
    for(auto r:bad.reads) if(r.first==Apps) assert(r.second<0x1000);
    for(uint64_t period:{8333ull,16667ull}) for(bool zeroReadback:{false,true}) {
        Fixture f;f.geometry();f.period=period;f.countEnabled=true;f.initial=UINT32_MAX-3;
        f.zeroEnableReadback=zeroReadback; // GPU184 inherited register behavior
        capture(f.reader(),999,Identify);
        assert(f.now==250000 && f.note("SAMPLE",0,"polls")==249);
        uint64_t measured=f.note("SAMPLE",1,"poll_estimate_period_ns");
        assert(measured>period*1000-150000 && measured<period*1000+150000);
        assert(f.note("SAMPLE",1,"max_counter_jump")==1);
    }
    Fixture frozen;frozen.geometry();frozen.countEnabled=true;frozen.frozen=true;
    capture(frozen.reader(),50,Identify);assert(!frozen.has("SAMPLE",1,"poll_estimate_period_ns"));
    Fixture off;off.geometry();capture(off.reader(),250,Identify);assert(off.now==0);
    std::printf("PASS default reads, reference plan, masked routes, EXIDS, CB bounds, 60/120 polling, wrap and stopped counters\n");
}
'''


def run(command):
    result = subprocess.run(host_command(command), capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed:\n{result.stdout}\n{result.stderr}')
    return result.stdout


def literal_defines(path):
    return {name: int(number, 16) for name, number in re.findall(
        r'^#define\s+(\w+)\s+(0x[0-9a-fA-F]+)\b', path.read_text(), re.M)}


def reference_check(output):
    definitions = {}
    for part in ['ctl', 'lm', 'sspp', 'intf']:
        definitions.update(literal_defines(REFERENCE / f'android/sde_hw_{part}.c'))
    dts = (REFERENCE / 'android/sm8150-sde.dtsi').read_text()
    bases = {}
    for block, key in [('CTL', 'ctl'), ('LM', 'mixer'), ('SSPP', 'sspp'), ('INTF', 'intf')]:
        match = re.search(r'qcom,sde-' + key + r'-off\s*=\s*<([^>]+)>', dts)
        bases[block] = [int(x, 16) for x in re.findall(r'0x[\da-f]+', match[1])]
    catalog = (REFERENCE / 'mainline/dpu_5_0_sm8150.h').read_text()
    mainline = {}
    for block, symbol in [('CTL', 'ctl'), ('LM', 'lm'), ('SSPP', 'sspp'), ('INTF', 'intf')]:
        section = re.search(r'sm8150_' + symbol + r'\[\]\s*=\s*\{(.*?)\n\};', catalog, re.S)
        mainline[block] = [int(x, 16) for x in re.findall(r'\.base\s*=\s*(0x[\da-f]+)', section[1])]
    checked = 0
    saved_dt = json.loads((ROOT / 'log/host/gpu-zero-copy/display-dtb-links.json').read_text())
    mdss = next(x for x in saved_dt['nodes'] if x['node'] == '/soc/qcom,mdss_mdp@ae00000')
    apps = next(x for x in saved_dt['nodes'] if x['node'] == '/soc/apps-smmu@0x15000000')
    for line in output.splitlines():
        if line.startswith('BASE '):
            values = [int(x, 16) for x in line.split()[1:]]
            assert values == [int(x, 16) for x in mdss['properties']['reg']['cells'][:2]] + [0x1000] + [
                int(x, 16) for x in apps['properties']['reg']['cells'][:2]]
            continue
        if not line.startswith('PLAN '):
            continue
        _, block, index, base, offset, name = line.split()
        index, base, offset = int(index), int(base, 16), int(offset, 16)
        if block == 'MDSS':
            expected = {'HW_VERSION': 0, 'HW_INTR_STATUS': 0x10}[name]
            if name == 'HW_VERSION':
                assert 'core_rev = readl_relaxed(sde_kms->mmio + 0x0)' in (REFERENCE / 'android/sde_kms.c').read_text()
            else:
                assert literal_defines(REFERENCE / 'android/sde_hw_interrupts.c')['HW_INTR_STATUS'] == expected
            assert base == 0 and offset == expected
        else:
            assert base == bases[block][index], (block, index, hex(base))
            assert base == mainline[block][index] + 0x1000, (block, 'root/child mismatch')
            if name.startswith('CTL_LAYER'):
                suffix = name[len('CTL_LAYER'):].lstrip('_')
                if suffix.startswith('EXT3_'):
                    expected = 0xa0 + 4 * int(suffix[5:])
                elif suffix.startswith('EXT2_'):
                    expected = 0x70 + 4 * int(suffix[5:])
                elif suffix.startswith('EXT'):
                    expected = 0x40 + 4 * int(suffix[3:])
                else:
                    mixer = int(suffix); expected = 0x24 if mixer == 5 else mixer * 4
                ctl = (REFERENCE / 'android/sde_hw_ctl.c').read_text()
                assert '(0x024)' in ctl and '0x40 +' in ctl and '0x70 +' in ctl and '0xA0 +' in ctl
            else:
                expected = definitions[name]
            assert offset == expected, (name, hex(offset), hex(expected))
        checked += 1
    return checked


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel-command', type=Path,
                    help='Existing compile-command JSON whose flags/headers are reused for a standalone ARM64 compile')
    args = ap.parse_args()
    source = CPP.read_text()
    assert 'const volatile uint32_t *' in source
    assert not re.search(r'\b(?:write32|write64|writel|SDE_REG_WRITE|write_register)\s*\(', source)
    assert 'write32' not in HEADER.read_text() and 'write64' not in HEADER.read_text()
    assert 'kIOMapInhibitCache | kIOMapReadOnly' in source
    # Compile and run the actual capture engine, with only the kernel binding excluded.
    with tempfile.TemporaryDirectory(prefix='nabu-dpu-snapshot-') as tmp:
        temp = Path(tmp)
        harness, binary = temp / 'fixture.cpp', temp / 'fixture'
        harness.write_text(HARNESS)
        compiler = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
        run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
             '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-DNABU_DPU_SNAPSHOT_HOST_TEST',
             '-I' + host_path(CPP.parent), host_path(CPP), host_path(harness), '-o', host_path(binary)])
        output = run([host_path(binary)])
        checked = reference_check(output)
        kernel = False
        stack_max = None
        volatile_loads = None
        if args.kernel_command:
            original = json.loads(args.kernel_command.read_text())
            command = []
            index = 0
            while index < len(original):
                arg = original[index]
                if arg in ['-c', '-o', '-include']:
                    index += 2
                    continue
                command.append(arg); index += 1
            target = temp / 'NabuDpuSnapshot.o'
            command += ['-I' + host_path(CPP.parent), '-c', host_path(CPP), '-o', host_path(target)]
            run(command)
            usage = target.with_suffix('.su')
            sizes = [int(line.split('\t')[1]) for line in usage.read_text().splitlines() if '\t' in line]
            stack_max = max(sizes)
            assert stack_max <= 1024, stack_max
            ir = temp / 'NabuDpuSnapshot.ll'
            ir_command = command[:-2] + ['-o', host_path(ir), '-S', '-emit-llvm']
            run(ir_command)
            llvm = ir.read_text()
            volatile_loads = len(re.findall(r'\bload volatile i32\b', llvm))
            assert volatile_loads >= 1
            assert not re.search(r'\bstore volatile\b', llvm)
            assembly = re.findall(r'\basm sideeffect\s+"([^"]*)"', llvm)
            assert assembly and all(x == 'dmb oshld' for x in assembly), assembly
            kernel = True
        print(json.dumps({'passed': True, 'reference_register_checks': checked,
                          'host_result': output.splitlines()[-1], 'arm64_kernel_compiled': kernel,
                          'max_function_stack_bytes': stack_max,
                          'production_llvm_volatile_load_sites': volatile_loads,
                          'scope': 'Local source/host verification only; no hardware reads, integration or deployment'}, indent=2))


if __name__ == '__main__':
    main()
