#!/usr/bin/env python3
"""Test the six exact launchd-cache pins and refusal gates in the real header."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HASHES = (
    "336caad51c9382131139edff75a9ca29dc5df51c",
    "48d2f579b4afb2428f07c73d959b826d7d815720",
    "15f825624810393964df58a7a032cb815e9a2a5f",
    "727205892a0eaf5496d62c9c9d4b81b11f35a631",
    "eeb5fe94bc9266fc62bcb52fbea447889ff5801b",
    "69e6e0b4804260f06ccbae063faec166c34de9a9",
)
SOURCE_PLIST_SHA = "5f57ec7aa0489146548ddcc19222a0d76f2427bd7d55bd5c3cfbb87db6f36ff6"
SOURCE_SIG_SHA = "665d817426926b0cef059bc4673403731631f8c49109dc3092deef2e63f052b4"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", type=Path, required=True)
    parser.add_argument("--cc", default="clang")
    parser.add_argument("--source-report", type=Path)
    args = parser.parse_args()
    header = args.xnu_source / "iokit/Kernel/arm/NabuAMFIQuery.h"
    text = header.read_text(encoding="utf-8")
    assert SOURCE_PLIST_SHA in text and SOURCE_SIG_SHA in text
    if args.source_report:
        report = json.loads(args.source_report.read_text(encoding="utf-8"))
        assert report["complete"]
        assert report["source_files"]["System/Library/xpc/launchd.plist"]["sha256"] == SOURCE_PLIST_SHA
        assert report["source_files"]["System/Library/xpc/launchd.plist.sig"]["sha256"] == SOURCE_SIG_SHA
        assert [item["cdhash"] for item in report["code_directories"]] == list(HASHES[-2:])
        assert all(item["all_page_hashes_match"] and item["page_slots"] == 340
                   for item in report["code_directories"])
        inputs = args.source_report.parent / "inputs"
        for name in ("launchd.plist", "launchd.plist.sig"):
            expected = report["source_files"]["System/Library/xpc/" + name]["sha256"]
            assert hashlib.sha256((inputs / name).read_bytes()).hexdigest() == expected
    rows = ",\n".join("{" + ",".join(f"0x{byte:02x}" for byte in bytes.fromhex(value)) + "}"
                     for value in HASHES)
    source = r'''
#include <assert.h>
#include <string.h>
#include "NabuAMFIQuery.h"
static const unsigned char expected[6][20] = { HASH_ROWS };
int main(void) {
    for (unsigned h = 0; h < 6; ++h) {
        assert(nabu_amfi_cache_query(1, expected[h], 20) == 1);
        for (unsigned bit = 0; bit < 160; ++bit) {
            unsigned char changed[20]; memcpy(changed, expected[h], 20);
            changed[bit / 8] ^= 1u << (bit % 8);
            assert(nabu_amfi_cache_query(1, changed, 20) == 0);
        }
        for (unsigned length = 0; length < 64; ++length)
            if (length != 20) assert(nabu_amfi_cache_query(1, expected[h], length) == -1);
        assert(nabu_amfi_cache_query(1, expected[h], ~0ul) == -1);
        assert(nabu_amfi_cache_query(0, expected[h], 20) == -1);
        assert(nabu_amfi_cache_query(2, expected[h], 20) == -1);
        assert(nabu_amfi_cache_query(~0ull, expected[h], 20) == -1);
    }
    assert(nabu_amfi_cache_query(1, 0, 20) == -1);
    unsigned char zero[20] = {0};
    assert(nabu_amfi_cache_query(1, zero, 20) == 0);
    return 0;
}
'''.replace("HASH_ROWS", rows)
    with tempfile.TemporaryDirectory(prefix="nabu-amfi-source-") as directory:
        temp = Path(directory)
        program = temp / "query.c"
        binary = temp / "query"
        program.write_text(source, encoding="utf-8", newline="\n")
        subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-I", str(header.parent), str(program), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
    print("AMFI current-source pins passed: six exact hashes, 960 one-bit mutations, invalid lengths/kinds, NULL and unknown hash.")
    if args.source_report:
        print("Current-source plist/signature bytes and two 340-page CodeDirectories bound to the test.")


if __name__ == "__main__":
    main()
