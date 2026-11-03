#!/usr/bin/env python3
"""Host-check actual DarwinBoot/8796 ABI, command-line code and size predicate.

This executes extracted scalar code on an LP64 host. It never executes UEFI or
XNU, allocates a device window, edits the source trees, or authorizes a boot map.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
XNU_COMMIT = "c54f35ca767986246321eb901baf8f5ff7923f6a"
FIELD_PAIRS = [
    ("Revision", "Revision"), ("Version", "Version"),
    ("virtBase", "VirtualBase"), ("physBase", "PhysicalBase"),
    ("memSize", "MemorySize"), ("topOfKernelData", "TopOfKernelData"),
    ("Video", "Video"), ("machineType", "MachineType"),
    ("deviceTreeP", "DeviceTree"), ("deviceTreeLength", "DeviceTreeLength"),
    ("CommandLine", "CommandLine"), ("bootFlags", "BootFlags"),
    ("memSizeActual", "MemorySizeActual"),
]
VIDEO_FIELDS = ["v_baseAddr", "v_display", "v_rowBytes", "v_width", "v_height", "v_depth"]
WINDOW_YES = [0x10000000, 0x40000000, 0x100000000, 0x100200000,
              0x200000000, 0x200200000, 0x2bfe00000, 0x2c0000000, 0x300000000]
WINDOW_NO = [0, 1, 0xfffffff, 0x10000001, 0x130001000, 0x2bfe01000,
             0x300000001, 0x300200000, (1 << 64) - 1]
WIDE_VALUES = [0x100000000, 0x100004000, 0x2bfe00000, 0x300000000, 0x380000000]


def identity(path):
    data = path.read_bytes()
    return {"path": path.resolve().as_posix(), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def unique(pattern, source):
    matches = list(re.finditer(pattern, source, re.S))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one actual-source match: {pattern}")
    return matches[0].group(0)


def run(arguments):
    result = subprocess.run(arguments, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {arguments!r}\n"
                           f"{result.stdout}\n{result.stderr}")
    return result.stdout


def host_command(arguments):
    return (["wsl", "-d", "Ubuntu-22.04", "--"] if sys.platform == "win32" else []) + arguments


def host_path(path):
    resolved = path.resolve().as_posix()
    if sys.platform == "win32":
        if len(path.resolve().drive) != 2:
            raise ValueError("WSL compiler requires a local drive path")
        return "/mnt/" + resolved[0].lower() + resolved[2:]
    return resolved


def make_harness(boot, header, source, window):
    video = unique(r"struct Boot_Video \{.*?\n\};", boot)
    structure = unique(r"typedef struct boot_args \{.*?\n\} boot_args;", boot)
    line_define = unique(r"#define BOOT_LINE_LENGTH[^\n]+", boot)
    declaration = unique(r"CHAR8\s+CommandLine\[[^\n]+;", source)
    begin = source.index("  ZeroMem (CommandLine, sizeof (CommandLine));")
    end = source.index("  Root = NULL;", begin)
    command = source[begin:end]
    copy = unique(r"CopyMem \(Args->CommandLine, CommandLine, sizeof \(CommandLine\)\);", source)
    # Only the local identifier is changed to place real buffer operations
    # between host guard words; expressions and rejection branches are retained.
    command = re.sub(r"\bCommandLine\b", "Buffer.CommandLine", command)
    copy = re.sub(r"(?<!->)\bCommandLine\b", "Buffer.CommandLine", copy)
    # Base.h supplies UEFI scalar typedefs and assertions in production. The
    # host prelude below supplies their LP64 equivalents; all actual declarations
    # and header assertions are retained, including explicit padding fields.
    header = re.sub(r"^#include <Base.h>\s*$", "", header, flags=re.M)
    checks = [
        '_Static_assert(sizeof(unsigned long) == 8 && sizeof(void *) == 8, "LP64 host");',
        '_Static_assert(BOOT_LINE_LENGTH == 608, "8796 command-line contract");',
        '_Static_assert(sizeof(boot_args) == 0x2e0, "8796 structure size");',
        '_Static_assert(sizeof(DARWIN_BOOT_ARGS) == sizeof(boot_args), "full ABI size");',
        '_Static_assert(_Alignof(DARWIN_BOOT_ARGS) == _Alignof(boot_args), "ABI alignment");',
    ]
    for xnu, loader in FIELD_PAIRS:
        checks += [
            f'_Static_assert(offsetof(boot_args, {xnu}) == offsetof(DARWIN_BOOT_ARGS, {loader}), "{xnu} offset");',
            f'_Static_assert(sizeof(((boot_args *)0)->{xnu}) == sizeof(((DARWIN_BOOT_ARGS *)0)->{loader}), "{xnu} width");',
        ]
    for i, field in enumerate(VIDEO_FIELDS):
        checks += [
            f'_Static_assert(offsetof(Boot_Video, {field}) == {i} * sizeof(UINT64), "{field} offset");',
            f'_Static_assert(sizeof(((Boot_Video *)0)->{field}) == sizeof(UINT64), "{field} width");',
        ]
    prelude = r'''#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>
typedef uint16_t UINT16;
typedef uint32_t UINT32;
typedef uint64_t UINT64;
typedef size_t UINTN;
typedef char CHAR8;
typedef uint16_t CHAR16;
#define STATIC_ASSERT _Static_assert
#define OFFSET_OF offsetof
#define ZeroMem(p, n) memset((p), 0, (n))
#define CopyMem(d, s, n) memcpy((d), (s), (n))
#define EFI_BAD_BUFFER_SIZE 4
static void Print(const wchar_t *format, ...) { (void)format; }
'''
    result = prelude + line_define + "\n" + video + "\ntypedef struct Boot_Video Boot_Video;\n"
    result += structure + "\n" + header + "\n" + window + "\n" + "\n".join(checks)
    result += "\nstatic int command_line(const CHAR16 *input, DARWIN_BOOT_ARGS *Args) {\n"
    result += "  struct { UINT64 Before; " + declaration + " UINT64 After; } Buffer;\n"
    result += '''  _Static_assert(sizeof(Buffer.CommandLine) == sizeof(Args->CommandLine), "local command buffer width");
  struct { const CHAR16 *BootArgs; } Value = { input }, *Request = &Value;
  UINTN Index;
  memset(&Buffer, 0xa5, sizeof(Buffer));
  const UINT64 Canary = UINT64_C(0xa5a5a5a5a5a5a5a5);
'''
    # Check local sentinels on rejection as well as success, without changing
    # the actual source's conditions, writes, or selected status value.
    command = command.replace("return EFI_BAD_BUFFER_SIZE;",
                              "assert(Buffer.Before == Canary && Buffer.After == Canary); return EFI_BAD_BUFFER_SIZE;")
    result += command + "  " + copy + "\n"
    result += "  assert(Buffer.Before == Canary && Buffer.After == Canary);\n  return 0;\n}\n"
    result += r'''
static unsigned command_cases;
static void check_command(size_t length, int non_ascii, int expected, int null_input) {
  CHAR16 text[1026];
  assert(length < sizeof(text) / sizeof(text[0]));
  for (size_t i = 0; i < length; ++i) text[i] = 'x';
  text[length] = 0;
  if (non_ascii && length) text[length / 2] = 0x80;
  struct { UINT64 Before; DARWIN_BOOT_ARGS Args; UINT64 After; } guarded;
  memset(&guarded, 0xa5, sizeof(guarded));
  guarded.Args.BootFlags = UINT64_C(0x1020304050607080);
  guarded.Args.MemorySizeActual = UINT64_C(0x300000000);
  DARWIN_BOOT_ARGS before;
  memcpy(&before, &guarded.Args, sizeof(before));
  int status = command_line(null_input ? NULL : text, &guarded.Args);
  assert(status == expected);
  assert(guarded.Before == UINT64_C(0xa5a5a5a5a5a5a5a5));
  assert(guarded.After == UINT64_C(0xa5a5a5a5a5a5a5a5));
  if (status == 0) {
    size_t count = null_input ? 0 : length;
    for (size_t i = 0; i < count; ++i) assert(guarded.Args.CommandLine[i] == 'x');
    for (size_t i = count; i < sizeof(guarded.Args.CommandLine); ++i)
      assert(guarded.Args.CommandLine[i] == 0);
    memcpy(before.CommandLine, guarded.Args.CommandLine, sizeof(before.CommandLine));
  }
  assert(memcmp(&before, &guarded.Args, sizeof(before)) == 0);
  ++command_cases;
}
static void check_wide(UINT64 value) {
  DARWIN_BOOT_ARGS loader = {0};
  boot_args kernel;
  loader.Revision = 2; loader.Version = 2;
  loader.VirtualBase = UINT64_C(0xfffffff007004000);
  loader.PhysicalBase = value; loader.MemorySize = value;
  loader.TopOfKernelData = value; loader.MemorySizeActual = value;
  loader.DeviceTree = value; loader.BootFlags = UINT64_C(0x1020304050607080);
  loader.MachineType = 0x89abcdef; loader.DeviceTreeLength = 0x12345678;
  for (size_t i = 0; i < 6; ++i) loader.Video[i] = value + i;
  memcpy(&kernel, &loader, sizeof(kernel));
  assert(kernel.Revision == 2 && kernel.Version == 2);
  assert(kernel.virtBase == loader.VirtualBase);
  assert(kernel.physBase == value && kernel.memSize == value);
  assert(kernel.topOfKernelData == value && kernel.memSizeActual == value);
  assert((uintptr_t)kernel.deviceTreeP == value);
  assert(kernel.bootFlags == loader.BootFlags);
  assert(kernel.machineType == loader.MachineType && kernel.deviceTreeLength == loader.DeviceTreeLength);
'''
    for i, field in enumerate(VIDEO_FIELDS):
        result += f"  assert(kernel.Video.{field} == value + {i});\n"
    result += "}\nint main(void) {\n"
    for key, values in [("yes", WINDOW_YES), ("no", WINDOW_NO), ("wide", WIDE_VALUES)]:
        result += f"  const UINT64 {key}[] = {{" + ",".join(f"UINT64_C({v:#x})" for v in values) + "};\n"
    result += r'''
  for (size_t i = 0; i < sizeof(yes)/sizeof(yes[0]); ++i) assert(DarwinWindowSizeValid(yes[i]));
  for (size_t i = 0; i < sizeof(no)/sizeof(no[0]); ++i) assert(!DarwinWindowSizeValid(no[i]));
  for (size_t i = 0; i < sizeof(wide)/sizeof(wide[0]); ++i) check_wide(wide[i]);
  check_command(0, 0, 0, 1);
  check_command(0, 0, 0, 0);
  check_command(1, 0, 0, 0);
  check_command(606, 0, 0, 0);
  check_command(607, 0, 0, 0);
  check_command(608, 0, EFI_BAD_BUFFER_SIZE, 0);
  check_command(609, 0, EFI_BAD_BUFFER_SIZE, 0);
  check_command(1023, 0, EFI_BAD_BUFFER_SIZE, 0);
  check_command(1, 1, EFI_BAD_BUFFER_SIZE, 0);
  check_command(607, 1, EFI_BAD_BUFFER_SIZE, 0);
  printf("{\"passed\":true,\"command_line_cases\":%u,\"boot_args_size\":%zu,\"memory_actual_offset\":%zu}\n",
    command_cases, sizeof(boot_args), offsetof(boot_args, memSizeActual));
  return 0;
}
'''
    return result, len(checks) + 1 + len(re.findall(r"^STATIC_ASSERT", header, re.M))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True,
                        help="Host generated source/binary/report directory")
    args = parser.parse_args()
    output = args.output.resolve()
    for reserved in (ROOT / "src", ROOT / "device", ROOT / "configs", args.tree.resolve()):
        if output == reserved.resolve() or reserved.resolve() in output.parents:
            raise ValueError(f"Output must not overwrite protected source/input tree: {reserved}")
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "darwinboot-8796-contracts.json"
    report = {"schema_version": 1, "status": "failed", "device_writes_performed": False,
              "device_boot_validated": False, "uefi_allocation_validated": False,
              "scope": "Actual structures, command-line scalar code and parser predicate on LP64 host"}
    try:
        xnu = ROOT / "src/xnu-8796"
        relative = "pexpert/pexpert/arm64/boot.h"
        boot_path = xnu / relative
        if run(["git", "-C", str(xnu), "rev-parse", "HEAD"]).strip() != XNU_COMMIT:
            raise ValueError("8796 input checkout does not match the pinned revision")
        canonical = subprocess.check_output(["git", "-C", str(xnu), "show", "HEAD:" + relative])
        if boot_path.read_bytes() != canonical:
            raise ValueError("8796 boot.h differs from the pinned source")
        paths = {"xnu_boot_h": boot_path,
                 "loader_boot_args_h": args.tree / "DarwinBootPkg/Driver/BootArgs.h",
                 "loader_c": args.tree / "DarwinBootPkg/Driver/DarwinBoot.c",
                 "window_size_h": args.tree / "DarwinBootPkg/Driver/WindowSize.h"}
        report["inputs"] = {name: identity(path) for name, path in paths.items()}
        texts = [path.read_text(encoding="utf-8") for path in paths.values()]
        content, assertions = make_harness(*texts)
        cfile, executable = output / "darwinboot-8796-contracts.c", output / "darwinboot-8796-contracts-host"
        cfile.write_text(content, encoding="utf-8", newline="\n")
        compile_args = ["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                        host_path(cfile), "-o", host_path(executable)]
        report["compiler"] = run(host_command(["clang", "--version"])).splitlines()[0]
        report["compile_command"] = host_command(compile_args)
        run(host_command(compile_args))
        result = json.loads(run(host_command([host_path(executable)])))
        if result != {"passed": True, "command_line_cases": 10,
                      "boot_args_size": 0x2e0, "memory_actual_offset": 0x2d8}:
            raise ValueError(f"Unexpected actual-source harness result: {result}")
        report.update(status="passed", static_assertions=assertions,
                      matching_fields=[{"xnu": x, "loader": l} for x, l in FIELD_PAIRS],
                      matching_video_fields=VIDEO_FIELDS,
                      window_accepted=[hex(v) for v in WINDOW_YES],
                      window_rejected=[hex(v) for v in WINDOW_NO],
                      wide_value_round_trips=[hex(v) for v in WIDE_VALUES],
                      command_line_cases=result["command_line_cases"],
                      command_line_max_ascii_chars=607,
                      harness=identity(cfile), host_binary=identity(executable),
                      script=identity(Path(__file__)), source_tree_modified=False,
                      host_result=result)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        report["error"] = str(error)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "failed", "report": str(report_path), "error": str(error)}))
        return 2
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "static_assertions": assertions,
                      "window_cases": len(WINDOW_YES) + len(WINDOW_NO),
                      "command_line_cases": result["command_line_cases"],
                      "wide_value_cases": len(WIDE_VALUES), "report": identity(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
