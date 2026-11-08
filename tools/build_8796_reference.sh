#!/usr/bin/env bash
# Host compilation checkpoint only; this is not the nabu boot image.
set -euo pipefail
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$PROJECT_ROOT"
mkdir -p log/ci artifacts/8796-reference build/downloads
python3 tools/fetch_sources.py --only hakios-8796-reference xnu-8796 DarwinBoot ShengUfs nabu XnuPrelink --report log/ci/source-checkouts.json
python3 tools/build_nabu_input_bridge.py --output artifacts/nabu-input-bridge
python3 tools/build_nabu_userland.py --work build/nabu-userland --output artifacts/nabu-userland
python3 tools/check_nabu_userland.py --output log/ci/nabu-userland-check
python3 tools/check_nabu_data_mount.py --output log/ci/nabu-data-mount
python3 tools/prepare_8796_loader.py --output build/darwinboot8796-capacity/tree
python3 tools/check_darwinboot_8796.py --tree build/darwinboot8796-capacity/tree --output log/ci/darwinboot8796
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
import hashlib,json,pathlib,sys,urllib.request
sys.path.insert(0,'tools')
from nabu_build_download import open_build_input
cfg=json.load(open('configs/build-inputs.json'))
p=pathlib.Path('build/downloads/MacOSX13.3.sdk.tar.xz')
with open_build_input(urllib.request.urlopen,cfg['macos_sdk_url'],timeout=90,github_asset_api=cfg['macos_sdk_asset_api']) as r,p.open('wb') as f:
    while b:=r.read(1024*1024):f.write(b)
digest=hashlib.sha256(p.read_bytes()).hexdigest()
if digest!=cfg['macos_sdk_sha256']:raise SystemExit('macOS SDK download hash differs from reviewed input')
print('macOS SDK SHA256:',digest)
PY
tar -xJf build/downloads/MacOSX13.3.sdk.tar.xz -C src/hakios-8796/xnu-deps --include='*MacOSX13.3.sdk/System/Library/Frameworks/Kernel.framework*'

# Select before exporthdrs: otherwise setup can leave shim-generated headers in
# place, and make may not regenerate them when IIG changes later.
python3 tools/probe_iig.py --output log/ci/iig-probe.json --selected-path log/ci/iig-path.txt \
  --fallback src/hakios-8796/xnu-deps/host/bin/iig
export PROJECT_ROOT
export NABU_NATIVE_IIG="$(cat log/ci/iig-path.txt)"
if [ "$(python3 -c 'import json; print(json.load(open("log/ci/iig-probe.json"))["mode"])')" = native-xcode ]; then
  export IIG="$PROJECT_ROOT/tools/iig_8796.py"
else
  export IIG="$NABU_NATIVE_IIG"
fi

cd "$PROJECT_ROOT/src/hakios-8796"
python3 tools/hakios-config.py defconfig defconfig
bash xnu/apply.sh "$XNU_SRC" 2>&1 | tee "$PROJECT_ROOT/log/ci/apply.log"
: > "$PROJECT_ROOT/log/ci/project-patches.sha256"
for patch in pmap-nonmonitor-queries.patch bcm2837-apple-iommu-query-returns.patch bcm2837-bootstrap-capacity.patch generic-smp-diagnostics.patch loader-return-diagnostics.patch nabu-log-capture.patch nabu-panic-early-log.patch nabu-native-display.patch nabu-export-contract.patch miniamfi-csops-xml.patch nabu-wifi-control-state.patch nabu-wifi-station-lifecycle.patch; do
  git -C "$XNU_SRC" apply --check "$PROJECT_ROOT/patches/8796/$patch"
  git -C "$XNU_SRC" apply "$PROJECT_ROOT/patches/8796/$patch"
  shasum -a 256 "$PROJECT_ROOT/patches/8796/$patch" >> "$PROJECT_ROOT/log/ci/project-patches.sha256"
