"""Run retained whole-protocol/ABI and queue regressions on this final source."""
from pathlib import Path
import json,subprocess,sys,platform
H=Path(__file__).resolve().parent;R=H.parents[4];OLD=R/'analysis/weather-WTH326/metal-r16/ci';SOURCE=H/'source'
OUT=R/'artifacts/nabu-metal-callback-pool-WTH326-r17';OUT.mkdir(parents=True,exist_ok=True)
report=dict(status='running',host=platform.platform(),architecture=platform.machine(),source=str(SOURCE),checks=[])
def run(cmd,name):
 r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,timeout=600);text=r.stdout+r.stderr
 (OUT/(name+'.log')).write_text(text);report['checks'].append(dict(name=name,code=r.returncode));print(text[-6000:],flush=True);(OUT/'global-report.json').write_text(json.dumps(report,indent=2)+'\n');return r.returncode==0
good=run([sys.executable,OLD/'run_runtime_abi.py','--source',SOURCE,'--expected',OLD/'expected-methods.json','--out',OUT/'runtime-abi'],'runtime-abi')
good=run([sys.executable,OLD/'run_protocol_regression.py','--baseline-source',OLD/'baseline-frontend','--fixed-source',SOURCE,'--out',OUT/'protocols'],'protocols') and good
good=run([sys.executable,H/'run_callback_pool.py','--baseline',OLD/'frontend','--fixed',SOURCE,'--out',OUT/'callback-pool'],'callback-pool') and good
# The retained 39 status/ordering assertions, with the final production methods.
generator=H/'generate_status_test.py';queue=OUT/'final-queue.mm'
prepared=run([sys.executable,generator,SOURCE/'NativeBridgeMetalFrontend.mm',queue],'queue-extract')
if prepared:
 text=queue.read_text();needle='struct NabuMetalSubmitSpan {template<class... A>NabuMetalSubmitSpan(A...) {}};'
 assert text.count(needle)==1
 text=text.replace(needle,needle+'\nstruct NabuMetalLifetimeSpan {template<class... A>NabuMetalLifetimeSpan(A...) {}};')
 queue.write_text(text)
 compiled=run(['xcrun','clang++','-std=c++17','-fobjc-arc','-fblocks','-O2','-framework','Foundation','-framework','Metal','-Wall','-Wextra','-Werror',queue,'-o',OUT/'final-queue'],'queue-compile')
 good=compiled and good
 if compiled:good=run([OUT/'final-queue'],'queue-runtime') and good
else:good=False
good=run([sys.executable,H/'test_lifetime_trace.py'],'lifetime-transport-parser') and good
report['status']='passed' if good else 'failed';(OUT/'global-report.json').write_text(json.dumps(report,indent=2)+'\n');raise SystemExit(not good)
