"""Differentially execute actual old/new CS functions and their index headers."""
import argparse, hashlib, json, re, subprocess, sys
from pathlib import Path
from nabu_cs_import_cache import transform

def function(text, name):
    start=text.index('void\n'+name+'(');pos=text.index('{',start);depth=1;end=pos+1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    result=text[start:end]
    if name=='tu_cs_use_range':result=result[:pos-start+1]+'\n   visits++;'+result[pos-start+1:]
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    current=(a.source/'tu_cs.cc').read_text();previous=transform(current,reverse=True)
    new_header=(a.source/'tu_resource_range_index.h').read_text()
    assert new_header==(root/'patches/nabu-vulkan/tu_resource_range_index.h').read_text()
    old_header=(root/'tools/fixtures/cs_import_baseline.h').read_text()
    assert 'tu_resource_range_index_clear(&cs->resource_range_index);' in current
    assert 'tu_resource_range_index_finish(&cs->resource_range_index);' in current
    assert current.count('memset(cs, 0, sizeof(*cs));')==3
    wrapper='''
static thread_local uint64_t visits=0;
struct tu_cs { util_dynarray resource_ranges{}; tu_resource_range_index resource_range_index{};
  tu_cs *parent=nullptr; int mode=TU_CS_MODE_GROW; int record_result=VK_SUCCESS; };
static void tu_cs_set_error(tu_cs *cs,int error){if(cs->record_result==VK_SUCCESS)cs->record_result=error;}
'''
    for label,header,text in [('baseline',old_header,previous),('candidate',new_header,current)]:
        header=re.sub(r'^#(?:include|pragma).*\n','',header,flags=re.M)
        body=header+wrapper+'\n'.join(function(text,n) for n in ['tu_cs_use_range','tu_cs_use_resources'])
        (out/(label+'.inc')).write_text(body,encoding='utf8')
    fixture=root/'tools/fixtures/cs_import_cache.cpp'
    report={'passed':False,'scope':'actual CS record/import and exact old/new index header; dynarray allocator is a host adapter',
            'source_sha256':hashlib.sha256(current.encode()).hexdigest(),'header_sha256':hashlib.sha256(new_header.encode()).hexdigest(),
            'source_reset_finish_and_init_wiring':True,'commands':[]}
    def hp(p):
        s=Path(p).resolve().as_posix()
        return '/mnt/'+s[0].lower()+s[2:] if sys.platform=='win32' else s
    def run(cmd,label):
        if sys.platform=='win32':cmd=['wsl','-d','Ubuntu-24.04','--',*cmd]
        report['commands'].append(cmd)
        proc=subprocess.run(cmd,capture_output=True)
        (out/(label+'.log')).write_bytes(proc.stdout+proc.stderr)
        if proc.returncode:raise RuntimeError((proc.stdout+proc.stderr).decode(errors='replace')[-6000:])
        return proc.stdout.decode()
    try:
        for mode,flags in [('release',['-O2']),('asan-ubsan',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
            exe=out/('check-'+mode)
            run(['clang++','-std=c++17','-Wall','-Wextra','-Werror','-pthread',*flags,'-I'+hp(out),hp(fixture),'-o',hp(exe)],'compile-'+mode)
            report[mode]=json.loads(run([hp(exe),'semantic'],'semantic-'+mode))
            if mode=='release':report['benchmark']=json.loads(run([hp(exe),'benchmark'],'benchmark'))
        report['passed']=True
        report['limits']='Host timings do not establish UI/FPS gains. No GPU packets, memory backing or scheduling are changed; native submission arrays are checked for identical order/address/size/access.'
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='commands'},indent=2))
if __name__=='__main__':main()
