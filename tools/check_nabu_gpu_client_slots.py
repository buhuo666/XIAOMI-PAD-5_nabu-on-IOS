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
    context = (ROOT/'src/nabu/gpu/a640/NativeAdrenoGpuContext.h').read_text()
    abi = (ROOT/'src/nabu/gpu/upstream/Adreno6xx/NativeAdrenoABI.h').read_text()
    # Use the shipped backend's actual firmware/ring addresses and queue width.
    constants = '\n'.join(re.findall(r'enum : (?:uint64_t|size_t) \{.*?\};', context, re.S))
    queues = int(re.search(r'NativeAdrenoAbiMaxQueues = (\d+)', abi)[1])
    source = out/'client-slots.cpp'
    source.write_text('#include <cstddef>\n#include <cassert>\n#include <cstdio>\n'
        '#include "NabuGpuClientSlots.h"\n'+constants+r'''
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
    puts("PASS eight isolated clients; GPU180 launch order; saturation and reuse; A640 firmware/GMEM/ring excluded");
}
'''+f'\nstatic_assert(NabuGpuMaxClients*{queues}<=256,"scheduler queues");\n',
        encoding='utf-8', newline='\n')
    exe = out/'client-slots'
    subprocess.run(host_command(['clang++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-I'+host_path(ROOT/'patches/nabu-gpu'),
        host_path(source), '-o', host_path(exe)]), check=True)
    result = subprocess.run(host_command([host_path(exe)]), capture_output=True, check=True)
    (out/'test.log').write_bytes(result.stdout+result.stderr)
    report = {'passed': True, 'clients': 8, 'queues_per_client': queues,
        'test_output': result.stdout.decode().strip(),
        'scope': 'Production slot/address policy with ASan/UBSan; no device execution'}
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
