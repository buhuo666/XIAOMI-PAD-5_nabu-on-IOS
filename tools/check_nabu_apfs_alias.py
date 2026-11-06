#!/usr/bin/env python3
"""Check cached-vnode reparenting from the actual patched APFS sysctl body."""
import argparse
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path


def block(source, anchor):
    start = source.index(anchor)
    at = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[at] == '{') - (source[at] == '}')
        at += 1
    return source[start:at]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    text = (args.tree/'bsd/miscfs/apfs/apfs_vfsops.c').read_text()
    text = text[text.index('apfs_sysctl_synthetic SYSCTL_HANDLER_ARGS'):]
    publish = text[text.index('am->am_nsynth++;'):text.index('error = 0;', text.index('am->am_nsynth++;'))]
    reparent = block(publish, 'if (tvp != NULLVP)')
    identity = block(text, 'if (error == 0 && tvp != NULLVP)')
    assert text.index(identity) > text.index('apfs_unlock(am);')
    assert text.index(identity) < text.index('vnode_put(dvp);', text.index('apfs_unlock(am);'))
    source = r'''
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#define NULLVP NULL
#define APFS_VP(vp) (vp)
#define VNODE_UPDATE_PARENT 1
#define VNODE_UPDATE_NAME 2
#define VNODE_UPDATE_CACHE 4
struct node { unsigned long long an_id, an_parent; struct { unsigned long long parent_id; } an_ino; };
static unsigned updates;
static struct node *named_parent;
static const char *cached_name;
static void vnode_update_identity(struct node *v, struct node *p, const char *name, int len, unsigned hash, int flags) {
    assert(v && p && len == (int)strlen(name) && hash == 0);
    assert(flags == (VNODE_UPDATE_PARENT | VNODE_UPDATE_NAME | VNODE_UPDATE_CACHE));
    named_parent = p; cached_name = name; updates++;
}
static void publish_alias(struct node *tvp, struct node *dn) {
''' + reparent + r'''
}
static void finish_alias(int error, struct node *tvp, struct node *dvp, const char *name) {
    size_t len = strlen(name);
''' + identity + r'''
}
int main(void) {
    struct node old = {.an_id=17}, applications = {.an_id=23};
    struct node cached = {.an_id=101, .an_parent=17, .an_ino={.parent_id=17}};
    named_parent = &old; cached_name = "MobileNotes.app";
    /* The existing-vnode path has already been materialized under staged apps. */
    assert(cached.an_parent != applications.an_id && named_parent == &old);
    publish_alias(&cached, &applications);
    finish_alias(0, &cached, &applications, "MobileNotes.app");
    assert(cached.an_parent == 23 && cached.an_ino.parent_id == 23);
    assert(named_parent == &applications && !strcmp(cached_name, "MobileNotes.app") && updates == 1);
    finish_alias(17, &cached, &old, "failed");
    publish_alias(NULL, &applications); finish_alias(0, NULL, &applications, "empty");
    assert(updates == 1 && named_parent == &applications);
    puts("PASS: cached alias parent/attributes/identity agree; failed and empty aliases do not rename vnodes");
}
'''
    path = args.output/'alias.c'
    binary = args.output/'alias-test'
    path.write_text(source, newline='\n')
    subprocess.run(host_command(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror',
                                '-fsanitize=address,undefined', host_path(path), '-o', host_path(binary)]), check=True)
    result = subprocess.check_output(host_command([host_path(binary)]), text=True)
    (args.output/'result.json').write_text(json.dumps({'passed': True, 'result': result,
        'scope': 'Actual reparent blocks with mock vnode identity; device F_GETPATH/registration still required'}, indent=2)+'\n')
    print(result.strip())


if __name__ == '__main__':
    main()
