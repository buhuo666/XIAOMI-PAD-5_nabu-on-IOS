"""Full frontend macOS callback ownership baseline/candidate regression."""
from pathlib import Path
import argparse,json,platform,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--baseline',type=Path,required=True);p.add_argument('--fixed',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
H=Path(__file__).resolve().parent;a.out.mkdir(parents=True,exist_ok=True);a.out=a.out.resolve()
report=dict(status='running',host=platform.platform(),architecture=platform.machine(),checks=[],full_frontend=True,rust_backend=False,gpu_executed=False,native_mps_executed=False)
def run(cmd,name):
 r=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,timeout=180);s=r.stdout+r.stderr
 (a.out/(name+'.log')).write_text(s);report['checks'].append(dict(name=name,code=r.returncode));(a.out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(s[-5000:],flush=True);return r.returncode,s
code,sdk=run(['xcrun','--sdk','macosx','--show-sdk-path'],'sdk');assert code==0
base=['xcrun','--sdk','macosx','clang++','-target','arm64-apple-macos14.0','-isysroot',sdk.strip(),'-std=c++17','-fobjc-arc','-fblocks','-O2','-g','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations']
code,_=run(['xcrun','--sdk','macosx','clang','-target','arm64-apple-macos14.0','-fno-objc-arc','-O2','-c',H/'callback_pool_mrc.m','-o',a.out/'mrc.o'],'mrc-compile');assert code==0
code,_=run(base+[H/'callback_pool_driver.mm','-framework','Foundation','-o',a.out/'driver'],'driver-compile');assert code==0
good=True
for variant,source in [('baseline',a.baseline),('fixed',a.fixed)]:
 bundle=a.out/(variant+'.bundle')
 code,_=run(base+['-I',source.resolve(),'-bundle','-Wl,-undefined,dynamic_lookup',H/'callback_pool_wrapper.mm',a.out/'mrc.o','-framework','Foundation','-framework','Metal','-framework','IOSurface','-o',bundle],variant+'-compile')
 if code:good=False;continue
 for kind in ['scheduled','completed','dispatch','deallocator','event']:
  code,output=run([a.out/'driver',bundle,kind],variant+'-'+kind)
  expected=f'callbacks=1 alive_before_thread_exit={1 if variant=="baseline" else 0} releases_before_thread_exit={0 if variant=="baseline" else 1}'
  passed=code==0 and expected in output;report['checks'][-1]['expected_observation']=passed;good=good and passed
report['status']='passed' if good else 'failed';(a.out/'report.json').write_text(json.dumps(report,indent=2)+'\n');raise SystemExit(not good)
