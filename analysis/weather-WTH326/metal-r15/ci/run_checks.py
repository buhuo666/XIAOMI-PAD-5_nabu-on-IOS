"""Unified real Mac runtime and production-extracted queue verification."""
from pathlib import Path
import json,platform,subprocess,sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'artifacts/nabu-metal-checks-WTH326-r15';OUT.mkdir(parents=True,exist_ok=True)
report=dict(status='running',host=platform.platform(),architecture=platform.machine(),checks=[],gpu_executed=False)
def run(command,name,timeout=300):
    result=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=timeout)
    (OUT/(name+'.log')).write_text(result.stdout+result.stderr)
    report['checks'].append(dict(name=name,returncode=result.returncode,command=list(map(str,command))))
    print((result.stdout+result.stderr)[-12000:],flush=True)
    (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return result.returncode==0
good=run([sys.executable,HERE/'run_runtime_abi.py','--source',HERE/'frontend','--expected',HERE/'expected-methods.json','--out',OUT/'runtime-abi'],'runtime-abi')
queue_source=OUT/'queue_behavior.mm'
prepared=run([sys.executable,HERE/'generate_queue_test.py',HERE/'frontend/NativeBridgeMetalFrontend.mm',queue_source],'queue-extract')
if prepared:
    compiled=run(['xcrun','clang++','-std=c++17','-fobjc-arc','-fblocks','-framework','Foundation','-framework','Metal','-Wall','-Wextra','-Werror',queue_source,'-o',OUT/'queue_behavior'],'queue-compile')
    good=compiled and good
    if compiled:good=run([OUT/'queue_behavior'],'queue-runtime',timeout=20) and good
else:good=False
good=run([sys.executable,HERE/'run_status_regression.py','--out',OUT/'callback-status'],'callback-status') and good
report['status']='passed' if good else 'failed'
(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(not good)
