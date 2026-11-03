#!/usr/bin/env bash
# Compile standalone UEFI binaries in generated directories. No device access.
set -euo pipefail
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$PROJECT_ROOT"
export PROJECT_ROOT
export JOBS=${JOBS:-3}
export CLANG_BIN=${CLANG_BIN:-/usr/lib/llvm-18/bin/}
export PATH="$CLANG_BIN:$PATH"
mkdir -p log/ci/efi8796 artifacts/efi8796 build
for tool in clang llvm-lib lld-link llvm-rc llvm-readobj gcc make; do
  command -v "$tool" >/dev/null
done
python3 tools/fetch_sources.py --only UniXNU-nabu-reference-core DarwinBoot xnu-8796 --report log/ci/efi8796/source-checkouts.json
python3 tools/prepare_8796_loader.py --output build/efi8796/loader
python3 tools/check_darwinboot_8796.py --tree build/efi8796/loader --output log/ci/efi8796/abi
cp log/ci/darwinboot8796/source.json log/ci/efi8796/loader-source.json
python3 - <<'PY'
import json, os, pathlib, re, subprocess, tomllib
root=pathlib.Path(os.environ['PROJECT_ROOT'])
cfg=json.loads((root/'configs/efi-build-inputs.json').read_text())
assert (cfg['toolchain'],cfg['target'])==('CLANGPDB','DEBUG')
version=subprocess.check_output(['clang','--version'],text=True)
major=int(re.search(r'clang version (\d+)',version).group(1))
assert major==cfg['llvm_major'], ('LLVM major version mismatch',major)
lock=json.loads((root/'configs/sources.lock.json').read_text())['sources']
source=next(s for s in lock if s['name']==cfg['unixnu_source_name'])
feeds=tomllib.loads((root/source['path']/'feeds.toml').read_text())
upstream=next(s for s in feeds['source'] if s['name']=='edk2')
assert upstream['commit']==cfg['edk2']['commit'], 'EDK2 pin differs from fixed UniXNU input'
path=root/'build/efi8796/edk2'
if path.exists():raise ValueError('Select a clean build/efi8796 directory; never reset an existing checkout')
def git(*args):
    return subprocess.check_output(['git','-c','core.autocrlf=false','-C',str(path),*args],text=True).strip()
path.mkdir(parents=True)
git('init','-q')
git('remote','add','origin',cfg['edk2']['repository'])
git('fetch','-q','--depth','1','origin',cfg['edk2']['commit'])
git('-c','advice.detachedHead=false','checkout','-q','--detach','FETCH_HEAD')
assert git('rev-parse','HEAD')==cfg['edk2']['commit']
for subpath,expected in cfg['edk2']['submodules'].items():
    assert git('ls-tree','HEAD',subpath).split()[2]==expected
    git('submodule','update','--init','--depth','1','--',subpath)
    actual=subprocess.check_output(['git','-C',str(path/subpath),'rev-parse','HEAD'],text=True).strip()
    assert actual==expected, (subpath,actual)
(root/'log/ci/efi8796/edk2-source.json').write_text(json.dumps(cfg['edk2'],indent=2)+'\n')
PY
EDK2="$PROJECT_ROOT/build/efi8796/edk2"
export UNIXNU_EDK2="$EDK2"
export UNIXNU_BUILD_DIR="$PROJECT_ROOT/build/efi8796/workspace"
export PYTHON_COMMAND=python3
{
  uname -a
  clang --version
  lld-link --version
  gcc --version
  python3 --version
} > log/ci/efi8796/host.txt
bash src/unixnu/package/build.sh -b DEBUG -t CLANGPDB 2>&1 | tee log/ci/efi8796/unixnu-build.log
export WORKSPACE="$UNIXNU_BUILD_DIR"
export PACKAGES_PATH="$PROJECT_ROOT/build/efi8796/loader:$PROJECT_ROOT/src/unixnu/package:$EDK2"
export EDK_TOOLS_PATH="$EDK2/BaseTools"
export CONF_PATH="$WORKSPACE/Build/Conf"
export PATH="$EDK_TOOLS_PATH/BinWrappers/PosixLike:$EDK_TOOLS_PATH/Source/C/bin:$PATH"
build -p DarwinBootPkg/DarwinBoot.dsc -a AARCH64 -b DEBUG -t CLANGPDB -n "$JOBS" 2>&1 | tee log/ci/efi8796/darwinboot-build.log
python3 - <<'PY'
import hashlib, json, os, pathlib, shutil, struct, subprocess
root=pathlib.Path(os.environ['PROJECT_ROOT']);workspace=pathlib.Path(os.environ['WORKSPACE'])
specs=[('UniXNU.efi', workspace/'Build/Out/AARCH64-DEBUG/UniXNU.efi',10),
       ('DarwinBoot.efi', workspace/'build/DarwinBoot/DEBUG_CLANGPDB/AARCH64/DarwinBoot.efi',11)]
result={'purpose':'UEFI binaries only; no board firmware, kernel or Android boot.img',
        'device_boot_validated':False, 'architecture':'AArch64',
        'configuration_sha256':hashlib.sha256((root/'configs/efi-build-inputs.json').read_bytes()).hexdigest(),
        'loader_source':json.loads((root/'log/ci/efi8796/loader-source.json').read_text()),'binaries':[]}
for name,path,expected_subsystem in specs:
    data=path.read_bytes()
    assert data[:2]==b'MZ', (name,'DOS signature')
    pe=struct.unpack_from('<I',data,0x3c)[0]
    assert data[pe:pe+4]==b'PE\0\0', (name,'PE signature')
    machine=struct.unpack_from('<H',data,pe+4)[0]
    magic=struct.unpack_from('<H',data,pe+24)[0]
    subsystem=struct.unpack_from('<H',data,pe+24+68)[0]
    assert (machine,magic,subsystem)==(0xaa64,0x20b,expected_subsystem), (name,machine,magic,subsystem)
    target=root/'artifacts/efi8796'/name
    shutil.copy2(path,target)
    record={'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'machine':hex(machine),'optional_header_magic':hex(magic),'subsystem':subsystem}
    result['binaries'].append(record)
    output=subprocess.check_output(['llvm-readobj','--file-headers','--sections','--coff-imports',str(path)],text=True)
    (root/'log/ci/efi8796'/f'{name}.headers.txt').write_text(output)
(root/'artifacts/efi8796/build-report.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
PY
