#!/usr/bin/env python3
"""Execute the actual boot trace filter and start gate with kernel shims."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile

REGION = r"""
static struct nabu_bt_queue nabu_bt_events;
static unsigned int nabu_bt_enabled, nabu_bt_started;
static uint64_t nabu_bt_id;

/* Exact p_comm filter; an empty list traces every process. */
static char nabu_bt_names[NABU_BT_MAX_NAMES][NABU_BT_NAME];
static unsigned int nabu_bt_name_count;
static unsigned int nabu_bt_kind_mask;
static uint64_t nabu_bt_filtered;

static void
nabu_bt_add_name(const char *name, unsigned int length)
{
	if (!length || length >= NABU_BT_NAME || nabu_bt_name_count == NABU_BT_MAX_NAMES) {
		return;
	}
	for (unsigned int i = 0; i < length; ++i) {
		nabu_bt_names[nabu_bt_name_count][i] = name[i];
	}
	nabu_bt_name_count++;
}

static void
nabu_bt_parse_names(const char *argument)
{
	unsigned int start = 0;
	for (unsigned int at = 0; ; ++at) {
		char byte = argument[at];
		if (byte == ',' || byte == 0) {
			nabu_bt_add_name(argument + start, at - start);
			if (!byte) {
				break;
			}
			start = at + 1;
		}
	}
}

static int
nabu_bt_match(proc_t p, unsigned int kind)
{
	if (!(nabu_bt_kind_mask & (1u << kind))) {
		return 0;
	}
	if (!nabu_bt_name_count) {
		return 1;
	}
	if (!p) {
		return 0;
	}
	for (unsigned int i = 0; i < nabu_bt_name_count; ++i) {
		if (strncmp(nabu_bt_names[i], p->p_comm, NABU_BT_NAME) == 0) {
			return 1;
		}
	}
	return 0;
}
"""


PRELUDE = r"""
#define ARM64_BOARD_CONFIG_NABU 1
#include <assert.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include "sys/nabu_boottrace.h"
#include "sys/nabu_boottrace_queue.h"

typedef struct proc { char p_comm[NABU_BT_NAME]; } *proc_t;
#define KERN_SUCCESS 0
typedef int thread_t;
static int shim_thread_starts;
static const char *arg_all, *arg_p, *arg_k;
static void nabu_bt_worker(void *arg, int wr) { (void)arg; (void)wr; }
static int
kernel_thread_start_priority(void (*continuation)(void *, int), void *parameter,
    int priority, thread_t *new_thread)
{
	(void)continuation; (void)parameter; (void)priority;
	*new_thread = 1;
	shim_thread_starts++;
	return KERN_SUCCESS;
}
static void thread_deallocate(thread_t thread) { (void)thread; }
static int
PE_parse_boot_argn(const char *key, void *value, int max_len)
{
	if (!strcmp(key, "nabutraceall")) {
		if (!arg_all) return 0;
		*(int *)value = atoi(arg_all);
		return 1;
	}
	if (!strcmp(key, "nabutracep")) {
		if (!arg_p || max_len < 2) return 0;
		strncpy((char *)value, arg_p, (size_t)max_len - 1u);
		((char *)value)[max_len - 1] = 0;
		return 1;
	}
	if (!strcmp(key, "nabutracek")) {
		if (!arg_k) return 0;
		*(int *)value = (int)strtol(arg_k, 0, 0);
		return 1;
	}
	return 0;
}
"""

MAIN = r"""
static void reset(void)
{
	nabu_bt_enabled = 0;
	nabu_bt_started = 0;
	nabu_bt_name_count = 0;
	nabu_bt_kind_mask = 0;
	nabu_bt_filtered = 0;
	nabu_bt_events.offered = 0;
	nabu_bt_id = 0;
	shim_thread_starts = 0;
	arg_all = arg_p = arg_k = 0;
}

static void set_comm(struct proc *p, const char *name)
{
	memset(p, 0, sizeof(*p));
	strncpy(p->p_comm, name, NABU_BT_NAME - 1);
}

static void start_expect(int started, unsigned int names, unsigned int mask)
{
	nabu_boottrace_start();
	assert(nabu_bt_started == (unsigned int)started);
	assert(nabu_bt_enabled == (unsigned int)started);
	assert(nabu_bt_name_count == names);
	assert(nabu_bt_kind_mask == mask);
	assert(shim_thread_starts == started);
}

