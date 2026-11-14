#!/usr/bin/env python3
"""Exercise the real jailbreak config update functions against sysctl I/O semantics.

Does not re-test the kernel injection parser or access any device. The stub uses
Darwin sysctl_io_string's reject-before-copy capacity behavior and NUL handling.
"""
import argparse
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    original = (ROOT / 'userland/nabu/src/jailbreak_paths.c').read_text()
    functions = original[original.index('int nabu_jailbreak_restore_tweak_config('):]
    # Match the already-qualified init's line representation only; parsing
    # which processes get which library is deliberately outside this check.
    config = args.config.read_text().rstrip('\n ').replace('\n', ';')
    (out / 'initial-config.txt').write_text(config)
    harness = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include "jailbreak_paths.h"
static char value[4096];
static size_t limit;
static int attempts, writes, reject_write;
static int sysctlbyname(const char *name,void *old,size_t *oldsize,const void *next,size_t nextsize) {
    assert(!strcmp(name,"kern.exec_inject"));
    if(old) {
        size_t wanted=strlen(value)+1;
        if(*oldsize<wanted) { *oldsize=wanted; errno=ENOMEM; return -1; }
        memcpy(old,value,wanted); *oldsize=wanted;
    }
    if(next) {
        attempts++;
        if(reject_write) { errno=reject_write; return -1; }
        if(nextsize>=limit) { errno=EINVAL; return -1; }
        memcpy(value,next,nextsize); value[nextsize]=0; writes++;
    }
    return 0;
}
''' + functions + r'''
static void reset(const char *initial,size_t capacity) {
    strcpy(value,initial); limit=capacity; attempts=writes=reject_write=0;
}
int main(int argc,char **argv) {
    assert(argc==2);
    char initial[4096]={0}, previous[4096]={0}, active[4096], second[4096];
    FILE *f=fopen(argv[1],"rb"); assert(f);
    size_t size=fread(initial,1,sizeof(initial)-1,f); assert(!ferror(f)); fclose(f);
    assert(size>0 && size<511);
    int n=snprintf(active,sizeof(active),"%s;%s",initial,NABU_JB_TWEAK_RULE);
    assert(n>0 && (size_t)n<sizeof(active));

    /* Reproduce the real baseline overflow on the old 512-byte sysctl. */
    reset(initial,512);
    int status=nabu_jailbreak_enable_tweaks(previous,sizeof(previous));
    if(strlen(active)+1>=512) {
        assert(status<0 && errno==EINVAL && attempts==1 && writes==0);
        assert(!strcmp(previous,initial) && !strcmp(value,initial));
    } else {
        /* Exercise the same old-limit failure when this chosen baseline is
         * shorter than the current device's full config. */
        assert(status==0);
        char long_config[511]; memset(long_config,'a',sizeof(long_config)-1); long_config[510]=0;
        reset(long_config,512);
        assert(nabu_jailbreak_enable_tweaks(previous,sizeof(previous))<0 && errno==EINVAL);
        assert(!strcmp(previous,long_config) && !strcmp(value,long_config) && writes==0);
    }

    reset(initial,4096);
    assert(nabu_jailbreak_enable_tweaks(previous,sizeof(previous))==0);
    assert(!strcmp(previous,initial) && !strcmp(value,active) && writes==1);
    assert(nabu_jailbreak_enable_tweaks(second,sizeof(second))==0);
    assert(!strcmp(second,active) && !strcmp(value,active) && attempts==1);
    assert(nabu_jailbreak_restore_tweak_config(previous)==0);
    assert(!strcmp(value,initial) && writes==2);

    reset(initial,4096); reject_write=EPERM;
    assert(nabu_jailbreak_enable_tweaks(previous,sizeof(previous))<0 && errno==EPERM);
    assert(!strcmp(value,initial) && !strcmp(previous,initial) && writes==0);
    reset(active,4096); reject_write=EPERM;
    assert(nabu_jailbreak_restore_tweak_config(initial)<0 && errno==EPERM);
    assert(!strcmp(value,active) && writes==0);

    reset(initial,4096);
    assert(nabu_jailbreak_enable_tweaks(previous,1)<0 && errno==ENOMEM && attempts==0);
    assert(!strcmp(value,initial));
    reset("",4096);
    assert(nabu_jailbreak_enable_tweaks(previous,sizeof(previous))==0);
    assert(!*previous && !strcmp(value,NABU_JB_TWEAK_RULE));
    assert(nabu_jailbreak_restore_tweak_config(previous)==0 && !*value);

    reset(NABU_JB_TWEAK_RULE ";/old.dylib oldproc",4096);
    assert(nabu_jailbreak_enable_tweaks(previous,sizeof(previous))==0 && attempts==0);
    reset("/old.dylib oldproc;" NABU_JB_TWEAK_RULE ";/other.dylib other",4096);
    assert(nabu_jailbreak_enable_tweaks(previous,sizeof(previous))==0 && attempts==0);
    puts("PASS: old-limit rejection, baseline preservation, append, idempotence, restore, denied writes, read failure, empty state, existing rule positions");
}
'''
    source = out / 'jailbreak-config.c'
    source.write_text(harness)
    binary = out / 'jailbreak-config'
    commands = [('compile', ['clang-18', '-std=gnu11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                             '-fsanitize=address,undefined', '-I' + host_path(ROOT / 'userland/nabu/src'),
                             host_path(source), '-o', host_path(binary)]),
                ('run', [host_path(binary), host_path(out / 'initial-config.txt')])]
    for label, command in commands:
        run = subprocess.run(host_command(command), capture_output=True)
        (out / (label + '.log')).write_bytes(run.stdout + run.stderr)
        if run.returncode:
            raise RuntimeError((run.stdout + run.stderr).decode(errors='replace'))
    report = dict(passed=True, device_executed=False, actual_config_functions=True,
                  sysctl_string_io_stub=True, initial_config_bytes=len(config.encode()),
                  updated_config_bytes=len((config + ';' + '/var/jb/usr/lib/TweakLoader.dylib *').encode()),
                  kernel_parser_retested=False, baseline_preserved=True, old_512_rejection_preserved_state=True,
                  new_4096_append_and_idempotence=True, rollback_exact=True,
                  denied_write_and_rollback_reported=True, read_failure_has_no_write=True)
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
