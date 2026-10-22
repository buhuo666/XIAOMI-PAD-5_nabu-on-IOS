#!/usr/bin/env python3
"""Exercise the patched boot-CPU checkpoint function, stubbing only display text."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--xnu-source", type=Path, required=True)
parser.add_argument("--cc", default="clang")
args = parser.parse_args()
source = (args.xnu_source / "osfmk/arm64/nabu_early.c").read_text(encoding="utf-8")
start = source.index("void\nnabu_early_mark(")
function = source[start:source.index("\nvoid\nnabu_early_panic(", start)]
assert "volatile uint32_t nabu_early_stage_mask;" in source
# The host test checks C state and bounds, not Arm memory-barrier semantics.
function = function.replace('__asm__ volatile("dsb sy" ::: "memory");', "")
prelude = r"""
#include <assert.h>
#include <stdint.h>
#include <string.h>
#define EARLY_WIDTH 1600u
#define EARLY_HEIGHT 2560u
#define EARLY_STRIDE 1600u
static uint32_t pixels[EARLY_WIDTH * EARLY_HEIGHT];
#define EARLY_FB pixels
static unsigned int early_disabled;
volatile uint32_t nabu_early_stage_mask;
static void nabu_early_string(const char *s) { (void)s; }
static void nabu_early_putc(char c) { (void)c; }
"""
main = r"""
int main(void) {
  nabu_early_mark(1,"first");
  assert(nabu_early_stage_mask==(1u<<1));
  assert(pixels[(EARLY_HEIGHT-32)*EARLY_STRIDE+48]==0xff20ff00u);
  nabu_early_mark(20,"last");
  assert(nabu_early_stage_mask==((1u<<1)|(1u<<20)));
  nabu_early_mark(1,"repeat");
  assert(nabu_early_stage_mask==((1u<<1)|(1u<<20)));
  memset(pixels,0,sizeof(pixels));
  assert(nabu_early_stage_mask==((1u<<1)|(1u<<20)));
  nabu_early_mark(21,"invalid");
  nabu_early_mark(32,"invalid shift");
  assert(nabu_early_stage_mask==((1u<<1)|(1u<<20)));
  early_disabled=1;
  nabu_early_mark(2,"disabled");
  assert(nabu_early_stage_mask==((1u<<1)|(1u<<20)));
  return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="nabu-stage-mask-") as work:
    work = Path(work)
    code, binary = work / "stages.c", work / "stages.exe"
    code.write_text(prelude + function + main, encoding="ascii")
    subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    str(code), "-o", str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=30)
print("Actual early-stage function: persistent mask, repeated, invalid and disabled stages PASS")
