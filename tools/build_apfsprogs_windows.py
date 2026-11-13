"""Cross-compile the pinned APFS tools for ordinary Windows image files only."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
ROOT=Path(__file__).resolve().parents[1]
REV='1bd1c1c2140d13d1b6d2e03379316572bee70aa3'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();source=a.source.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==REV
    shim=ROOT/'patches/apfsprogs-windows'
    for name in ('mkapfs','apfsck'):
        (source/name/'version.h').write_text('#define GIT_COMMIT "'+REV[:8]+'"\n')
        command=['x86_64-w64-mingw32-gcc','-O2','-static','-D_FILE_OFFSET_BITS=64',
                 '-Wno-address-of-packed-member','-fno-strict-aliasing','-include',str(shim/'compat.h'),
                 '-I'+str(shim),'-I'+str(source/'include'),
                 *map(str,sorted((source/name).glob('*.c'))),
                 *map(str,sorted((source/'lib').glob('*.c'))),
                 *map(str,sorted((source/'lib/zlib_inflate').glob('*.c'))),
                 '-o',str(out/(name+'.exe')),'-lwinpthread']
        result=subprocess.run(command,capture_output=True)
        (out/(name+'-build.log')).write_bytes(result.stdout+result.stderr)
        if result.returncode:
            print(result.stderr.decode(errors='replace'));raise SystemExit(result.returncode)
    (out/'build-report.json').write_text(json.dumps({'source_commit':REV,'platform':'Windows x64',
        'scope':'Regular image files only, explicit UUIDs required; no raw block devices',
        'filesystem_algorithms_changed':False,'windows_runtime_tested':False},indent=2)+'\n')
    # Complete corresponding source, adapter and reproducible build instructions.
    shutil.copytree(source,out/'source/apfsprogs',ignore=shutil.ignore_patterns('.git','*.o','*.d'))
    shutil.copytree(shim,out/'source/windows-adapter')
    shutil.copy2(__file__,out/'source/build_apfsprogs_windows.py')
    print(out)


if __name__=='__main__':main()
