"""Apply the entire runtime series; check the actual Apple diagnostic ABI and errno contract."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from nabu_metal_ios_qos import stage_ios_qos
from nabu_metal_submit_trace import stage_submit_trace
from nabu_metal_runtime_trace import stage_runtime_trace

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
mod production;
fn early() -> Result<u32, u32> {
    unsafe { *libc::__error() = 13; }
    let _span = production::Span::new(32, 33, 7, 0);
    assert_eq!(unsafe { *libc::__error() }, 13);
    {
        let _nested = production::Span::new(34, 35, 7, 0);
        assert_eq!(unsafe { *libc::__error() }, 13);
        unsafe { *libc::__error() = 22; }
    }
    assert_eq!(unsafe { *libc::__error() }, 22);
    Err(42)
}
fn main() {
    for _ in 0..10 {
        assert_eq!(early(), Err(42));
        assert_eq!(unsafe { *libc::__error() }, 22);
    }
    let (result, errno) = std::thread::spawn(|| {
        let result = early();
        (result, unsafe { *libc::__error() })
    }).join().unwrap();
    assert_eq!(result, Err(42));
    assert_eq!(errno, 22);
    println!("PASS: real Apple clock/syscall ABI, nested scopes, original errno/return, second thread");
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--stage-only',action='store_true')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    if not a.stage_only and sys.platform!='darwin':p.error('Use macOS CI for native execution')
    report=dict(result='building',commands=[],native_executed=False,ios_compiled=False)
    def run(args,label,**kwargs):
        args=list(map(str,args));report['commands'].append(args)
        r=subprocess.run(args,capture_output=True,**kwargs)
        (out/(label+'.stdout')).write_bytes(r.stdout);(out/(label+'.stderr')).write_bytes(r.stderr)
        if r.returncode:raise RuntimeError(label+': '+r.stderr.decode(errors='replace')[-5000:])
        return r
    try:
        frontend=out/'frontend'
        shutil.copytree(a.input/'frontend-source',frontend)
        stage_submit_trace(ROOT,frontend);stage_ios_qos(ROOT,frontend)
        report['staging']=stage_runtime_trace(ROOT,frontend)
        runtime=out/'runtime'
        run(['git','clone','--quiet','--no-hardlinks','--config','core.autocrlf=false',ROOT/'src/metal2vulkan',runtime],'clone')
        patches=[n for n in (frontend/'bridge/patches/series').read_text().splitlines() if n and not n.startswith('#')]
        for index,name in enumerate(patches):
            run(['git','-C',runtime,'apply',frontend/'bridge/patches'/name],f'patch-{index}')
        source=runtime/'crates/metal2vulkan-runtime/src/nabu_submit_trace.rs'
        assert source.read_bytes()==(ROOT/'patches/nabu-metal/NativeMetalRuntimeTrace.rs').read_bytes()
        report['patch_count']=len(patches)
        if a.stage_only:
            report['result']='staged_not_run'
        else:
            case=out/'native';(case/'src').mkdir(parents=True)
            shutil.copyfile(source,case/'src/production.rs')
            (case/'src/main.rs').write_text(HARNESS)
            (case/'Cargo.toml').write_text('[package]\nname="nabu-runtime-trace-check"\nversion="0.0.0"\nedition="2024"\n[dependencies]\nlibc="=0.2.191"\n')
            run(['cargo','+1.98.1','build','--manifest-path',case/'Cargo.toml'],'native-build')
            import os
            for enabled in ('0','1'):
                run([case/'target/debug/nabu-runtime-trace-check'],'native-'+enabled,env=dict(os.environ,NABU_METAL_SUBMIT_TRACE=enabled))
            report['native_executed']=True
            run(['cargo','+1.98.1','check','--locked','--target','aarch64-apple-ios','--manifest-path',case/'Cargo.toml'],'ios-check')
            report.update(ios_compiled=True,result='pass')
    finally:
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='commands'}))


if __name__=='__main__':main()
