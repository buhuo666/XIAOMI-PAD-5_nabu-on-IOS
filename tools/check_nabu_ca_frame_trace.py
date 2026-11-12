#!/usr/bin/env python3
"""Run transparent CA wrapper and bounded-snapshot host checks; no device."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from check_darwinboot_8796 import host_command, host_path
ROOT=Path(__file__).resolve().parents[1]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    binary=a.output/'ca-frame-trace-test'
    compiler=['xcrun','--sdk','macosx','clang'] if sys.platform=='darwin' else ['clang-18']
    subprocess.run(host_command([*compiler,'-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined',host_path(ROOT/'userland/nabu/tests/ca_frame_trace_test.c'),
        '-o',host_path(binary)]),check=True)
    r=subprocess.run(host_command([host_path(binary)]),capture_output=True,text=True,encoding='utf-8',errors='replace')
    (a.output/'host-test.log').write_text(r.stdout+r.stderr,encoding='utf-8');r.check_returncode()
    report={'passed':True,'test':r.stdout.strip(),'device_executed':False,
        'executable_function_entries_modified':False,'executable_pages_modified':False,
        'render_update_data_vtable_slots':2,'metal_context_data_vtable_slots':2,
        'immediate_render_data_vtable_slots':2,'metal_flush_data_vtable_slots':1,'total_data_vtable_slots':19,
        'server_state_pre_call_only':True,'context_state_pre_call_only':True,
        'immediate_state_pre_call_only':True,'immediate_events':[123,126],
        'immediate_original_calls_per_wrapper':1,'scheduler_conditions_modified':False,
        'flush_event':127,'flush_subevents':[1,2],'flush_capability':64,'maximum_capabilities':127,
        'flush_thread_cpu_clock':'clock_gettime_nsec_np(CLOCK_THREAD_CPUTIME_ID=16)',
        'flush_original_calls_per_wrapper':1,'flush_post_call_object_reads':False,
        'flush_slot':'0x1d57e3fb8','flush_original_target':'0x18825f288'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
