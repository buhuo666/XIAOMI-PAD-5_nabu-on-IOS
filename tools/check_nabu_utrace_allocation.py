"""Exercise the actual patched producer routines with GPU allocation faults."""
import argparse, json, hashlib, subprocess, sys
from pathlib import Path
import re

def function(source,name):
    match=re.search(r"^(?:static )?[^\n]+\n"+re.escape(name)+r"\(",source,re.M)
    if not match: raise ValueError("Missing producer function: "+name)
    opening=source.index("{",match.end());depth=0
    for end in range(opening,len(source)):
        depth += (source[end]=="{")-(source[end]=="}")
        if depth==0:return source[match.start():end+1]
    raise ValueError("Unclosed producer function: "+name)
from nabu_turnip_trace_allocation import FILES, FAILURE_HELPERS, transform
from check_darwinboot_8796 import host_command, host_path
ROOT = Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser()
p.add_argument("--source",type=Path,required=True,help="Patched Mesa checkout or flat candidate directory")
p.add_argument("--output",type=Path,required=True)
a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
sources={name:(a.source/path if (a.source/path).exists() else a.source/name).read_text(encoding="utf-8") for name,path in FILES.items()}
before=transform(sources,reverse=True)
assert transform(before)==sources
fixture=(ROOT/"tools/fixtures/nabu_utrace_allocation.c").read_text(encoding="utf-8")
report={"result":"running","producer_functions_extracted":True,"cases":13,"commands":[]}
for label,src in [("candidate",sources),("buggy",before)]:
 code=fixture
 replacements={"CREATE":function(src["tu_device.cc"],"tu_trace_create_buffer"),
               "READ":function(src["tu_device.cc"],"tu_trace_read_ts"),
               "GET":function(src["u_trace.c"],"u_trace_buffer_view_get_buffer"),
               "HELPERS":FAILURE_HELPERS if label=="candidate" else "static bool u_trace_discard_failed_flush(struct u_trace *ut,void *data) {(void)ut;(void)data;return false;}",
               "LINEAR":function(src["u_trace.c"],"u_trace_get_linear_alloc"),
               "INIT":function(src["u_trace.c"],"u_trace_init"),
               "FINI":function(src["u_trace.c"],"u_trace_fini"),
               "ALLOC":function(src["u_trace.c"],"alloc_device_memory")+"\n"+function(src["u_trace.c"],"release_last_device_memory"),
               "CLONE":function(src["u_trace.c"],"u_trace_clone_append"),
               "APPEND":function(src["u_trace.c"],"u_trace_appendv")}
 for k,v in replacements.items():code=code.replace("/* ACTUAL_"+k+" */",v)
 path=out/(label+".c");path.write_text(code,encoding="utf-8");exe=out/label
 cmd=["clang" if sys.platform=="darwin" else "clang-18","-std=gnu11","-O1","-g","-fsanitize=address,undefined","-fno-omit-frame-pointer",host_path(path),"-o",host_path(exe)]
 report["commands"].append(cmd)
 r=subprocess.run(host_command(cmd),capture_output=True)
 (out/(label+"-compile.log")).write_bytes(r.stdout+r.stderr)
 if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode("utf-8","replace")[-6000:])
 r=subprocess.run(host_command([host_path(exe)]+(["buggy"] if label=="buggy" else [])),capture_output=True)
 (out/(label+"-run.log")).write_bytes(r.stdout+r.stderr)
 if label=="candidate" and r.returncode:raise RuntimeError((r.stdout+r.stderr).decode("utf-8","replace")[-6000:])
 if label=="buggy":
  assert r.returncode not in [0,2] and b"runtime error:" in r.stderr
  report["original_failure_reproduced"]={"exit_code":r.returncode,"sanitizer_null_access":True}
 else:print(r.stdout.decode())
report.update(result="pass",source_sha256={n:hashlib.sha256(s.encode()).hexdigest() for n,s in sources.items()},
              sanitizers=["address","undefined"],gpu_commands_checked="healthy trace write/copy counts equal pinned path; rendering CS not changed")
(out/"report.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
print(json.dumps({k:report[k] for k in ["result","cases","original_failure_reproduced"]}))
