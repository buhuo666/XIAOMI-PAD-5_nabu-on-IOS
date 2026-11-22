"""Check the actual Turnip trace worker's submission-lock and close ordering."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]

def part(source, begin, end):
    return source[source.index(begin):source.index(end, source.index(begin))]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.read_text()
    out = args.output
    out.mkdir(parents=True, exist_ok=False)
    constants = part(source, 'enum {\n   TRACE_QUEUE_EVENTS', 'static uint64_t trace_next_command;')
    structures = part(source, '/* tu_darwin_trace_queue', 'static tu_darwin_trace_state *\ntrace_state')
    (out/'production_types.inc').write_text(constants+structures)
    core = part(source, 'static void\ntrace_argument(', 'static void\ntrace_append(tu_darwin_trace_state')
    core += part(source, 'static void\ntrace_send(', '\nvoid\ntu_darwin_trace_init')
    (out/'production_core.inc').write_text(core)
    results = []
    for mode, flags in [('release',['-O2']),('sanitized',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
        binary = out / mode
        command = ['clang++','-std=c++17','-Wall','-Wextra','-Werror','-pthread',*flags,
                   '-DEXPECT_STEADY_DRAIN=1','-I'+host_path(out),'-I'+host_path(args.source.parent),
                   host_path(ROOT/'tools/fixtures/nabu_trace_worker.cpp'),'-o',host_path(binary)]
        for step, cmd in [('compile',command),('run',[host_path(binary)])]:
            result = subprocess.run(host_command(cmd),capture_output=True,timeout=90)
            (out/(mode+'-'+step+'.log')).write_bytes(result.stdout+result.stderr)
            if result.returncode:
                raise RuntimeError((result.stdout+result.stderr).decode(errors='replace'))
        results.append(dict(mode=mode,**json.loads(result.stdout)))
    report = dict(passed=True, actual_source=str(args.source), results=results,
                  scope='production worker/queue/close code with host device-control stubs',
                  device_executed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))

if __name__ == '__main__':
    main()
