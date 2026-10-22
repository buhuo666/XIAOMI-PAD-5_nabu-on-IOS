#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export WORKSPACE=$ROOT/sources/framework
export PACKAGES_PATH=$WORKSPACE/drivers/DarwinBoot:$WORKSPACE/package:$ROOT/sources/edk2
export EDK_TOOLS_PATH=$ROOT/sources/edk2/BaseTools
export CONF_PATH=$ROOT/sources/Conf
export PYTHON_COMMAND=python3
export PATH=$EDK_TOOLS_PATH/BinWrappers/PosixLike:$EDK_TOOLS_PATH/Source/C/bin:$PATH
cd "$WORKSPACE"
build -p DarwinBootPkg/DarwinBoot.dsc -m Test/QemuNabuEnvironment.inf \
  -a AARCH64 -b DEBUG -t CLANGPDB -n 3 \
  -D DARWINBOOT_XNU_MAJOR=22 -D DARWINBOOT_QEMU_EXPERIMENT=1
cp build/DarwinBoot/DEBUG_CLANGPDB/AARCH64/QemuNabuEnvironment.efi "$ROOT/out/"
cd "$ROOT"
python3 loader/observe-kernel.py
