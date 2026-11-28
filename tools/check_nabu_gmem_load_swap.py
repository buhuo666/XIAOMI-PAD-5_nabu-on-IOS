"""Extract actual load descriptor code; compare old/new packets and channel ordering."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path
from nabu_gmem_load_swap import transform,NEW
def extract(source,name):
    at=source.index('template <chip CHIP>\nstatic void\n'+name+'(');brace=source.index('{',at);end=brace+1;depth=1
    while depth:depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[at:end]
def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    source=(a.source/'src/freedreno/vulkan/tu_clear_blit.cc').read_text(encoding='utf8');old=transform(source,True)
    assert NEW in source
    assert 'if (!iview->view.is_mutable)\n      tu_desc_set_swap<CHIP>(desc, WZYX);' in extract(source,'r3d_src_gmem')
    for name in ['r3d_src_load','r3d_src_sysmem_load','r3d_src_gmem','store_cp_blit','r3d_dst_gmem']:assert extract(source,name)==extract(old,name)
    text=''
    for label,s in [('baseline',old),('candidate',source)]:
        text+='namespace '+label+' {\n'+extract(s,'r3d_src_load')+'\n'+extract(s,'r3d_src_gmem_load')+'\n'+extract(s,'r3d_src_sysmem_load')+'\n}\n'
    (out/'actual.inc').write_text(text,encoding='utf8',newline='\n')
    report={'passed':False,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'only_function_changed':'r3d_src_gmem_load','commands':[]}
    def hp(p):
        s=Path(p).resolve().as_posix();return '/mnt/'+s[0].lower()+s[2:] if sys.platform=='win32' else s
    def run(cmd,label):
        if sys.platform=='win32':cmd=['wsl','-d','Ubuntu-24.04','--',*cmd]
        report['commands'].append(cmd);v=subprocess.run(cmd,capture_output=True);(out/(label+'.log')).write_bytes(v.stdout+v.stderr)
        if v.returncode:raise RuntimeError((v.stdout+v.stderr).decode(errors='replace')[-3500:])
        return v.stdout.decode()
    try:
        for mode,flags in [('release',['-O2']),('asan-ubsan',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
            exe=out/mode;run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',*flags,'-I'+hp(out),hp(root/'tools/fixtures/nabu_gmem_load_swap.cpp'),'-o',hp(exe)],'compile-'+mode)
            report[mode]=json.loads(run([hp(exe)],'run-'+mode))
        report['passed']=True;report['scope']='Actual production function extraction with descriptor-write stubs; validates packet fields/ordering, not GPU silicon. Runtime pixel validation required.'
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='commands'},indent=2))
if __name__=='__main__':main()
