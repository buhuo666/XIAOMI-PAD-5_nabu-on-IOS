"""Correct Sandbox request 4's result without changing permission decisions."""
import argparse,hashlib,json,subprocess
from pathlib import Path
def main():
    p=argparse.ArgumentParser();p.add_argument('--tree',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];patches=root/'patches/nabu-sandbox';a.output.mkdir(parents=True,exist_ok=True)
    source=a.tree/'bsd/kern/kern_minimac.c';before=source.read_text(encoding='utf8')
    old=(patches/'baseline-function.c').read_text(encoding='utf8');new=(patches/'candidate-function.c').read_text(encoding='utf8')
    assert before.count(old)==1,'Pinned container function changed'
    after=before.replace(old,new,1)
    after=after.replace(' * A process without the variable has no container, and gets what every process got before:\n * success and an untouched buffer.',' * A process without the variable has no container and returns ENOENT.\n * Never return success with an untouched output buffer.')
    report={'passed':False,'scope':'Sandbox request 4 container lookup only; AMFI, privileges and other Sandbox calls unchanged','modes':{}}
    fixture=(patches/'container_test.c').read_text(encoding='utf8')
    for label,body in [('baseline',old),('candidate',new)]:
        test=a.output/(label+'.c');test.write_text(fixture.replace('/* ACTUAL_FUNCTION */',body),encoding='utf8')
        for mode,flags in [('release',['-O2']),('asan-ubsan',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
            exe=a.output/(label+'-'+mode)
            proc=subprocess.run(['clang','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror',*flags,str(test),'-o',str(exe)],capture_output=True)
            (a.output/(label+'-'+mode+'-compile.log')).write_bytes(proc.stdout+proc.stderr);assert proc.returncode==0,proc.stderr.decode(errors='replace')
            proc=subprocess.run([str(exe)],capture_output=True);(a.output/(label+'-'+mode+'.log')).write_bytes(proc.stdout+proc.stderr)
            if label=='baseline':assert proc.returncode!=0;result={'known_bug_detected':True}
            else:assert proc.returncode==0,proc.stderr.decode(errors='replace');result=json.loads(proc.stdout)
            report['modes'][label+'-'+mode]=result
    source.write_text(after,encoding='utf8',newline='\n')
    report.update(passed=True,source_sha256=hashlib.sha256(after.encode()).hexdigest(),baseline_sha256=hashlib.sha256(before.encode()).hexdigest())
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8');print(json.dumps(report))
if __name__=='__main__':main()
