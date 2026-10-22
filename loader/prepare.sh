#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"
mkdir -p sources out
fetch() {
  git init -q "$1"
  git -C "$1" fetch -q --depth 1 "$2" "$3"
  git -C "$1" checkout -q FETCH_HEAD
  test "$(git -C "$1" rev-parse HEAD)" = "$3"
}
fetch sources/framework https://github.com/UniXNU/UniXNU.git e95b37d97875bd8b30c976fcdef44d35d9c27bf3
fetch sources/framework/drivers/DarwinBoot https://github.com/UniXNU/DarwinBoot.git d099354d0eab34df5088ca1ba89c9c88bc3260bb
fetch sources/edk2 https://github.com/microsoft/mu_basecore.git cfb93724a06ff86ff5ba971413368a7809ee42a5
fetch sources/xnu https://github.com/apple-oss-distributions/xnu.git 1b191cb58250d0705d8a51287127505aa4bc0789
git -C sources/edk2 submodule update --init --depth 1 \
  MdePkg/Library/BaseFdtLib/libfdt \
  MdePkg/Library/MipiSysTLib/mipisyst \
  BaseTools/Source/C/BrotliCompress/brotli
git -C sources/framework/drivers/DarwinBoot apply --check "$ROOT/loader/patches/darwinboot.patch"
git -C sources/framework/drivers/DarwinBoot apply "$ROOT/loader/patches/darwinboot.patch"
git -C sources/framework apply --check "$ROOT/loader/patches/framework.patch"
git -C sources/framework apply "$ROOT/loader/patches/framework.patch"
{
  for repo in sources/framework sources/framework/drivers/DarwinBoot sources/edk2 sources/xnu; do
    printf '%s ' "$repo"
    git -C "$repo" rev-parse HEAD
  done
  shasum -a 256 loader/patches/*.patch loader/scripts/*.py
} > out/source-lock.txt
