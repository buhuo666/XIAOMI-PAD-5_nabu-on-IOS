#!/usr/bin/env bash
# Local build using the same fixed EDK II inputs as the successful Actions build.
set -euo pipefail
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$PROJECT_ROOT"
NABU_EFI_WORK=${NABU_EFI_WORK:-/home/buhuo/nabu16-efi-v1}
export PROJECT_ROOT NABU_EFI_WORK
export CLANG_BIN=/usr/lib/llvm-18/bin/
export PATH="$CLANG_BIN:$PATH"
export JOBS=${JOBS:-8}
export PYTHON_COMMAND=python3.12
mkdir -p "$NABU_EFI_WORK" log/host/nabu-efi artifacts/nabu-efi
python3.12 - <<'PY'
import json,os,pathlib,subprocess
root=pathlib.Path(os.environ['PROJECT_ROOT'])
cfg=json.loads((root/'configs/efi-build-inputs.json').read_text())['edk2']
p=root/'src/edk2-efi8796'
def git(path,*args):return subprocess.check_output(['git','-C',str(path),*args],text=True).strip()
assert git(p,'rev-parse','HEAD')==cfg['commit']
for rel,commit in cfg['submodules'].items():assert git(p/rel,'rev-parse','HEAD')==commit
PY
if [ ! -d "$NABU_EFI_WORK/edk2" ]; then
  cp -a src/edk2-efi8796 "$NABU_EFI_WORK/edk2"
fi
if [ ! -d "$NABU_EFI_WORK/loader" ]; then
  python3.12 tools/prepare_8796_loader.py --output "$NABU_EFI_WORK/loader"
fi
python3.12 tools/restore_git_exec.py "$NABU_EFI_WORK/edk2"
python3.12 tools/check_darwinboot_8796.py --tree "$NABU_EFI_WORK/loader" --output log/host/nabu-efi/abi
python3.12 tools/check_nabu_handoff.py --tree "$NABU_EFI_WORK/loader" --output log/host/nabu-efi/handoff
export UNIXNU_EDK2="$NABU_EFI_WORK/edk2"
export UNIXNU_BUILD_DIR="$NABU_EFI_WORK/workspace"
bash src/unixnu/package/build.sh -b DEBUG -t CLANGPDB 2>&1 | tee log/host/nabu-efi/unixnu-build.log
export WORKSPACE="$UNIXNU_BUILD_DIR"
export PACKAGES_PATH="$NABU_EFI_WORK/loader:$PROJECT_ROOT/src/unixnu/package:$UNIXNU_EDK2"
export EDK_TOOLS_PATH="$UNIXNU_EDK2/BaseTools"
export CONF_PATH="$WORKSPACE/Build/Conf"
export PATH="$EDK_TOOLS_PATH/BinWrappers/PosixLike:$EDK_TOOLS_PATH/Source/C/bin:$PATH"
build -p DarwinBootPkg/DarwinBoot.dsc -a AARCH64 -b DEBUG -t CLANGPDB -n "$JOBS" 2>&1 | tee log/host/nabu-efi/darwinboot-build.log
cp "$WORKSPACE/Build/Out/AARCH64-DEBUG/UniXNU.efi" artifacts/nabu-efi/
cp "$WORKSPACE/build/DarwinBoot/DEBUG_CLANGPDB/AARCH64/DarwinBoot.efi" artifacts/nabu-efi/
python3.12 - <<'PY'
import hashlib,json,pathlib,struct
root=pathlib.Path('.')
result=[]
for name,subsystem in [('UniXNU.efi',10),('DarwinBoot.efi',11)]:
 p=root/'artifacts/nabu-efi'/name;b=p.read_bytes();pe=struct.unpack_from('<I',b,0x3c)[0]
 assert b[:2]==b'MZ' and b[pe:pe+4]==b'PE\0\0'
 assert struct.unpack_from('<H',b,pe+4)[0]==0xaa64
 assert struct.unpack_from('<H',b,pe+24)[0]==0x20b
 assert struct.unpack_from('<H',b,pe+24+68)[0]==subsystem
 result.append({'name':name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'subsystem':subsystem})
(root/'artifacts/nabu-efi/build-report.json').write_text(json.dumps({'binaries':result,'device_boot_validated':False},indent=2)+'\n')
print(json.dumps(result,indent=2))
PY
