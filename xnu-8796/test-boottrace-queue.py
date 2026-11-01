#!/usr/bin/env python3
"""Host tests for the bounded, try-lock-only boottrace queue."""
import hashlib
import argparse
import re
import subprocess
import tempfile
from pathlib import Path

SOURCE = r"""
#include <assert.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "queue.h"

static struct nabu_bt_queue q;
static void *producer(void *arg) {
    uintptr_t base = (uintptr_t)arg;
    for (unsigned i = 0; i < 2000; ++i) {
        struct nabu_bt_event e = {0};
        e.id = base + i;
        e.path_bytes = NABU_BT_PATH;
        e.truncated = 1;
        (void)nabu_bt_push(&q, &e);
    }
    return 0;
}
int main(void) {
    struct nabu_bt_event e = {0}, out = {0};
    e.id = 7;
    assert(nabu_bt_push(&q, &e) == 1);
    assert(nabu_bt_pop(&q, &out) == 1 && out.id == 7);
    q.lock = 1;
    assert(nabu_bt_push(&q, &e) == 0 && q.busy_dropped == 1);
    q.lock = 0;
    q.count = NABU_BT_SLOTS;
    assert(nabu_bt_push(&q, &e) == 0 && q.full_dropped == 1);
    q.count = 0; q.read_at = q.write_at = 0;
    uint64_t accepted_before = q.accepted;
    pthread_t threads[8];
    for (unsigned i = 0; i < 8; ++i)
        assert(!pthread_create(&threads[i], 0, producer, (void *)(uintptr_t)(i * 10000)));
    for (unsigned i = 0; i < 8; ++i) assert(!pthread_join(threads[i], 0));
    assert(q.offered == 16000 + 3);
    assert(q.accepted + q.busy_dropped + q.full_dropped == q.offered);
    uint64_t checked = 0;
    while (nabu_bt_pop(&q, &out)) {
        assert(out.path_bytes == NABU_BT_PATH && out.truncated == 1);
        ++checked;
    }
    assert(checked == q.accepted - accepted_before);
    puts("try-lock, bounded full queue, concurrent producers and truncation metadata passed");
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


def build_path_test(source):
    path_function = extract_function(
        source,
        "void\nnabu_boottrace_path(struct nabu_bt_token token, unsigned int kind, const char *kernel_path)",
    )
    path_test = r"""
#define ARM64_BOARD_CONFIG_NABU 1
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "sys/nabu_boottrace.h"
#include "sys/nabu_boottrace_queue.h"
static struct nabu_bt_queue nabu_bt_events;
static void nabu_bt_identity(struct nabu_bt_event *e) { e->pid=1; e->ns=9; }
""" + path_function + r"""
int main(void) {
    char path[NABU_BT_PATH + 1];
    struct nabu_bt_event event;
    struct nabu_bt_token token = { 41, 1 };
    memset(path, 'x', sizeof(path));
    path[319] = 0;
    nabu_boottrace_path(token, NABU_BT_LOOKUP, path);
    assert(nabu_bt_pop(&nabu_bt_events, &event));
    assert(event.id == 41 && event.kind == NABU_BT_LOOKUP);
    assert(event.edge == 2 && event.path_bytes == 319 && !event.truncated);
    path[319] = 'x'; path[320] = 0;
    nabu_boottrace_path(token, NABU_BT_LOOKUP, path);
    assert(nabu_bt_pop(&nabu_bt_events, &event));
    assert(event.path_bytes == NABU_BT_PATH && event.truncated);
    nabu_boottrace_path((struct nabu_bt_token){0,0}, NABU_BT_LOOKUP, path);
    nabu_boottrace_path(token, NABU_BT_LOOKUP, 0);
    assert(!nabu_bt_pop(&nabu_bt_events, &event));
    puts("actual path recorder: event identity, type, exact-fit, truncation and disabled-token cases passed");
    return 0;
}
"""
    return path_test


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", type=Path, required=True)
    args = parser.parse_args()
    header = args.xnu_source / "bsd/sys/nabu_boottrace_queue.h"
    path_test = build_path_test(
        (args.xnu_source / "bsd/dev/nabu_boottrace.c").read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="nabu-boottrace-") as td:
        root = Path(td)
        (root / "queue.h").write_bytes(header.read_bytes())
        queue_test = root / "queue-test.c"
        queue_test.write_text(SOURCE, encoding="utf-8", newline="\n")
        queue_binary = root / "queue-test.exe"
        subprocess.run(["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-pthread", str(queue_test), "-o", str(queue_binary)], check=True)
        subprocess.run([str(queue_binary)], check=True)
        include = root / "sys"
        include.mkdir()
        (include / "nabu_boottrace.h").write_bytes(
            (args.xnu_source / "bsd/sys/nabu_boottrace.h").read_bytes())
        (include / "nabu_boottrace_queue.h").write_bytes(header.read_bytes())
        path_source = root / "path-test.c"
        path_source.write_text(path_test, encoding="utf-8", newline="\n")
        path_binary = root / "path-test.exe"
        subprocess.run(["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-I", str(root), str(path_source), "-o", str(path_binary)], check=True)
        subprocess.run([str(path_binary)], check=True)
        print("source_sha256=" + hashlib.sha256(header.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
