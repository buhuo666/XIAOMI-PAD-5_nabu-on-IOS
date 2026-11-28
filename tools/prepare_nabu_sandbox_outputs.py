"""SET378 output contracts, layered after the SET377 container path repair."""
import argparse,hashlib,json,subprocess
from pathlib import Path
def extract(source,name):
    start=source.index('static int\n'+name+'(');body=source.index('{',start);depth=0
    for at in range(body,len(source)):
        depth+=(source[at]=='{')-(source[at]=='}')
        if not depth:return source[start:at+1]
    raise ValueError('Unclosed function')
def main():
    p=argparse.ArgumentParser();p.add_argument('--tree',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    r=Path(__file__).resolve().parents[1];patch=r/'patches/nabu-sandbox';a.output.mkdir(parents=True,exist_ok=True)
    path=a.tree/'bsd/kern/kern_minimac.c';before=path.read_text(encoding='utf8')
    assert (patch/'candidate-function.c').read_text(encoding='utf8') in before,'SET377 prerequisite missing'
    old=extract(before,'minisandbox_policy_syscall');expected=(patch/'baseline-dispatch.c').read_text(encoding='utf8').strip()
    assert old==expected,'Pinned dispatcher changed'
    functions=(patch/'output-contracts.c').read_text(encoding='utf8');dispatch=(patch/'output-dispatch.c').read_text(encoding='utf8')
    anchor='/* Which request numbers have been seen:';assert before.count(anchor)==1
    after=before.replace(anchor,functions+'\n'+anchor,1).replace(old,dispatch.strip(),1)
    fixture=(patch/'output_test.c').read_text(encoding='utf8');report={'passed':False,'modes':{}}
    for label,fn,dp in [('baseline','',old),('candidate',functions,dispatch)]:
        # Old dispatcher has no references to the query helper stubs, so suppress
        # only unused-function warnings in the negative-control fixture.
        src=a.output/(label+'.c');src.write_text(fixture.replace('/* OUTPUT_FUNCTIONS */',fn).replace('/* DISPATCH_FUNCTION */',dp),encoding='utf8')
        for mode,flags in [('release',['-O2']),('asan-ubsan',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
            exe=a.output/(label+'-'+mode)
            proc=subprocess.run(['clang','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-Wno-unused-function',*flags,str(src),'-o',str(exe)],capture_output=True)
            (a.output/(label+'-'+mode+'-compile.log')).write_bytes(proc.stdout+proc.stderr);assert proc.returncode==0,proc.stderr.decode(errors='replace')
            proc=subprocess.run([str(exe)],capture_output=True);(a.output/(label+'-'+mode+'.log')).write_bytes(proc.stdout+proc.stderr)
            if label=='baseline':assert proc.returncode!=0;row={'known_gap_detected':True}
            else:assert proc.returncode==0,proc.stderr.decode(errors='replace');row=json.loads(proc.stdout)
            report['modes'][label+'-'+mode]=row
    path.write_text(after,encoding='utf8',newline='\n')
    report.update(passed=True,source_sha256=hashlib.sha256(after.encode()).hexdigest(),baseline_sha256=hashlib.sha256(before.encode()).hexdigest(),scope='Request2 explicit filter-query failure and normal result output; request5 no-op sentinel; request21 byte results; SET377 retained')
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
if __name__=='__main__':main()
