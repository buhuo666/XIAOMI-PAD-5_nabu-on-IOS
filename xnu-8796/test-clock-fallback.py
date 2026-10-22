#!/usr/bin/env python3
"""Exercise the actual patched platform clock calculation with stub DT input."""
import argparse
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--xnu-source", type=Path, required=True)
parser.add_argument("--cc", default="clang")
args = parser.parse_args()
header = (args.xnu_source / "pexpert/pexpert/pexpert.h").read_text(encoding="utf-8")
start = header.index("struct clock_frequency_info_t {")
clock_type = header[start:header.index("\n};", start) + 3]
source = (args.xnu_source / "pexpert/arm/pe_identify_machine.c").read_text(encoding="utf-8")
start = source.index("void\npe_identify_machine(")
function = source[start:source.index("\nvm_offset_t\npe_arm_get_soc_base_phys", start)]
prelude = r"""
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#define NABU 1
#ifndef bzero
#define bzero(p,n) memset(p,0,n)
#endif
#define kSuccess 0
typedef void *DTEntry;
typedef int OpaqueDTEntryIterator;
typedef void boot_args;
static uint32_t bus, cpu, timer;
static int supply;
static uintptr_t pe_arm_get_soc_base_phys(void) { return 0x17000000; }
static int SecureDTLookupEntry(void *root,const char *path,DTEntry *entry) {
  (void)root; (void)path; *entry=(void*)1; return 0;
}
static int SecureDTInitEntryIterator(DTEntry entry,int *iter) {
  (void)entry; *iter=0; return 0;
}
static int SecureDTIterateEntries(int *iter,DTEntry *entry) {
  *entry=(void*)2; return (*iter)++ ? 1 : 0;
}
static int SecureDTGetProperty(DTEntry entry,const char *name,
                               const void **value,unsigned int *size) {
  (void)entry;
  if (!strcmp(name,"state")) { *value="running"; *size=8; return 0; }
  if (!supply) return 1;
  if (!strcmp(name,"bus-frequency")) *value=&bus;
  else if (!strcmp(name,"clock-frequency")) *value=&cpu;
  else if (!strcmp(name,"timebase-frequency")) *value=&timer;
  else return 1;
  *size=4; return 0;
}
"""
main = r"""
int main(void) {
  supply=0;
  pe_identify_machine(NULL);
  assert(gPEClockFrequencyInfo.bus_clock_rate_hz==100000000);
  assert(gPEClockFrequencyInfo.cpu_clock_rate_hz==400000000);
  assert(gPEClockFrequencyInfo.dec_clock_rate_hz>0);
  assert(gPEClockFrequencyInfo.bus_to_cpu_rate_num==8);
  supply=1; bus=200000000; cpu=800000000; timer=19200000;
  pe_identify_machine(NULL);
  assert(gPEClockFrequencyInfo.bus_clock_rate_hz==bus);
  assert(gPEClockFrequencyInfo.cpu_clock_rate_hz==cpu);
  assert(gPEClockFrequencyInfo.dec_clock_rate_hz==timer);
  assert(gPEClockFrequencyInfo.bus_to_cpu_rate_num==8);
  assert(gPEClockFrequencyInfo.bus_to_dec_rate_den==10);
  bus=cpu=timer=0;
  pe_identify_machine(NULL);
  assert(gPEClockFrequencyInfo.bus_clock_rate_hz==100000000);
  assert(gPEClockFrequencyInfo.cpu_clock_rate_hz==400000000);
  assert(gPEClockFrequencyInfo.timebase_frequency_hz==19200000);
  assert(gPEClockFrequencyInfo.dec_clock_rate_hz==19200000);
  puts("NABU clock fallback: absent, supplied and zero properties PASS");
  return 0;
}
"""
with tempfile.TemporaryDirectory(prefix="nabu-clock-test-") as work:
    code, binary = Path(work) / "clock.c", Path(work) / "clock-test.exe"
    code.write_text(prelude + clock_type +
                    "\ntypedef struct clock_frequency_info_t clock_frequency_info_t;\n" +
                    "\nstatic struct clock_frequency_info_t gPEClockFrequencyInfo;\n" +
                    function + main, encoding="ascii")
    subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                    str(code), "-o", str(binary)], check=True, timeout=60)
    subprocess.run([str(binary)], check=True, timeout=30)
