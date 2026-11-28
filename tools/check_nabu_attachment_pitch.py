"""Run actual attachment predicate/store and FDL pitch functions with a host memory oracle."""
import argparse, hashlib, json, subprocess, sys
from pathlib import Path
from nabu_attachment_pitch import OLD, NEW, transform

def function(text, marker):
    start=text.index(marker);brace=text.index('{',start);end=brace+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]

def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    root=Path(__file__).resolve().parents[1];out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    source=(a.source/'src/freedreno/vulkan/tu_clear_blit.cc').read_text(encoding='utf8')
    layout=(a.source/'src/freedreno/fdl/freedreno_layout.h').read_text(encoding='utf8')
    assert NEW in source and transform(source,True).count(OLD)==1
    load=function(source,'void\ntu_load_gmem_attachment(')
    store=function(source,'static bool\ntu_attachment_store_unaligned(')
    assert 'tu_attachment_unpadded(cmd, iview) ||' in load
    assert 'tu_attachment_unpadded(cmd, iview)' in store
    assert 'TU_DEBUG(3D_LOAD)' in load and 'cmd->state.pass->has_fdm' in load and '(a != gmem_a)' in load
    assert 'TU_DEBUG(UNALIGNED_STORE)' in store and 'need_y2_align' in store and 'render_area_count' in store
    pitch=function(layout,'static inline uint32_t\nfdl_pitch(')
    (out/'actual.inc').write_text(pitch+'\nnamespace baseline {\n'+OLD+'\n'+store+'\n}\nnamespace candidate {\n'+NEW+'\n'+store+'\n}\n',encoding='utf8',newline='\n')
    report={'passed':False,'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
        'predicate_sha256':hashlib.sha256(NEW.encode()).hexdigest(),'actual_fdl_pitch':True,'actual_store_function':True,
        'load_site_and_existing_fallbacks_retained':True,'commands':[]}
    def hp(p):
        s=Path(p).resolve().as_posix();return '/mnt/'+s[0].lower()+s[2:] if sys.platform=='win32' else s
    def run(cmd,label):
        if sys.platform=='win32':cmd=['wsl','-d','Ubuntu-24.04','--',*cmd]
        report['commands'].append(cmd);proc=subprocess.run(cmd,capture_output=True)
        (out/(label+'.log')).write_bytes(proc.stdout+proc.stderr)
        if proc.returncode:raise RuntimeError((proc.stdout+proc.stderr).decode(errors='replace')[-5000:])
        return proc.stdout.decode()
    try:
        for mode,flags in [('release',['-O2']),('asan-ubsan',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
            exe=out/mode
            run(['clang++','-std=c++17','-Wall','-Wextra','-Werror',*flags,'-I'+hp(out),hp(root/'tools/fixtures/nabu_attachment_pitch.cpp'),'-o',hp(exe)],'compile-'+mode)
            report[mode]=json.loads(run([hp(exe)],'run-'+mode))
        report['passed']=True
        report['limits']='Host checks execute the production policy/store condition and FDL pitch; pixel tests model block addresses/visible bytes, not A640 hardware. Runtime GPU pixels and performance remain unverified.'
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='commands'},indent=2))

if __name__=='__main__':main()
