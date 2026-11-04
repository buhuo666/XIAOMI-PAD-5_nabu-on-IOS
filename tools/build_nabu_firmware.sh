#!/usr/bin/env bash
set -euo pipefail
PROJECT_ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$PROJECT_ROOT"
export PROJECT_ROOT
export PATH="/usr/lib/llvm-18/bin:$PATH"
export CLANGPDB_BIN=/usr/lib/llvm-18/bin/
export CLANGPDB_AARCH64_PREFIX=aarch64-linux-gnu-
export GCC5_AARCH64_PREFIX=aarch64-linux-gnu-
mkdir -p log/ci/nabu-firmware artifacts/nabu-firmware build
TREE="$PROJECT_ROOT/build/nabu-firmware/tree"
python3 tools/fetch_nabu_firmware.py --output "$TREE" 2>&1 | tee log/ci/nabu-firmware/fetch.log
python3 tools/prepare_nabu_firmware.py --tree "$TREE"
python3 -m venv build/nabu-firmware/venv
source build/nabu-firmware/venv/bin/activate
python3 - <<'PY'
import os,pathlib
root=pathlib.Path(os.environ['PROJECT_ROOT'])
s=(root/'build/nabu-firmware/tree/pip-requirements.txt').read_text()
s=s.replace('edk2-pytool-extensions~=0.31.2','edk2-pytool-extensions==0.31.2').replace('Levenshtein~=0.27','Levenshtein==0.27.0')
(root/'log/ci/nabu-firmware/pip-requirements.txt').write_text(s)
PY
python3 -m pip install --disable-pip-version-check --report log/ci/nabu-firmware/pip-downloads.json -r log/ci/nabu-firmware/pip-requirements.txt 2>&1 | tee log/ci/nabu-firmware/pip.log
python3 -m pip freeze > log/ci/nabu-firmware/pip-freeze.txt
{
  clang --version
  lld-link --version
  iasl -v
} > log/ci/nabu-firmware/toolchain.txt
cd "$TREE"
make -C BootShim UEFI_BASE=0x9fc00000 UEFI_SIZE=0x300000 2>&1 | tee "$PROJECT_ROOT/log/ci/nabu-firmware/bootshim.log"
# All Git modules were fetched from parent gitlinks above. No upstream setup script.
python3 Platforms/SurfaceDuo1Pkg/PlatformBuildNoSb.py --update -t DEBUG 2>&1 | tee "$PROJECT_ROOT/log/ci/nabu-firmware/update.log"
python3 Platforms/SurfaceDuo1Pkg/PlatformBuildNoSb.py TARGET=DEBUG TARGET_DEVICE=xiaomi-nabu 2>&1 | tee "$PROJECT_ROOT/log/ci/nabu-firmware/build.log"
cd "$PROJECT_ROOT"
cp "$TREE/Build/SurfaceDuo1Pkg/xiaomi-nabu.img" artifacts/nabu-firmware/boot.img
cp "$TREE/Build/SurfaceDuo1Pkg/DEBUG_CLANGPDB/FV/SM8150_EFI.fd" artifacts/nabu-firmware/
cp "$TREE/BootShim/BootShim.bin" artifacts/nabu-firmware/
cp "$TREE/Platforms/SurfaceDuo1Pkg/Device/xiaomi-nabu/DeviceTreeBlob/Android/android-nabu.dtb" artifacts/nabu-firmware/
python3 tools/verify_nabu_boot_image.py --image artifacts/nabu-firmware/boot.img --shim artifacts/nabu-firmware/BootShim.bin --firmware artifacts/nabu-firmware/SM8150_EFI.fd --dtb artifacts/nabu-firmware/android-nabu.dtb --output artifacts/nabu-firmware/boot-image-report.json
