#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
EDK2=$ROOT/sources/edk2
FRAMEWORK=$ROOT/sources/framework
export WORKSPACE=$FRAMEWORK
export PACKAGES_PATH=$FRAMEWORK/drivers/DarwinBoot:$FRAMEWORK/package:$EDK2
export EDK_TOOLS_PATH=$EDK2/BaseTools
export CONF_PATH=$ROOT/sources/Conf
export PYTHON_COMMAND=python3
export PATH=$EDK_TOOLS_PATH/BinWrappers/PosixLike:$EDK_TOOLS_PATH/Source/C/bin:$PATH
mkdir -p "$CONF_PATH"
for name in target tools_def build_rule; do
  cp "$EDK_TOOLS_PATH/Conf/$name.template" "$CONF_PATH/$name.txt"
done
make -C "$EDK_TOOLS_PATH/Source/C" -j3
cd "$FRAMEWORK"
for profile in darwin23 darwin22 nabu-diagnostic; do
  major=22
  diagnostic=0
  if [ "$profile" = darwin23 ]; then major=23; fi
  if [ "$profile" = nabu-diagnostic ]; then diagnostic=1; fi
  # Rebuild all objects when changing compiler definitions.
  build -p DarwinBootPkg/DarwinBoot.dsc -a AARCH64 -b DEBUG -t CLANGPDB \
    -D "DARWINBOOT_XNU_MAJOR=$major" -D "DARWINBOOT_NABU_DIAGNOSTIC=$diagnostic" cleanall
  build -p DarwinBootPkg/DarwinBoot.dsc -a AARCH64 -b DEBUG -t CLANGPDB -n 3 \
    -D "DARWINBOOT_XNU_MAJOR=$major" -D "DARWINBOOT_NABU_DIAGNOSTIC=$diagnostic"
  mkdir -p "$ROOT/out/$profile"
  cp build/DarwinBoot/DEBUG_CLANGPDB/AARCH64/DarwinBoot.efi "$ROOT/out/$profile/"
  if [ "$diagnostic" = 0 ]; then
    cp build/DarwinBoot/DEBUG_CLANGPDB/AARCH64/DarwinBootValidation.efi "$ROOT/out/$profile/"
  fi
  file "$ROOT/out/$profile/DarwinBoot.efi"
  llvm-readobj --file-headers "$ROOT/out/$profile/DarwinBoot.efi" > "$ROOT/out/$profile/pe-headers.txt"
  grep -q 'IMAGE_FILE_MACHINE_ARM64' "$ROOT/out/$profile/pe-headers.txt"
done