done
cd "$PROJECT_ROOT"
python3 tools/check_nabu_csops_xml.py --tree "$XNU_SRC" --output log/ci/nabu-csops-xml
python3 tools/prepare_nabu_storage.py --tree "$XNU_SRC" --work build/nabu-storage-source --output log/ci/nabu-storage/source.json
python3 tools/prepare_nabu_input.py --tree "$XNU_SRC" --output log/ci/nabu-input/source.json
python3 tools/prepare_nabu_native_apfs.py --tree "$XNU_SRC" --output log/ci/nabu-native-apfs/source.json
python3 tools/check_nabu_apfs_alias.py --tree "$XNU_SRC" --output log/ci/nabu-apfs-alias
python3 tools/check_nabu_native_apfs.py --output log/ci/nabu-native-apfs/checks
python3 tools/check_nabu_input.py --output log/ci/nabu-input/checks
python3 tools/check_nabu_storage.py --tree "$XNU_SRC" --output log/ci/nabu-storage/host
python3 tools/check_nabu_log_writer.py --tree "$XNU_SRC" --output log/ci/nabu-log-writer
python3 tools/check_nabu_log_capture.py --tree "$XNU_SRC" --output log/ci/nabu-log-capture
python3 tools/check_nabu_panic_early.py --tree "$XNU_SRC" --output log/ci/nabu-panic-early
python3 tools/check_nabu_log_runtime.py --output log/ci/nabu-log-runtime
python3 tools/check_nabu_log_format.py --output log/ci/nabu-log-format --native-fixture log/ci/nabu-log-writer/valid-slot.bin
python3 tools/check_return_diagnostics.py --tree "$XNU_SRC" --output log/ci/return-diagnostics-host
python3 tools/check_nabu_display.py --tree "$XNU_SRC" --output log/ci/nabu-display-host
python3 tools/check_nabu_export_contract.py --tree "$XNU_SRC" --output log/ci/nabu-export-contract.json
export NABU_EXPORT_CONTRACT=20F66-37-v1
export NABU_EXPORT_CONTRACT_ROOT="$PROJECT_ROOT"
python3 -m pip install --disable-pip-version-check --only-binary=:all: --target build/host-tools/capacity unicorn==2.1.4
python3 tools/check_bootstrap_capacity.py --tree "$XNU_SRC" --output log/ci/bootstrap-capacity
cd "$PROJECT_ROOT/src/hakios-8796"
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
        'build_exit_code':int(os.environ['BUILD_EXIT']),'device_boot_validated':False,'kernels':[],
        'iig':json.loads((root/'log/ci/iig-probe.json').read_text()),
        'project_patches':[{'path':'patches/8796/'+name,
          'sha256':hashlib.sha256((root/'patches/8796'/name).read_bytes()).hexdigest()}
          for name in ('pmap-nonmonitor-queries.patch','bcm2837-apple-iommu-query-returns.patch',
                       'bcm2837-bootstrap-capacity.patch','generic-smp-diagnostics.patch','loader-return-diagnostics.patch','nabu-log-capture.patch','nabu-panic-early-log.patch',
                       'nabu-native-display.patch','nabu-export-contract.patch','miniamfi-csops-xml.patch','nabu-wifi-control-state.patch','nabu-wifi-station-lifecycle.patch')],
        'export_contract':json.loads((root/'log/ci/nabu-export-contract.json').read_text())}
generated=[]
for p in sorted((tree/'BUILD').rglob('*.iig.cpp')):
    raw=p.read_bytes()
    generated.append({'path':p.relative_to(tree).as_posix(),'bytes':len(raw),
                      'sha256':hashlib.sha256(raw).hexdigest(),
                      'empty_shim_marker':b'no DriverKit implementation generated' in raw})
(root/'log/ci/iig-generated.json').write_text(json.dumps(generated,indent=2)+'\n')
for p in candidates:
    dest=root/'artifacts/8796-reference'/p.name;shutil.copy2(p,dest)
    report['kernels'].append({'name':p.name,'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
out=root/'artifacts/8796-reference/build-report.json';out.write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report))
if not candidates:raise SystemExit('No linked Mach-O kernel was produced')
# Preserve a real make failure in CI, including the upstream export-check issue.
raise SystemExit(report['build_exit_code'])
PY
