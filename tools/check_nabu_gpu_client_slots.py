#!/usr/bin/env python3
"""Exercise the production GPU slot allocator and A640 address boundaries."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    context = (ROOT/'patches/nabu-gpu/NativeAdrenoGpuContext.h').read_text()
    abi = (ROOT/'src/nabu/gpu/upstream/Adreno6xx/NativeAdrenoABI.h').read_text()
    # Use the shipped backend's actual firmware/ring addresses and queue width.
    constants = '\n'.join(re.findall(r'enum : (?:uint64_t|size_t) \{.*?\};', context, re.S))
    queues = int(re.search(r'NativeAdrenoAbiMaxQueues = (\d+)', abi)[1])
    source = out/'client-slots.cpp'
    source.write_text('#include <cstddef>\n#include <cassert>\n#include <cstdio>\n'
        '#include "NabuGpuClientSlots.h"\n#include "NabuGpuAddressSpace.h"\n'+constants+r'''
int main() {
    const NabuGpuClientWindow reserved[] = {
        {0x100000,0x100000}, // on-chip GMEM
        {GpuSqeIova,GpuSqeBytes},{GpuRingIova,GpuRingBytes},
        {GpuMemptrsIova,GpuPageBytes},{GpuPwrupIova,GpuPageBytes},
        {GpuScratchIova,GpuPageBytes}};
    auto disjoint=[](NabuGpuClientWindow a,NabuGpuClientWindow b) {
        return a.start+a.bytes<=b.start || b.start+b.bytes<=a.start;
    };
    for(unsigned i=0;i<NabuGpuMaxClients;++i) {
        const auto w=NabuGpuClientWindows[i];
        assert(w.bytes && !(w.start&4095) && !(w.bytes&4095));
        assert(w.start+w.bytes<=GpuApertureBytes);
        for(auto r:reserved)assert(disjoint(w,r));
        for(unsigned j=0;j<i;++j)assert(disjoint(w,NabuGpuClientWindows[j]));
    }
    // Ordinary processes cannot consume the compositor's reserved slot.
    bool live[NabuGpuMaxClients]{};
    for(unsigned i=1;i<NabuGpuMaxClients;++i) {
        const unsigned slot=NabuGpuSelectClientSlot(false,live);
        assert(slot==i);live[slot]=true;
    }
    assert(NabuGpuSelectClientSlot(false,live)==NabuGpuMaxClients);
    assert(NabuGpuSelectClientSlot(true,live)==0);live[0]=true;
    assert(NabuGpuSelectClientSlot(true,live)==NabuGpuMaxClients);
    // A successful close frees its slot; retaining a failed close above does not.
    for(unsigned i=1;i<NabuGpuMaxClients;++i) {
        live[i]=false;
        assert(NabuGpuSelectClientSlot(false,live)==i);
        live[i]=true;
    }
    // Reproduce GPU180: compositor + three consumers, then chronod,
    // SpringBoard, the App, and a temporary enumeration connection.
    for(auto &used:live)used=false;
    const bool compositor[]={false,true,false,false,false,false,false,false};
    const unsigned expected[]={1,0,2,3,4,5,6,7};
    for(unsigned i=0;i<8;++i) {
        const unsigned slot=NabuGpuSelectClientSlot(compositor[i],live);
        assert(slot==expected[i]);live[slot]=true;
    }
    // GPU183: Preferences and Spotlight consumed the final two old slots.
    // The App must obtain a high-address window without moving any old one.
    assert(NabuGpuSelectClientSlot(false,live)==8);
    live[8]=true;
    assert(NabuGpuSelectClientSlot(false,live)==9);
    assert(NabuGpuClientWindows[8].start==0x80000000ull);
    assert(NabuGpuClientWindows[23].start+NabuGpuClientWindows[23].bytes==0x100000000ull);
    puts("PASS 24 isolated clients; GPU180/183 launch order; saturation and reuse; A640 firmware/GMEM/ring excluded");
}
'''+f'\nstatic_assert(NabuGpuMaxClients*{queues}<=256,"scheduler queues");\n',
        encoding='utf-8', newline='\n')
    exe = out/'client-slots'
    subprocess.run(host_command(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-I'+host_path(ROOT/'patches/nabu-gpu'),
        host_path(source), '-o', host_path(exe)]), check=True)
    result = subprocess.run(host_command([host_path(exe)]), capture_output=True, check=True)
    (out/'test.log').write_bytes(result.stdout+result.stderr)
    aperture = check_live_aperture(out)
    report = {'passed': True, 'clients': 24, 'queues_per_client': queues,
        'live_aperture': aperture,
        'test_output': result.stdout.decode().strip(),
        'scope': 'Production slot/address policy with ASan/UBSan; no device execution'}
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


def check_live_aperture(out):
    """Use the existing MMIO fixture with the production GPU live-table code."""
    gpu = ROOT/'src/nabu/gpu/upstream/ArmSmmu4K'
    fixture = (ROOT/'src/ArmSmmu4K-nabu/test_live.c').read_text()
    fixture = fixture[:fixture.index('static unsigned profiles(void)')]
    # Derive geometry from the same public constants as kernel bring-up.
    fixture = fixture.replace('#define POOL_PAGES 16',
        '#include "NabuGpuAddressSpace.h"\n#define POOL_PAGES NabuGpuTablePages')
    fixture = fixture.replace('{{bits,output,0x10000000,16}',
                              '{{bits,output,0x10000000,NabuGpuApertureLeaves}')
    fixture = fixture.replace('+low,4*4096,upper,tables',
                              '+low,NabuGpuApertureBytes,upper,tables')
    fixture = fixture.replace('cache?3:2', 'cache?3u:2u')
    fixture += r'''
int main(void) {
    setup(32,0,40,0,0);
    CHECK(state.tables.table_pages==2053);
    ArmSmmu4KLiveArena short_pool=arena;
    ArmSmmu4KLiveState empty={0};
    short_pool.capacity_pages=1027;
    CHECK(ArmSmmu4KLivePrepare(&short_pool,&empty)==ArmSmmu4KCapacity);
    short_pool=arena;short_pool.config.leaf_budget=1u<<19;
    CHECK(ArmSmmu4KLivePrepare(&short_pool,&empty)==ArmSmmu4KBudget);
    unsigned tested=0;
    for(unsigned slot=0;slot<16;++slot)for(unsigned end=0;end<2;++end) {
        const uint64_t va=0x80000000ull+slot*0x08000000ull+(end?0x07fff000ull:0);
        ArmSmmu4KRange r={va,0x180000000ull+tested*4096,4096,3,1,2};
        ArmSmmu4KLiveRegion lower={&arena,&state,0,0};
        reset_counters();
        CHECK(ArmSmmu4KLiveUpdateContextRanges(&io,0,&context,&lower,0,0,
            &visibility,&r,1,1,4,&result)==ArmSmmu4KSuccess);
        CHECK(result.complete && state.tables.leaf_pages==1);
        CHECK((pte(va)&0x0000fffffffff000ull)==r.physical);
        CHECK((pte(va)&0xfffull)==0xe47); // AF, outer shareable, RW EL0, WB index1
        CHECK(!pte(0x400000)); // no wrap into the low firmware aperture
        reset_counters();
        CHECK(ArmSmmu4KLiveUpdateContextRanges(&io,0,&context,&lower,0,0,
            &visibility,&r,1,0,4,&result)==ArmSmmu4KSuccess);
        CHECK(result.complete && result.translation_removed && !pte(va));
        CHECK(f.tlbi_calls==1 && f.sync_calls==1 && !state.tables.leaf_pages);
        ++tested;
    }
    CHECK(ArmSmmu4KLiveAudit(&arena,&state,0,0,&result)==ArmSmmu4KSuccess);
    printf("PASS %u high-window endpoints, 4 GiB live topology, WB PTEs, unmap/TLB and old-budget rejection\n",tested);
}
'''
    # Compile as C++ for shared enum constants, C production units separately.
    source = out/'aperture.cpp'; source.write_text(fixture, newline='\n')
    objects=[]
    for stem in ['ArmSmmu4K','ArmSmmu4KAudit','ArmSmmu4KContext','ArmSmmu4KLive','ArmSmmu4KProgram']:
        obj=out/(stem+'.o'); objects.append(host_path(obj))
        subprocess.run(host_command(['clang','-std=c11','-O1','-g','-fsanitize=address,undefined',
            '-I'+host_path(gpu),'-c',host_path(gpu/(stem+'.c')),'-o',host_path(obj)]),check=True)
    exe=out/'aperture'
    subprocess.run(host_command(['clang++','-std=c++17','-O1','-g','-fsanitize=address,undefined',
        '-I'+host_path(gpu),'-I'+host_path(ROOT/'patches/nabu-gpu'),
        host_path(source),*objects,'-o',host_path(exe)]),check=True)
    result=subprocess.run(host_command([host_path(exe)]),capture_output=True,check=True)
    (out/'aperture.log').write_bytes(result.stdout+result.stderr)
    return result.stdout.decode().strip()


if __name__ == '__main__':
    main()
