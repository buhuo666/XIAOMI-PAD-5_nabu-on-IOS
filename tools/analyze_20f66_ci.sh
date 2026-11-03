#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p log/ci/native-20f66
python3 tools/fetch_sources.py --only XnuPrelink lzfse --report log/ci/native-20f66/sources.json
python3 tools/fetch_ipsw_members.py
BASE=OS/ipados/16.5-20F66-iPad7_11
cp "$BASE/manifests/download-receipt.json" log/ci/native-20f66/download-receipt.json
python3 - <<'PY'
import hashlib,json,pathlib
config=json.load(open('configs/native-analysis-20f66.json'))
path=pathlib.Path('OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.release.ipad7c')
assert hashlib.sha256(path.read_bytes()).hexdigest()==config['kernelcache_im4p_sha256']
PY
python3 tools/inspect_kernelcache.py "$BASE/extracted/kernelcache.release.ipad7c" --payload-output build/kernelcache.20f66.lzfse
make -C src/lzfse -j3 > log/ci/native-20f66/lzfse-build.log 2>&1
src/lzfse/build/bin/lzfse -decode -i build/kernelcache.20f66.lzfse -o "$BASE/extracted/kernelcache.decoded.macho"
python3 tools/inspect_kernelcache.py "$BASE/extracted/kernelcache.decoded.macho" --report log/ci/native-20f66/original-metadata.json
python3 tools/analyze_20f66_native.py --original "$BASE/extracted/kernelcache.arm64.macho" \
  --candidate artifacts/8796-reference/mach.development.bcm2837.unstripped
python3 tools/inspect_iig_20f66.py --original "$BASE/extracted/kernelcache.arm64.macho" \
  --candidate artifacts/8796-reference/mach.development.bcm2837.unstripped \
  --analysis log/ci/native-20f66/instructions.json \
  --headers log/ci/iig-8796/obj/DEVELOPMENT_ARM64_BCM2837/iokit/DriverKit \
  --output log/ci/native-20f66/iig-review.json --require-legacy-reply-checks
