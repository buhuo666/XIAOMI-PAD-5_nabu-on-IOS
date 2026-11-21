"""Sign the production iOS adapter and execute real installation paths on ARM64 macOS."""
from pathlib import Path
import json,platform,subprocess,sys
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OUT=ROOT/'artifacts/nabu-keyboard-WTH326-r18';OUT.mkdir(parents=True,exist_ok=False)
report=dict(result='running',architecture=platform.machine(),checks=[],device_executed=False,
    limitation='Host classes model Objective-C method ABI and lazy-load timing; no real UIKit layout or visual input validation.')
def run(cmd,name):
    p=subprocess.run(list(map(str,cmd)),capture_output=True,text=True,timeout=300)
    (OUT/(name+'.log')).write_text(p.stdout+p.stderr)
    report['checks'].append(dict(name=name,returncode=p.returncode));save()
    if p.returncode:raise RuntimeError(name+': '+(p.stdout+p.stderr)[-5000:])
    return p.stdout
def save():(OUT/'runtime-report.json').write_text(json.dumps(report,indent=2)+'\n')
try:
    assert platform.machine()=='arm64','Use an ARM64 runner for the production objc_msgSend aggregate ABI'
    run([sys.executable,ROOT/'tools/build_nabu_keyboard_compat.py','--output',OUT/'ios'],'ios-build-sign')
    common=['xcrun','clang','-Os','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        '-I'+str(ROOT/'userland/nabu/src')]
    host=OUT/'libnabu.keyboard.dylib'
    run([*common,'-std=gnu11','-dynamiclib',ROOT/'userland/nabu/src/keyboard_compat.c','-lobjc','-o',host],'host-adapter')
    run([*common,'-dynamiclib',HERE/'mock_uikit.m','-lobjc','-o',OUT/'mock_uikit.dylib'],'host-fixture')
    for name in ['libnabu.experience.dylib','ex.dylib']:
        run([*common,'-dynamiclib',HERE/'mock_experience.c','-lobjc','-o',OUT/name],'host-'+name)
    run([*common,HERE/'test_keyboard_runtime.c','-framework','CoreFoundation','-lobjc','-o',OUT/'runtime-test'],'host-driver')
    results=[]
    for mode in ['headless','early','late','existing-full','existing-short']:
        old='ex.dylib' if mode=='existing-short' else 'libnabu.experience.dylib'
        result=run([OUT/'runtime-test',mode,OUT/'mock_uikit.dylib',host,OUT/old],'runtime-'+mode)
        results.append(json.loads(result))
    report.update(result='passed',runtime_results=results,sanitizers=['address','undefined'])
except Exception as e:
    report.update(result='failed',error=str(e));raise
finally:save()
