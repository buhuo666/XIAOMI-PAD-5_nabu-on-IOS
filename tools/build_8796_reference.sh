#!/usr/bin/env bash
# Host compilation checkpoint only; this is not the nabu boot image.
set -euo pipefail
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$PROJECT_ROOT"
mkdir -p log/ci artifacts/8796-reference build/downloads
python3 tools/fetch_sources.py --only hakios-8796 xnu-8796 --report log/ci/source-checkouts.json
export JOBS=3
export THEOS="$PROJECT_ROOT/build/reference-theos"
export XNU_SRC="$PROJECT_ROOT/build/xnu8796-reference/tree"
SDK_COMMIT=$(python3 -c 'import json; print(json.load(open("configs/build-inputs.json"))["theos_sdk_commit"])')
mkdir -p "$THEOS/sdks" "$THEOS/sdks-git"
git -C "$THEOS/sdks-git" init -q
git -C "$THEOS/sdks-git" remote add origin https://github.com/theos/sdks.git
git -C "$THEOS/sdks-git" sparse-checkout init --cone
git -C "$THEOS/sdks-git" sparse-checkout set iPhoneOS16.5.sdk
git -C "$THEOS/sdks-git" fetch -q --depth 1 --filter=blob:none origin "$SDK_COMMIT"
git -C "$THEOS/sdks-git" -c advice.detachedHead=false checkout -q --detach FETCH_HEAD
ln -s ../sdks-git/iPhoneOS16.5.sdk "$THEOS/sdks/iPhoneOS16.5.sdk"

python3 - <<'PY'
import hashlib,json,pathlib,urllib.request
cfg=json.load(open('configs/build-inputs.json'))
p=pathlib.Path('build/downloads/MacOSX13.3.sdk.tar.xz')
with urllib.request.urlopen(cfg['macos_sdk_url'],timeout=90) as r,p.open('wb') as f:
    while b:=r.read(1024*1024):f.write(b)
digest=hashlib.sha256(p.read_bytes()).hexdigest()
if digest!=cfg['macos_sdk_sha256']:raise SystemExit('macOS SDK download hash differs from reviewed input')
print('macOS SDK SHA256:',digest)
PY
tar -xJf build/downloads/MacOSX13.3.sdk.tar.xz -C src/hakios-8796/xnu-deps --include='*MacOSX13.3.sdk/System/Library/Frameworks/Kernel.framework*'

cd "$PROJECT_ROOT/src/hakios-8796"
python3 tools/hakios-config.py defconfig defconfig
bash xnu/apply.sh "$XNU_SRC" 2>&1 | tee "$PROJECT_ROOT/log/ci/apply.log"
bash xnu-deps/setup.sh 2>&1 | tee "$PROJECT_ROOT/log/ci/setup.log"
set +e
bash xnu-build.sh -j"$JOBS" -k 2>&1 | tee "$PROJECT_ROOT/log/ci/kernel-build.log"
BUILD_EXIT=${PIPESTATUS[0]}
set -e
export BUILD_EXIT PROJECT_ROOT
python3 - <<'PY'
import hashlib,json,os,pathlib,shutil,subprocess
root=pathlib.Path(os.environ['PROJECT_ROOT']);tree=pathlib.Path(os.environ['XNU_SRC'])
candidates=[p for p in tree.glob('BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837*') if p.is_file() and p.read_bytes()[:4]==bytes.fromhex('cffaedfe')]
report={'purpose':'HakiOS 8796 host compilation reference; not a nabu device image',
        'build_exit_code':int(os.environ['BUILD_EXIT']),'device_boot_validated':False,'kernels':[]}
for p in candidates:
    dest=root/'artifacts/8796-reference'/p.name;shutil.copy2(p,dest)
    report['kernels'].append({'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
out=root/'artifacts/8796-reference/build-report.json';out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
if not candidates:raise SystemExit('No linked Mach-O kernel was produced')
# Preserve a real make failure in CI, including the upstream export-check issue.
raise SystemExit(report['build_exit_code'])
PY
