#!/usr/bin/env python3
"""Check the benchmark's real completion join and keep CPU timings distinct from display FPS."""
import argparse
import json
from pathlib import Path
import subprocess

from analyze_nabu_frame_bench import analyze
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include "FrameCompletion.h"
#include <atomic>
#include <cassert>
#include <thread>
#include <vector>
using namespace NabuFrameCompletion;
int main() {
    for(bool completionFirst:{false,true}) {
        uint32_t state=0;assert(!claim(state));
        publish(state,completionFirst?CommandCompleted:CommitReturned);assert(!claim(state));
        publish(state,completionFirst?CommitReturned:CommandCompleted);assert(claim(state));assert(!claim(state));
    }
    for(unsigned round=0;round<1000;++round) {
        uint32_t state=0;uint64_t committed=0,completed=0;std::atomic<unsigned> claims{0};
        std::thread first([&]{committed=11;publish(state,CommitReturned);});
        std::thread second([&]{completed=22;publish(state,CommandCompleted);});
        std::thread observer([&]{while(!claim(state))std::this_thread::yield();assert(committed==11&&completed==22);++claims;});
        first.join();second.join();observer.join();assert(claims==1&&!claim(state));
    }
}
'''


def check_analysis():
    for fps in (10, 120):
        metadata = {'sample_start_s': 10, 'sample_end_s': 11, 'width': 1600, 'height': 2560,
                    'stopped_s': 11.001, 'benchmark_revision': 3,
                    'run_id': 'synthetic', 'scene': 'opaque_motion', 'repetition': 1, 'target_hz': 120,
                    'result': 'captured_not_display_qualified', 'frames_submitted': fps, 'commands_completed': fps,
                    'admission_skips': 120-fps, 'display_link_callbacks': 120}
        rows = []
        for i in range(fps):
            t = 10 + (i + .5) / fps
            rows.append(dict(frame=i, measured=1, callback_s=t, acquire_begin_s=t,
                             acquire_end_s=t+.001, submit_s=t+.002, commit_return_s=t+.0021,
                             completed_s=t+.004, status=4))
        result = analyze(metadata, rows)
        assert result['app_submit_rate'] == fps and result['display_fps'] is None and result['pure_gpu_ms'] is None
        assert result['metrics']['submit_to_completion_observed']['p95_ms'] < 2.001
        assert result['valid_performance_run'] and result['complete_interval']
        historical = analyze(dict(metadata, benchmark_revision=1), rows)
        assert historical['app_submit_rate'] is None and not historical['valid_performance_run']
        partial_rows = [r for r in rows if r['callback_s'] < 10.25]
        partial = analyze(dict(metadata, stopped_s=10.25, result='failed',
                               frames_submitted=len(partial_rows), commands_completed=len(partial_rows)), partial_rows)
        assert partial['app_submit_rate'] is None and not partial['complete_interval']
        assert partial['duration_s'] == .25 and partial['requested_duration_s'] == 1
        assert partial['diagnostic_observed_submit_rate'] == len(partial_rows) / .25
        warmup_failure = analyze(dict(metadata, stopped_s=9.8, result='failed',
                                      frames_submitted=0, commands_completed=0), [])
        assert warmup_failure['duration_s'] == 0 and warmup_failure['app_submit_rate'] is None
        assert warmup_failure['diagnostic_observed_submit_rate'] is None
        for bad in (rows + [rows[0]], [dict(row, submit_s=0) if i == 0 else row for i, row in enumerate(rows)]):
            try: analyze(metadata, bad)
            except ValueError: pass
            else: raise AssertionError('Invalid/missing rows were accepted')


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    check_analysis()
    source = out/'completion.cpp'; source.write_text(HARNESS); binary = out/'completion'
    command = ['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
               '-I'+host_path(ROOT/'userland/nabu/apps/FrameBench'), host_path(source), '-o', host_path(binary)]
    for name, argv in [('compile',command), ('run',[host_path(binary)])]:
        result = subprocess.run(host_command(argv), capture_output=True, timeout=120)
        (out/(name+'.log')).write_bytes(result.stdout+result.stderr)
        if result.returncode: raise RuntimeError((result.stdout+result.stderr).decode(errors='replace')[-4000:])
    report = {'passed': True, 'completion_join_orders': 2, 'concurrent_completion_rounds': 1000,
              'analysis_cpu_only_scope_checked': True, 'device_executed': False}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n'); print(json.dumps(report))


if __name__ == '__main__': main()
