"""Reproduce the orphaned queue using actual production worker code."""
import argparse,json,subprocess,sys
from pathlib import Path
from check_darwinboot_8796 import host_command,host_path
from nabu_trace_close import transform
R=Path(__file__).resolve().parents[1]
def part(s,a,b):return s[s.index(a):s.index(b,s.index(a))]
def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    original=a.source.read_text();fixed='Appends can finish after the last send' in original
    sources={'old':transform(original,True) if fixed else original,'fixed':original if fixed else transform(original)}
    out=a.output;out.mkdir(parents=True,exist_ok=False);reports=[]
    for name,source in sources.items():
        o=out/name;o.mkdir()
        (o/'production_types.inc').write_text(part(source,'enum {\n   TRACE_QUEUE_EVENTS','static uint64_t trace_next_command;')+part(source,'/* tu_darwin_trace_queue','static tu_darwin_trace_state *\ntrace_state'))
        core=part(source,'static uint64_t\ntrace_thread_cpu_ns()','static void\ntrace_append(tu_darwin_trace_state')+part(source,'static void\ntrace_send(','\nvoid\ntu_darwin_trace_init')
        (o/'production_core.inc').write_text(core)
        for mode,flags in [('release',['-O2']),('sanitized',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
            binary=o/mode;cmd=['clang++','-std=c++17','-Wall','-Wextra','-Werror','-pthread',*flags,'-DEXPECT_STEADY_DRAIN=1','-DEXPECT_COALESCED_WAKE=1','-DEXPECT_SUMMARY_RECORDS=4','-DEXPECT_CLOSE_FIX='+str(int(name=='fixed')),'-I'+host_path(o),'-I'+host_path(a.source.parent),host_path(R/'tools/fixtures/nabu_trace_close.cpp'),'-o',host_path(binary)]
            for step,c in [('compile',cmd),('run',[host_path(binary)])]:
                r=subprocess.run(host_command(c),capture_output=True,timeout=90);(o/(mode+'-'+step+'.log')).write_bytes(r.stdout+r.stderr)
                if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
            diagnostic=r.stderr[r.stderr.find(b'close_fix='):].decode(errors='replace').strip()
            reports.append(dict(version=name,mode=mode,**json.loads(r.stdout),race_replays=12,idle_diagnostic=diagnostic))
    report=dict(passed=True,source=str(a.source),results=reports,old_bug_reproduced=True,candidate_no_orphan=True,device_executed=False,scope='Real worker/append/close functions; host transport controlled at close boundary')
    (out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
if __name__=='__main__':main()
