#!/usr/bin/env python3
"""Compile and exercise the native filesystem probe on Linux, without a device.

Uses two names for one real directory. Darwin-only checks remain explicitly
not_run; this validates the probe, not Nabu's kernel or mount implementation.
"""
import argparse
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    runner = out / 'main.c'
    runner.write_text('''#include "jailbreak_fs_probe.h"
int main(int argc, char **argv) {
    int child=nabu_jailbreak_fs_probe_child(argc,argv);
    if (child>=0) return child;
    if (argc!=4) return 64;
    return nabu_jailbreak_fs_probe(argv[1],argv[2],argv[3]);
}
''')
    source = ROOT / 'userland/nabu/src'
    binary = out / 'fs-probe'
    command = ['clang-18', '-std=gnu11', '-g', '-O1', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               '-I' + host_path(source), host_path(source / 'jailbreak_fs_probe.c'),
               host_path(runner), '-o', host_path(binary)]
    compiled = subprocess.run(host_command(command), capture_output=True, text=True, encoding='utf-8', errors='replace')
    (out / 'compile.log').write_text(compiled.stdout + compiled.stderr, encoding='utf-8')
    if compiled.returncode:
        raise RuntimeError(compiled.stdout + compiled.stderr)
    harness = out / 'run.py'
    harness.write_text('''import json, pathlib, subprocess, sys, tempfile
binary=pathlib.Path(sys.argv[1])
out=pathlib.Path(sys.argv[2])
summary={"device_executed":False,"scope":"Linux probe behavior only", "cases":[]}
with tempfile.TemporaryDirectory(prefix="nabu-fs-probe-host-") as temporary:
    root=pathlib.Path(temporary)
    lower=root/"lower"; lower.mkdir()
    upper=root/"upper"; upper.symlink_to(lower,target_is_directory=True)
    report=out/"same-vnode.json"
    run=subprocess.run([str(binary),str(lower),str(upper),str(report)],capture_output=True,text=True,timeout=60)
    (out/"run.log").write_text(run.stdout+run.stderr)
    data=json.loads(report.read_text())
    assert run.returncode==2, (run.returncode,run.stderr,data)
    assert data["failed"]==0 and data["all_executed_passed"] and not data["all_target_checks_passed"], data
    skips={row["name"] for row in data["checks"] if row["passed"] is None}
    expected={"rename_swap","explicit_readonly_bind_mount"}
    if data["euid"]!=0: expected.add("chown_cross_alias")
    assert skips==expected, skips
    assert not list(lower.iterdir()), list(lower.iterdir())
    summary["cases"].append({"name":"same-vnode-aliases","executed_passed":len(data["checks"])-len(skips),"not_run":sorted(skips),"cleanup":True})
    other=root/"other"; other.mkdir()
    report=out/"wrong-alias.json"
    run=subprocess.run([str(binary),str(other),str(upper),str(report)],capture_output=True,text=True,timeout=10)
    data=json.loads(report.read_text())
    assert run.returncode==1 and data["failed"]==1 and not data["all_target_checks_passed"],data
    assert not list(lower.iterdir()) and not list(other.iterdir())
    summary["cases"].append({"name":"mismatched-alias-reported","cleanup":True})
(out/"host-check.json").write_text(json.dumps(summary,indent=2)+"\\n")
print(json.dumps(summary))
''')
    ran = subprocess.run(host_command(['python3', host_path(harness), host_path(binary), host_path(out)]),
                         capture_output=True, text=True, encoding='utf-8', errors='replace')
    (out / 'harness.log').write_text(ran.stdout + ran.stderr, encoding='utf-8')
    if ran.returncode:
        raise RuntimeError(ran.stdout + ran.stderr)
    print(ran.stdout.strip())


if __name__ == '__main__':
    main()