int main(void)
{
	struct proc p;
	char sixteen[NABU_BT_NAME], seventeen[NABU_BT_NAME + 1];

	/* Filter parsing: exact bounded names, blanks skipped, four entries max. */
	reset();
	set_comm(&p, "lsd");
	nabu_bt_kind_mask = 0x1e;
	nabu_bt_parse_names("");
	assert(nabu_bt_name_count == 0 && nabu_bt_match(&p, NABU_BT_LOOKUP) == 1);
	nabu_bt_parse_names("lsd,launchd");
	assert(nabu_bt_name_count == 2);
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 1);
	set_comm(&p, "launchd");
	assert(nabu_bt_match(&p, NABU_BT_OPEN) == 1);
	set_comm(&p, "SpringBoard");
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 0);
	assert(nabu_bt_match(0, NABU_BT_LOOKUP) == 0);
	set_comm(&p, "lsd1");
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 0);
	set_comm(&p, "LSD");
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 0);

	reset();
	nabu_bt_kind_mask = 0x1e;
	nabu_bt_parse_names(",,lsd,");
	assert(nabu_bt_name_count == 1);
	set_comm(&p, "lsd");
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 1);

	reset();
	nabu_bt_kind_mask = 0x1e;
	memset(sixteen, 'a', sizeof(sixteen) - 1u);
	sixteen[NABU_BT_NAME - 1] = 0;
	memset(seventeen, 'b', sizeof(seventeen) - 1u);
	seventeen[NABU_BT_NAME - 1] = 'b';
	seventeen[NABU_BT_NAME] = 0;
	nabu_bt_parse_names(sixteen);
	assert(nabu_bt_name_count == 1);
	set_comm(&p, sixteen);
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 1);
	nabu_bt_name_count = 0;
	nabu_bt_parse_names(seventeen);
	assert(nabu_bt_name_count == 0);

	reset();
	nabu_bt_kind_mask = 0x1e;
	nabu_bt_parse_names("aaaa,bbbb,cccc,dddd,eeee");
	assert(nabu_bt_name_count == 4);
	set_comm(&p, "eeee");
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 0);

	/* Kind mask: only bits 1..4 are addressable, and an empty mask matches none. */
	reset();
	set_comm(&p, "lsd");
	nabu_bt_kind_mask = 0x1e;
	assert(nabu_bt_match(&p, 0) == 0);
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 1);
	assert(nabu_bt_match(&p, NABU_BT_OPEN) == 1);
	assert(nabu_bt_match(&p, NABU_BT_EXEC) == 1);
	assert(nabu_bt_match(&p, NABU_BT_EXIT) == 1);
	assert(nabu_bt_match(&p, 5) == 0);
	nabu_bt_kind_mask = 0x0c;
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 0);
	assert(nabu_bt_match(&p, NABU_BT_OPEN) == 1);
	assert(nabu_bt_match(&p, NABU_BT_EXEC) == 1);
	assert(nabu_bt_match(&p, NABU_BT_EXIT) == 0);
	nabu_bt_kind_mask = 0;
	assert(nabu_bt_match(&p, NABU_BT_LOOKUP) == 0);

	/* Start gate: opt-in only, validated arguments, single worker. */
	reset();
	start_expect(0, 0, 0);

	reset();
	arg_p = "lsd,launchd";
	start_expect(1, 2, 0x1e);
	nabu_boottrace_start();
	assert(shim_thread_starts == 1);

	reset();
	arg_all = "1";
	start_expect(1, 0, 0x1e);

	reset();
	arg_all = "2";
	start_expect(0, 0, 0);

	reset();
	arg_p = ",";
	start_expect(0, 0, 0);

	reset();
	arg_p = "lsd";
	arg_k = "12";
	start_expect(1, 1, 0x0c);

	reset();
	arg_p = "lsd";
	arg_k = "0";
	start_expect(0, 0, 0);

	reset();
	arg_p = "lsd";
	arg_k = "31";
	start_expect(1, 1, 0x1e);

	reset();
	arg_p = "a,b,c,d,e";
	start_expect(1, 4, 0x1e);
	puts("boottrace filter: exact bounded names, kind mask, opt-in start gate and single worker passed");
	return 0;
}
"""


def extract_function(source, signature):
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def build_region(source):
    begin = source.index("static struct nabu_bt_queue nabu_bt_events;")
    match = extract_function(source, "static int\nnabu_bt_match(proc_t p, unsigned int kind)")
    end = source.index(match) + len(match)
    return begin, source[begin:end]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    args = parser.parse_args()
    source = (args.xnu_source / "bsd/dev/nabu_boottrace.c").read_text(encoding="utf-8")
    _, region = build_region(source)
    start = extract_function(source, "void\nnabu_boottrace_start(void)")
    # The narrowed build must gate producers before they allocate an event, and
    # must keep the opt-in arguments that the device profile relies on.
    checks = {
        "if (!nabu_bt_match(current_proc(), kind))": 1,
        "__atomic_fetch_add(&nabu_bt_filtered, 1ULL, __ATOMIC_RELAXED);": 1,
        "nabu_bt_push(&nabu_bt_events, &event)": 3,
        "nabutracep": 1,
        "nabutracek": 1,
        "flt=%llu": 1,
    }
    for text, expected in checks.items():
        if source.count(text) != expected:
            raise SystemExit("unexpected source count for: " + text)
    if "nabu_bt_parse_names(names)" not in start:
        raise SystemExit("extracted start gate is missing the name parser")
    with tempfile.TemporaryDirectory(prefix="boottrace-filter-") as td:
        root = Path(td)
        include = root / "sys"
        include.mkdir()
        (include / "nabu_boottrace.h").write_bytes(
            (args.xnu_source / "bsd/sys/nabu_boottrace.h").read_bytes())
        (include / "nabu_boottrace_queue.h").write_bytes(
            (args.xnu_source / "bsd/sys/nabu_boottrace_queue.h").read_bytes())
        harness = root / "test.c"
        harness.write_text(PRELUDE + region + start + MAIN, encoding="utf-8", newline="\n")
        binary = root / "test.exe"
        subprocess.run([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-I", str(root), str(harness), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True, timeout=30)
    print("source_sha256=" + hashlib.sha256(
        (args.xnu_source / "bsd/dev/nabu_boottrace.c").read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
