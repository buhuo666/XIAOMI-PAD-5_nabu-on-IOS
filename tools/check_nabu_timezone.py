#!/usr/bin/env python3
"""Exercise the PID1 timezone migration with real symlinks and a persistent marker."""
import argparse
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    code = r'''
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
static char folder[] = "/tmp/nabu-timezone-XXXXXX";
static int refuse_link;
static const char *map(const char *path, char out[256]) {
    const char *prefix = "/private/var/db/timezone";
    assert(!strncmp(path, prefix, strlen(prefix)));
    snprintf(out, 256, "%s%s", folder, path + strlen(prefix));
    return out;
}
static int routed_stat(const char *p, struct stat *s) { char b[256]; return stat(map(p,b),s); }
static ssize_t routed_readlink(const char *p, char *s, size_t n) { char b[256]; return readlink(map(p,b),s,n); }
static int routed_symlink(const char *s, const char *p) {
    if (refuse_link) {errno = EROFS; return -1;}
    char b[256]; return symlink(s,map(p,b));
}
static int routed_unlink(const char *p) { char b[256]; return unlink(map(p,b)); }
static int routed_rename(const char *a, const char *b) { char x[256],y[256]; return rename(map(a,x),map(b,y)); }
static int routed_open(const char *p, int flags, int mode) { char b[256]; return open(map(p,b),flags,mode); }
static int nabu_data_fullfsync(int fd) { return fsync(fd); }
#define stat(p,s) routed_stat(p,s)
#define readlink routed_readlink
#define symlink routed_symlink
#define unlink routed_unlink
#define rename routed_rename
#define open routed_open
''' + (ROOT/'patches/nabu-userland/NabuTimeZone.inc').read_text() + r'''
static void expect(const char *expected) {
    char out[128]; ssize_t n=readlink("/private/var/db/timezone/localtime",out,sizeof(out)-1);
    assert(n>0);out[n]=0;assert(!strcmp(out,expected));
}
int main(void) {
    const char *local="/private/var/db/timezone/localtime";
    const char *marker="/private/var/db/timezone/nabu-default-v1";
    const char *pacific="/var/db/timezone/zoneinfo/US/Pacific";
    const char *shanghai="/var/db/timezone/zoneinfo/Asia/Shanghai";
    assert(mkdtemp(folder));
    assert(symlink(pacific,local)==0);
    refuse_link=1;assert(!nabu_fix_timezone());expect(pacific);
    struct stat st;assert(stat(marker,&st)!=0 && errno==ENOENT);
    refuse_link=0;assert(nabu_fix_timezone());expect(shanghai);
    assert(stat(marker,&st)==0 && st.st_size>0);
    // The user can choose Pacific later: the second boot must keep it.
    assert(unlink(local)==0 && symlink(pacific,local)==0);
    assert(nabu_fix_timezone());expect(pacific);
    assert(unlink(marker)==0 && unlink(local)==0);
    assert(symlink("/var/db/timezone/zoneinfo/Europe/London",local)==0);
    assert(nabu_fix_timezone());expect("/var/db/timezone/zoneinfo/Europe/London");
    assert(unlink(marker)==0 && unlink(local)==0);
    assert(rmdir(folder)==0);
    puts("PASS: Pacific default migration, failed update preservation, restart marker and later user timezone choices");
}
'''
    source = args.output/'TimeZone.c'
    binary = args.output/'TimeZone'
    source.write_text(code)
    subprocess.run(host_command(['clang-18', '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', host_path(source), '-o', host_path(binary)]), check=True)
    result = subprocess.check_output(host_command([host_path(binary)]), text=True)
    (args.output/'result.txt').write_text(result)
    print(result)


if __name__ == '__main__':
    main()
