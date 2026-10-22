#!/usr/bin/env python3
"""Host checks for the diagnostic ADT and actual loader guard helpers."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adt = load("diagnostic_adt", ROOT / "scripts/make-nabu-diagnostic-adt.py")
contract = load("boot_contract", ROOT / "scripts/check-boot-contract.py")


class DiagnosticTests(unittest.TestCase):
    def test_diagnostic_tree_contract(self):
        nodes = contract.read_adt(adt.build(0x300000000, 0x10000000))
        self.assertIn("/arm-io/gic", nodes)
        self.assertEqual(list(path for path in nodes if path.startswith("/cpus/")), ["/cpus/cpu0"])
        self.assertEqual(set(nodes["/chosen/memory-map"]), {"name"})
        self.assertEqual(nodes["/chosen"]["random-seed"], bytes(64))
        self.assertFalse(any("ufs" in path.lower() for path in nodes))
        self.assertNotIn("/psci", nodes)

    def test_invalid_memory_sizes(self):
        for size in (0, 0xfffffff, 0x10001000, 0x20000000, 0x20200000, 0x300000000):
            with self.subTest(size=hex(size)), self.assertRaises(ValueError):
                adt.build(0x300000000, size)

    def test_malformed_tree(self):
        tree = adt.build(0x300000000, 0x10000000)
        for raw in (b"", tree[:-1], tree + b"\0", b"\xff" * 8):
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                contract.read_adt(raw)

    def test_payload_argument_limits(self):
        sys.path.insert(0, str(FRAMEWORK / "scripts"))
        from unixnu.payload import check_args
        from unixnu.util import Error
        for major, limit in ((22, 607), (23, 1000)):
            self.assertEqual(len(check_args(["a" * limit], major)), limit)
            with self.assertRaises(Error):
                check_args(["a" * (limit + 1)], major)
        with self.assertRaises(Error):
            check_args(["a=\u4e2d"], 22)

    def test_actual_window_and_video_helpers(self):
        driver = FRAMEWORK / "drivers/DarwinBoot/DarwinBootPkg/Driver"
        source = r"""
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
typedef uint64_t UINT64;
typedef uint8_t UINT8;
typedef size_t UINTN;
#define CompareMem memcmp
#define MAX_UINT64 UINT64_MAX
#define DARWINBOOT_XNU_MAJOR 22
#define DARWINBOOT_NABU_DIAGNOSTIC 1
#include "NabuDiagnostic.h"
int main(void) {
  UINT64 p=0, video[6]={0x9c000000,1,6400,1600,2560,32};
  assert(DarwinNabuVideoValid(video));
  for (int i=0;i<6;i++) {
    video[i]++;
    assert(!DarwinNabuVideoValid(video));
    video[i]--;
  }
  assert(DarwinWindowCandidate(0xa4000000,0x100000000,0xfffffe0007004000,
                              0x10000000,0x100000000,&p) && p==0xa5004000);
  assert(DarwinWindowCandidate(0x48000000,0x80000000,0xfffffe0007004000,
                              0x10000000,0x100000000,&p) && p==0x49004000);
  assert(DarwinWindowCandidate(0x49004000,0x59004000,0xfffffe0007004000,
                              0x10000000,0x100000000,&p) && p==0x49004000);
  assert(!DarwinWindowCandidate(0x49004001,0x59004001,0xfffffe0007004000,
                               0x10000000,0x100000000,&p));
  assert(!DarwinWindowCandidate(0x100000000,0x300000000,0x4000,
                               0x10000000,0x100000000,&p));
  assert(!DarwinWindowCandidate(0xf0000000,0x200000000,0x4000,
                               0x10000000,0x100000000,&p));
  assert(DarwinWindowCandidate(0x100000000,0x300000000,0x4000,
                              0x10000000,UINT64_MAX,&p));
  assert(!DarwinWindowCandidate(UINT64_MAX-1,UINT64_MAX,0x4000,
                               0x10000000,UINT64_MAX,&p));
  return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="nabu-guard-test-") as work:
            work = Path(work)
            code, binary = work / "guards.c", work / "guards.exe"
            code.write_text(source, encoding="ascii")
            subprocess.run([CC, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            f"-I{driver}", str(code), "-o", str(binary)],
                           check=True, timeout=60)
            subprocess.run([str(binary)], check=True, timeout=30)

    def test_actual_kernel_and_adt_parsers(self):
        base = 0xfffffff007004000
        def segment(address):
            return struct.pack("<II16sQQQQiiII", 0x19, 72, b"__TEXT", address,
                               0x1000, 0, 0x1000, 5, 5, 0, 0)
        state = bytearray(272)
        struct.pack_into("<Q", state, 256, base + 0x400)
        commands = segment(base) + struct.pack("<IIII", 5, 288, 6, 68) + state
        image = bytearray(0x1000)
        image[:32] = struct.pack("<8I", 0xfeedfacf, 0x100000c, 0, 2, 2, len(commands), 0, 0)
        image[32:32 + len(commands)] = commands
        variants = {"valid": image, "short": image[:31]}
        for label, offset, fmt, value in (
            ("subtype", 8, "<I", 2), ("commands-overrun", 20, "<I", len(image)),
            ("short-command", 36, "<I", 4), ("file-overrun", 32 + 48, "<Q", 0x1001),
            ("entry-outside", 32 + 72 + 272, "<Q", base + 0x2000),
            ("entry-unaligned", 32 + 72 + 272, "<Q", base + 0x401),
            ("segment-wrap", 32 + 24, "<Q", (1 << 64) - 0x800),
        ):
            broken = bytearray(image)
            struct.pack_into(fmt, broken, offset, value)
            variants[label] = broken
        overlapping = bytearray(image)
        overlap_commands = commands + segment(base)
        overlapping[32:32 + len(overlap_commands)] = overlap_commands
        struct.pack_into("<II", overlapping, 16, 3, len(overlap_commands))
        variants["overlap"] = overlapping
        tree = adt.build(0x300000000, 0x10000000)
        forbidden = adt.node("device-tree", children=[adt.node("nabu-ufs")])
        with tempfile.TemporaryDirectory(prefix="nabu-parser-test-") as work:
            work = Path(work)
            kernel, dt = work / "kernel", work / "tree"
            for major, diagnostic in ((22, False), (23, False), (22, True)):
                binary = contract.compile_parser(FRAMEWORK, CC, work, major, diagnostic)
                for label, data in variants.items():
                    kernel.write_bytes(data)
                    result = json.loads(contract.run([binary, kernel]))
                    with self.subTest(profile=(major, diagnostic), kernel=label):
                        self.assertEqual(result["kernel_status"] == 0, label == "valid")
                kernel.write_bytes(image)
                for label, data, accepted in (
                    ("valid", tree, True), ("truncated", tree[:-1], False),
                    ("trailing", tree + b"\0", False),
                    ("storage", forbidden, not diagnostic),
                    ("psci", adt.node("device-tree", children=[adt.node("psci")]), not diagnostic),
                    ("short-seed", adt.node("device-tree", children=[adt.node(
                        "chosen", [("random-seed", bytes(63))])]), False),
                    ("misplaced-seed", adt.node("device-tree", [("random-seed", bytes(64))]), False),
                    ("duplicate-seed", adt.node("device-tree", children=[adt.node(
                        "chosen", [("random-seed", bytes(64)), ("random-seed", bytes(64))])]), False),
                ):
                    dt.write_bytes(data)
                    result = json.loads(contract.run([binary, kernel, dt]))
                    with self.subTest(profile=(major, diagnostic), tree=label):
                        self.assertEqual(result["adt_parser_accepts"], accepted)

    def test_actual_entropy_helper_refuses_failed_sources(self):
        source = (FRAMEWORK / "drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c").read_text()
        helper = contract.extract(source, "STATIC\nEFI_STATUS\nFillBootSeed (",
                                  "\nSTATIC\nEFI_STATUS\nGetMap (")
        prelude = r"""
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <assert.h>
typedef uint8_t UINT8;
typedef void VOID;
typedef int EFI_STATUS;
typedef struct RNG EFI_RNG_PROTOCOL;
struct RNG { EFI_STATUS (*GetRNG)(EFI_RNG_PROTOCOL *, VOID *, size_t, UINT8 *); };
#define STATIC static
#define EFI_SUCCESS 0
#define EFI_DEVICE_ERROR 7
#define EFI_ERROR(s) ((s)!=0)
#define ZeroMem(p,n) memset(p,0,n)
static int mode, calls, gEfiRngProtocolGuid;
static int IsZeroBuffer(const void *p, size_t n) {
  const UINT8 *b=p;
  for (size_t i=0;i<n;i++) if(b[i]) return 0;
  return 1;
}
static EFI_STATUS get(EFI_RNG_PROTOCOL *p, VOID *algorithm, size_t size, UINT8 *out) {
  (void)p; assert(algorithm==NULL && size==64); calls++;
  if(mode==1) { memset(out,0xa5,size); return 9; }
  if(mode!=2) for(size_t i=0;i<size;i++) out[i]=(UINT8)(i+1);
  return 0;
}
static EFI_RNG_PROTOCOL rng={get};
static EFI_STATUS locate(VOID *guid, VOID *registration, VOID **out) {
  assert(guid==&gEfiRngProtocolGuid && registration==NULL);
  if(mode==0) return 14;
  *out=&rng; return 0;
}
static struct { EFI_STATUS (*LocateProtocol)(VOID *,VOID *,VOID **); } bs={locate}, *gBS=&bs;
"""
        main = r"""
int main(void) {
  UINT8 seed[64];
  for(mode=0;mode<4;mode++) {
    memset(seed,0xcc,sizeof(seed)); calls=0;
    EFI_STATUS status=FillBootSeed(seed);
    assert(calls==(mode==0?0:1));
    if(mode<3) assert(status!=0 && IsZeroBuffer(seed,64));
    else {
      assert(status==0);
      for(size_t i=0;i<64;i++) assert(seed[i]==i+1);
    }
  }
  return 0;
}
"""
        with tempfile.TemporaryDirectory(prefix="nabu-entropy-test-") as work:
            work = Path(work)
            code, binary = work / "entropy.c", work / "entropy.exe"
            code.write_text(prelude + helper + main, encoding="ascii")
            subprocess.run([CC, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            str(code), "-o", str(binary)], check=True, timeout=60)
            subprocess.run([str(binary)], check=True, timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    args, rest = parser.parse_known_args()
    FRAMEWORK, CC = args.framework.resolve(), args.cc
    unittest.main(argv=[sys.argv[0], *rest])
