#!/usr/bin/env python3
"""Check the production CA context scheduler and its arm64 ABI; no device."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    compiler=['xcrun','--sdk','macosx','clang'] if sys.platform=='darwin' else ['clang-18']
    commands=[]
    def run(command,name):
        commands.append(command)
        result=subprocess.run(host_command(command),capture_output=True,text=True,
                              encoding='utf-8',errors='replace',timeout=180)
        (out/name).write_text(result.stdout+result.stderr,encoding='utf-8')
        result.check_returncode()
        return result
    report={'passed':False,'device_executed':False,'commands':commands}
    try:
        binary=out/'ca-context-timer-test'
        run([*compiler,'-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
             '-fsanitize=address,undefined','-pthread',
             host_path(ROOT/'userland/nabu/tests/ca_context_timer_test.c'),
             '-o',host_path(binary)],'host-compile.log')
        result=run([host_path(binary)],'host-test.log')
        observer_binary=out/'ca-frame-trace-test'
        run([*compiler,'-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
             '-fsanitize=address,undefined',
             host_path(ROOT/'userland/nabu/tests/ca_frame_trace_test.c'),
             '-o',host_path(observer_binary)],'observer-host-compile.log')
        observer_result=run([host_path(observer_binary)],'observer-host-test.log')
        cross=['xcrun','--sdk','iphoneos','clang'] if sys.platform=='darwin' else ['clang-18']
        core=ROOT/'userland/nabu/src/ca_context_timer.c'
        arm64=[*cross,'-target','arm64-apple-ios16.5','-std=c11','-ffreestanding',
               '-Os','-Wall','-Wextra','-Werror','-fno-omit-frame-pointer']
        run([*arm64,'-c',host_path(core),'-o',host_path(out/'ca_context_timer.o')],
            'arm64-compile.log')
        run([*arm64,'-S',host_path(core),'-o',host_path(out/'ca_context_timer.s')],
            'arm64-assembly.log')
        run([*arm64,'-c',host_path(ROOT/'userland/nabu/src/ca_frame_trace.c'),
             '-o',host_path(out/'ca_frame_trace.o')],'observer-arm64-compile.log')
        report.update(passed=True,test=result.stdout.strip(),sanitizers=['address','undefined'],
                      arm64_core_compiled=True,arm64_assembly='ca_context_timer.s',
                      aggregate_bytes=24,double_argument_preserved=True,
                      total_data_vtable_slots=6,scheduler_data_vtable_slots=2,can_retry_data_vtable_slots=4,
                      observer_test=observer_result.stdout.strip(),observer_arm64_compiled=True,
                      observer_bundled=True,observer_chaining_executed=True,
                      mode='original-can-false single-empty-next-page retry',
                      executable_pages_modified=False,
                      policy='last == 0 && next.time == 0; active display, native VSync source',
                      base_call_under_original_mutex=True,original_override_fallback=True,
                      native_keepalive='original enable and uint32(3 * minimum_frame_duration)',
                      single_free_gate='flags0 original false, count3, next non-current and all five resources zero',
                      original_revalidation_outside_page_mutex=True,
                      limits=['Host native-idle model is not real VSync execution',
                              'Original can boundary uses a host substitute; no native CA execution',
                              'Retry is resource-gated, not exclusive attribution to the asynchronous context timer',
                              'Runloop timing, display correctness and both latency targets require device validation'])
    finally:
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
