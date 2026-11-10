#!/usr/bin/env python3
"""Compare the production copied-buffer merge with its byte contract and baseline."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
use std::ptr::NonNull;
use std::hint::black_box;
use std::time::Instant;
mod candidate { include!("candidate.rs"); }
mod baseline { use std::ptr::NonNull; include!("baseline.rs"); }
type Sync = unsafe fn(NonNull<u8>, NonNull<u8>, &mut [u8], bool) -> u64;
fn pointer(p: *mut u8) -> NonNull<u8> { NonNull::new(p).unwrap() }
fn main() {
    // The independent contract works one byte at a time over disjoint buffers.
    let mut cases = 0;
    for length in 0..130 {
        for offset in 0..8 {
            for mode in 0..8 {
                for keep in [false, true] {
                    let mut from = vec![0xa5u8; length+32];
                    let mut to = vec![0x5au8; length+32];
                    let mut snapshot = vec![0x17u8; length+32];
                    let start = offset+8;
                    for i in 0..length {
                        let old = (i*37+11) as u8;
                        snapshot[start+i] = old;
                        from[start+i] = if mode&1!=0 || i%3==0 { old.wrapping_add(1) } else { old };
                        to[start+i] = if mode&2!=0 && i%2==0 { old.wrapping_add(2) } else { old };
                        if mode&4!=0 { from[start+i] ^= 0x80; }
                    }
                    let mut expected = to.clone();
                    let mut agreed = snapshot.clone();
                    let mut moved = 0;
                    for i in start..start+length {
                        if from[i]!=snapshot[i] {
                            if !keep || to[i]==snapshot[i] { expected[i]=from[i]; moved+=1; }
                            agreed[i]=from[i];
                        }
                    }
                    let count = unsafe { candidate::sync(pointer(from.as_mut_ptr().add(start)),
                        pointer(to.as_mut_ptr().add(start)), &mut snapshot[start..start+length], keep) };
                    assert_eq!((to,snapshot,count), (expected,agreed,moved));
                    cases += 1;
                }
            }
        }
    }
    // Also preserve the baseline's chunk snapshot behavior for overlapping views.
    for length in 1..80 {
        for delta in 0..8 {
            for keep in [false,true] {
                let original: Vec<u8> = (0..length+32).map(|i|(i*17) as u8).collect();
                let mut a=original.clone(); let mut b=original;
                let mut sa=vec![17u8;length];let mut sb=sa.clone();
                let ca=unsafe{baseline::sync(pointer(a.as_mut_ptr().add(8)),pointer(a.as_mut_ptr().add(8+delta)),&mut sa,keep)};
                let cb=unsafe{candidate::sync(pointer(b.as_mut_ptr().add(8)),pointer(b.as_mut_ptr().add(8+delta)),&mut sb,keep)};
                assert_eq!((a,sa,ca),(b,sb,cb));cases+=1;
            }
        }
    }
    candidate::profile_finish(false,candidate::profile_start(),0,0);
    println!("CASES {}",cases);
    let bytes=16*1024*1024;
    for mode in ["unchanged","bgra_changed","sparse","cpu_conflict"] {
        for (name,sync) in [("baseline",baseline::sync as Sync),("candidate",candidate::sync as Sync)] {
            let mut from=vec![0u8;bytes];let mut to=vec![0u8;bytes];let mut snapshot=vec![0u8;bytes];
            for i in 0..bytes {
                from[i]=match mode {"unchanged"=>0,"sparse"=>u8::from(i%4096==0),_=>u8::from(i%4!=3)};
            }
            let mut times=Vec::new();let mut moved=0;
            for _ in 0..9 {
                snapshot.fill(0);to.fill(if mode=="cpu_conflict" {2} else {0});
                let before=Instant::now();
                moved=unsafe {black_box(sync)(pointer(black_box(from.as_mut_ptr())),pointer(black_box(to.as_mut_ptr())),black_box(&mut snapshot),true)};
                times.push(before.elapsed().as_nanos());
                black_box((&from,&to,&snapshot,moved));
            }
            times.sort();println!("BENCH {} {} {} {} {}",mode,name,bytes,times[4],moved);
        }
    }
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage-only', action='store_true')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = (ROOT/'src/metal2vulkan/crates/metal2vulkan-runtime/src/copied.rs').read_text(encoding='utf-8')
    first = source.index('pub(crate) unsafe fn sync(')
    last = source.index('/// Read the caller', first)
    (out/'baseline.rs').write_text(source[first:last], encoding='utf-8', newline='\n')
    candidate = (ROOT/'patches/nabu-metal/NativeCopiedSync.rs').read_text(encoding='utf-8')
    (out/'candidate.rs').write_text(candidate, encoding='utf-8', newline='\n')
    (out/'main.rs').write_text(HARNESS, encoding='utf-8', newline='\n')
    report = {'result': 'staged_not_run', 'gpu_verified': False}
    if not args.stage_only:
        exe = out/'copied-sync-check'
        subprocess.run(['rustc', '+1.98.1', '--edition=2024', '-Dwarnings', '-Copt-level=3',
                        '-Ccodegen-units=1', str(out/'main.rs'), '-o', str(exe)], check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True, check=True)
        (out/'test.stdout').write_text(result.stdout)
        (out/'test.stderr').write_text(result.stderr)
        timings = {}
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts[0] == 'CASES':
                report['cases'] = int(parts[1])
            elif parts[0] == 'BENCH':
                _, mode, name, size, ns, moved = parts
                timings.setdefault(mode, {})[name] = dict(bytes=int(size), median_ms=int(ns)/1e6, moved=int(moved))
        for row in timings.values():
            assert row['baseline']['moved'] == row['candidate']['moved']
            row['speedup'] = row['baseline']['median_ms']/row['candidate']['median_ms']
        report.update(result='pass', timings=timings, scope='Release host CPU comparisons; GPU/display performance unverified')
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
