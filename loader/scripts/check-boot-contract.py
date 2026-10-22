#!/usr/bin/env python3
"""Compile the actual DarwinBoot parsers on the host and inspect a payload offline."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def extract(source, start, end):
    return source[source.index(start):source.index(end, source.index(start))]


def run(command):
    result = subprocess.run([str(item) for item in command], capture_output=True,
                            text=True, check=True, timeout=60)
    return result.stdout.strip()


def read_adt(data):
    """Parse bounded Apple DT records, preserving node paths and property bytes."""
    nodes = {}
    offset = 0

    def node(parent, depth):
        nonlocal offset
        if depth > 64 or len(data) - offset < 8:
            raise ValueError("truncated or excessively deep ADT")
        nprops, nchildren = struct.unpack_from("<II", data, offset)
        offset += 8
        props = {}
        if nprops > (len(data) - offset) // 36:
            raise ValueError("ADT property count exceeds remaining bytes")
        for _ in range(nprops):
            if len(data) - offset < 36:
                raise ValueError("truncated ADT property")
            key, size = struct.unpack_from("<32sI", data, offset)
            offset += 36
            if b"\0" not in key or size > len(data) - offset:
                raise ValueError("invalid ADT property")
            key = key.split(b"\0", 1)[0].decode("ascii")
            if key in props:
                raise ValueError(f"duplicate ADT property: {key}")
            props[key] = data[offset:offset + size]
            offset = (offset + size + 3) & ~3
            if offset > len(data):
                raise ValueError("truncated ADT padding")
        name = props.get("name", b"")
        if not name.endswith(b"\0") or b"\0" in name[:-1]:
            raise ValueError("ADT node has no valid name")
        name = name[:-1].decode("ascii")
        path = "/" if depth == 0 else parent.rstrip("/") + "/" + name
        if path in nodes:
            raise ValueError(f"duplicate ADT path: {path}")
        nodes[path] = props
        if nchildren > (len(data) - offset) // 8:
            raise ValueError("ADT child count exceeds remaining bytes")
        for _ in range(nchildren):
            node(path, depth + 1)

    node("", 0)
    if offset != len(data):
        raise ValueError("ADT has trailing bytes")
    return nodes


PRELUDE = r"""
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "BootArgs.h"
#include "WindowSize.h"
typedef size_t UINTN;
typedef int BOOLEAN;
typedef int EFI_STATUS;
#define STATIC static
#define CONST const
#define TRUE 1
#define FALSE 0
#define MAX_UINTN SIZE_MAX
#define MAX_UINT64 UINT64_MAX
#define EFI_SUCCESS 0
#define EFI_UNSUPPORTED 1
#define EFI_LOAD_ERROR 2
#define SIZE_2MB 0x200000ULL
#define WINDOW_SIZE 0x10000000ULL
#define BLOCK_SIZE SIZE_2MB
#define EFI_PAGE_MASK 0xfff
#define MAX_SEGMENTS 64
#define ALIGN_VALUE(a,b) (((a)+(b)-1)&~((b)-1))
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define AsciiStrCmp strcmp
#define CompareMem memcmp
#define ZeroMem(p,n) memset(p,0,n)
static const void *ScanMem8(const void *p,size_t n,int v){return memchr(p,v,n);}
static UINT32 U32(const void *p){UINT32 v;memcpy(&v,p,4);return v;}
static UINT64 U64(const void *p){UINT64 v;memcpy(&v,p,8);return v;}
#include "NabuDiagnostic.h"
"""

MAIN = r"""
static unsigned char *read_file(const char *path, size_t *size) {
  FILE *f=fopen(path,"rb"); long n; unsigned char *p;
  if (!f || fseek(f,0,SEEK_END) || (n=ftell(f))<0 || fseek(f,0,SEEK_SET)) exit(10);
  p=malloc(n ? (size_t)n : 1);
  if (!p || fread(p,1,(size_t)n,f)!=(size_t)n) exit(11);
  fclose(f); *size=(size_t)n; return p;
}
int main(int argc,char **argv) {
  KERNEL k; size_t n; unsigned char *b; int status;
  if (argc<2) return 12;
  b=read_file(argv[1],&n); status=ParseKernel(b,n,&k); free(b);
  printf("{\"kernel_status\":%d,\"abi\":%d,\"command_line_bytes\":%zu,"
         "\"boot_flags_offset\":%zu,\"memory_actual_offset\":%zu,\"boot_args_bytes\":%zu",
         status,DARWINBOOT_XNU_MAJOR,sizeof(((DARWIN_BOOT_ARGS*)0)->CommandLine),
         offsetof(DARWIN_BOOT_ARGS,BootFlags),offsetof(DARWIN_BOOT_ARGS,MemorySizeActual),
         sizeof(DARWIN_BOOT_ARGS));
  if (!status) printf(",\"segments\":%zu,\"virtual_base\":\"0x%llx\","
                     "\"virtual_end\":\"0x%llx\",\"entry\":\"0x%llx\",\"span_bytes\":%llu",
                     k.Count,(unsigned long long)k.Base,(unsigned long long)k.End,
                     (unsigned long long)k.Entry,(unsigned long long)(k.End-k.Base));
  if (argc>2) {
    UINTN at=0,r=MAX_UINTN,t=MAX_UINTN,a=MAX_UINTN;
    UINT64 w=0; BOOLEAN packed=FALSE; int ok;
    b=read_file(argv[2],&n);
    ok=AdtNode(b,n,&at,0,3,&r,&t,&a,&w,&packed) && at==n;
    printf(",\"adt_parser_accepts\":%s,\"owned_window_bytes\":%llu,"
           "\"ramdisk_placeholder\":%s,\"trust_cache_placeholder\":%s,"
           "\"gpu_addon_placeholder\":%s,\"packed_ramdisk\":%s",
           ok?"true":"false",(unsigned long long)(w?w:WINDOW_SIZE),
           r!=MAX_UINTN?"true":"false",t!=MAX_UINTN?"true":"false",
           a!=MAX_UINTN?"true":"false",packed?"true":"false");
    free(b);
  }
  puts("}"); return 0;
}
"""


def compile_parser(framework, cc, work, major, diagnostic=False):
    driver = framework / "drivers/DarwinBoot/DarwinBootPkg/Driver"
    source = (driver / "DarwinBoot.c").read_text(encoding="utf-8")
    code = (PRELUDE + extract(source, "typedef struct {", "\nSTATIC EFI_HANDLE")
            + extract(source, "STATIC\nEFI_STATUS\nParseKernel (",
                      "\nSTATIC\nBOOLEAN\nValidTrustCaches") + MAIN)
    (work / "Base.h").write_text(
        "#include <stdint.h>\n#include <stddef.h>\n"
        "typedef uint16_t UINT16; typedef uint32_t UINT32; typedef uint64_t UINT64;\n"
        "typedef uint8_t UINT8; typedef char CHAR8; typedef void VOID;\n"
        "#define STATIC_ASSERT _Static_assert\n#define OFFSET_OF offsetof\n",
        encoding="ascii")
    harness = work / "contract.c"
    harness.write_text(code, encoding="ascii")
    binary = work / f"contract-{major}-{int(diagnostic)}.exe"
    run([cc, "-std=c11", "-D__USE_MINGW_ANSI_STDIO=1", "-Wall", "-Wextra", "-Werror",
         f"-DDARWINBOOT_XNU_MAJOR={major}", f"-DDARWINBOOT_NABU_DIAGNOSTIC={int(diagnostic)}",
         f"-I{work}", f"-I{driver}", harness, "-o", binary])
    return binary


def check(args):
    driver = args.framework / "drivers/DarwinBoot/DarwinBootPkg/Driver"
    source_path = driver / "DarwinBoot.c"
    cc = shutil.which(args.cc)
    if not cc:
        raise ValueError(f"C compiler not found: {args.cc}")
    with tempfile.TemporaryDirectory(prefix="nabu-boot-contract-") as work:
        work = Path(work)
        layouts = {}
        for major in (22, 23):
            binary = compile_parser(args.framework, cc, work, major)
            layouts[str(major)] = json.loads(run([binary, args.kernel, *([args.adt] if args.adt else [])]))
        binary = compile_parser(args.framework, cc, work, 22, diagnostic=True)
        diagnostic = json.loads(run([binary, args.kernel, *([args.adt] if args.adt else [])]))
        # Compare with the selected real XNU source, independently of loader assertions.
        source_abi = None
        if args.xnu_source:
            header = args.xnu_source / "pexpert/pexpert/arm64/boot.h"
            text = header.read_text(encoding="utf-8")
            text = re.sub(r"^\s*#include[^\n]*", "", text, flags=re.MULTILINE)
            # ARM64 Darwin is LP64; Windows hosts use LLP64 (unsigned long is 32-bit).
            # Pin the six Boot_Video words to the target width for the host probe.
            text = re.sub(r"\bunsigned\s+long\b", "uint64_t", text)
            (work / "xnu-abi.c").write_text(
                "#include <stdint.h>\n#include <stddef.h>\n#include <stdio.h>\n" + text +
                '\nint main(void){printf("%d %zu %zu %zu\\n",BOOT_LINE_LENGTH,'
                "offsetof(boot_args,bootFlags),offsetof(boot_args,memSizeActual),sizeof(boot_args));}\n",
                encoding="ascii")
            binary = work / "xnu-abi.exe"
            run([cc, "-std=c11", "-D__USE_MINGW_ANSI_STDIO=1", work / "xnu-abi.c", "-o", binary])
            actual = list(map(int, run([binary]).split()))
            selected = layouts[str(args.xnu_major)]
            expected = [selected[key] for key in ("command_line_bytes", "boot_flags_offset",
                                                 "memory_actual_offset", "boot_args_bytes")]
            if actual != expected:
                raise ValueError(f"XNU source ABI {actual} does not match Darwin {args.xnu_major}: {expected}")
            source_abi = {"header_sha256": sha256(header), "matches_selected_loader_abi": True}
    selected = layouts[str(args.xnu_major)]
    blockers = ["UEFI allocation, ExitBootServices, CPU handoff and device hardware have not been tested.",
                "Loader binary must be rebuilt with the selected ABI; this does not modify existing firmware."]
    if selected["kernel_status"]:
        blockers.append("The actual DarwinBoot Mach-O parser rejected this kernel.")
    if args.adt:
        if not selected["adt_parser_accepts"]:
            blockers.append("The actual DarwinBoot ADT parser rejected this device tree.")
        nodes = read_adt(args.adt.read_bytes())
        selected["adt_node_paths"] = list(nodes)
        selected["adt_sha256"] = sha256(args.adt)
        if args.xnu_major == 22 and "/arm-io/gic" not in nodes:
            blockers.append("xnu-8796 requires /arm-io/gic, which this ADT lacks.")
        if args.xnu_major == 22:
            blockers.append("NABU bootstrap still hardcodes framebuffer 0x9c000000 and assumes low physical memory; verify before any device boot.")
        for flag, label in (("ramdisk_placeholder", "RAMDisk"),
                            ("trust_cache_placeholder", "TrustCache"),
                            ("gpu_addon_placeholder", "GpuAddon")):
            if selected[flag]:
                blockers.append(f"ADT contains {label}; the loader requires a matching validated sidecar.")
        if "/nabu-ufs" in nodes:
            blockers.append("ADT exposes /nabu-ufs; it is not a storage-isolated diagnostic tree.")
    report = {"kernel": str(args.kernel), "kernel_sha256": sha256(args.kernel),
              "loader_source_sha256": sha256(source_path),
              "boot_args_header_sha256": sha256(driver / "BootArgs.h"),
              "selected_xnu_major": args.xnu_major, "layouts": layouts,
              "nabu_diagnostic_parser": diagnostic, "xnu_source_abi": source_abi,
              "blockers": blockers, "hardware_tested": False, "ready_to_boot": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if selected["kernel_status"] == 0 and selected.get("adt_parser_accepts", True) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--adt", type=Path)
    parser.add_argument("--xnu-source", type=Path)
    parser.add_argument("--xnu-major", type=int, choices=(22, 23), default=22)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name in ("framework", "kernel", "adt", "xnu_source", "output"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    try:
        return check(args)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(2, f"boot contract check failed: {error}\n"
                    f"{getattr(error, 'stderr', '') or ''}")


if __name__ == "__main__":
    raise SystemExit(main())
