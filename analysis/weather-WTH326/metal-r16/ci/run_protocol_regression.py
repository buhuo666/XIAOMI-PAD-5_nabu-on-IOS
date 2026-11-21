"""Build actual r15/r16 frontend bundles and test public protocol identity on Mac.

No CI submission, hardware, or GPU work. The device probe uses production
protocol registration and donor IMPs, with no runtime/driver creation.
"""
from pathlib import Path
import argparse
import json
import platform
import subprocess
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--baseline-source',type=Path,required=True)
parser.add_argument('--fixed-source',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
if sys.platform!='darwin':raise SystemExit('Actual Objective-C runtime tests require macOS.')
HERE=Path(__file__).resolve().parent
args.out.mkdir(parents=True,exist_ok=True)
args.out=args.out.resolve()
report=dict(status='running',host=platform.platform(),architecture=platform.machine(),checks=[],gpu_executed=False,original_mps_executed=False)

def run(command,name):
    result=subprocess.run(list(map(str,command)),capture_output=True,text=True,timeout=180)
    output=result.stdout+result.stderr
    (args.out/(name+'.log')).write_text(output)
    report['checks'].append(dict(name=name,command=list(map(str,command)),returncode=result.returncode))
    (args.out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(output[-16000:],end='',flush=True)
    return result.returncode,output.strip()

code,sdk=run(['xcrun','--sdk','macosx','--show-sdk-path'],'sdk')
if code:raise SystemExit(code)
base=['xcrun','--sdk','macosx','clang++','-target','arm64-apple-macos14.0','-isysroot',sdk,
      '-std=c++17','-fobjc-arc','-fblocks','-O1','-g','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations']
binary=args.out/'protocol-runtime'
code,_=run(base+[HERE/'protocol_runtime.mm','-I',HERE,'-framework','Foundation','-framework','Metal','-o',binary],'test-compile')
if code:raise SystemExit(code)
good=True
for variant,source in [('baseline',args.baseline_source.resolve()),('fixed',args.fixed_source.resolve())]:
    fixed=variant=='fixed'
    wrapper=args.out/(variant+'-wrapper.mm')
    wrapper.write_text('''#include "NativeBridgeMetalFrontend.mm"
extern "C" Class nabu_test_install_protocols() {
'''+(' nabuInstallPublicMetalProtocols();nabuInstallPublicMetalProtocols();\n' if fixed else '')+'''
 Class cls=objc_allocateClassPair([NSObject class],"NBProtocolDeviceProbe",0);
 unsigned count=0;Method *methods=class_copyMethodList([NBDeviceMethods class],&count);
 for(unsigned i=0;i<count;i++)class_addMethod(cls,method_getName(methods[i]),method_getImplementation(methods[i]),method_getTypeEncoding(methods[i]));
 free(methods);
'''+(' nabuInstallDeviceMetalProtocols(cls);\n' if fixed else ''' class_addProtocol(cls,@protocol(MTLDevice));
 if(Protocol *spi=objc_getProtocol("MTLDeviceSPI"))class_addProtocol(cls,spi);
''')+''' objc_registerClassPair(cls);return cls;
}
''')
    bundle=args.out/(variant+'.bundle')
    code,_=run(base+['-I',source,'-bundle','-Wl,-undefined,dynamic_lookup',wrapper,
              '-framework','Foundation','-framework','Metal','-framework','IOSurface','-o',bundle],variant+'-compile')
    if code:good=False;continue
    output=args.out/(variant+'-report.json')
    code,_=run([binary,bundle,HERE/'protocol-manifest.json',variant,output],variant+'-runtime')
    if not output.exists():good=False;continue
    actual=json.loads(output.read_text())
    expected=(code==0 and actual['failure_count']==0 and actual['mps_public_protocol_gate']) if fixed else (
        code==2 and actual['failure_count']==55 and actual['missing_class_conformance']==28 and
        actual['missing_instance_conformance']==27 and not actual['mps_public_protocol_gate'])
    expected=expected and actual['root_class_checks']==30 and actual['required_method_abi_checks']==576 and actual['typed_binding_checks']==44 and actual['native_class_wrapper_checks']==11
    report['checks'][-1]['expected_result']=expected
    good=good and expected
report['status']='passed' if good else 'failed'
(args.out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(not good)
