#!/usr/bin/env python3
"""Check actual append-only capture and loader producers with host atomics.

Uses extracted production functions, the production core header and ASan/UBSan.
Only ARM DAIF access is mocked. No kernel/device execution or disk persistence
claim follows from these checks.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def function(text, name):
    matches = list(re.finditer(
        r'\n(?:static void|const char \*|uint32_t|uint64_t|int|void)\n' +
        re.escape(name) + r'\([^;{]*\)\n\{', text))
    if len(matches) != 1:
        raise ValueError('Expected one function: ' + name)
    start = matches[0].start() + 1
    end = matches[0].end()
    depth = 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end] + '\n'


def run(args):
    result = subprocess.run(args, capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{args!r}\n{result.stdout}\n{result.stderr}')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--tree', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.tree:
        tree = args.tree
    else:
        tree = Path(tempfile.mkdtemp(prefix='source-', dir=args.output.resolve()))
        loader = tree / 'osfmk/arm64/loader_return.c'
        loader.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'src/hakios-8796/xnu/files/osfmk/arm64/loader_return.c', loader)
        msgbuf = tree / 'bsd/kern/subr_log.c'
        msgbuf.parent.mkdir(parents=True)
        shutil.copy2(ROOT / 'src/xnu-8796/bsd/kern/subr_log.c', msgbuf)
        run(['git', 'init', '-q', str(tree)])
        for patch in ('loader-return-diagnostics.patch', 'nabu-log-capture.patch'):
            path = ROOT / 'patches/8796' / patch
            run(['git', '-C', str(tree), 'apply', '--check', str(path)])
            run(['git', '-C', str(tree), 'apply', str(path)])
    loader_path = tree / 'osfmk/arm64/loader_return.c'
    msgbuf_path = tree / 'bsd/kern/subr_log.c'
    loader = loader_path.read_text()
    msgbuf = msgbuf_path.read_text()
    core = ROOT / 'patches/nabu-storage/NabuLogCapture.h'
    copied = args.output / core.name
    shutil.copy2(core, copied)
    timer = function(loader, 'loader_return_timer')
    assert timer.count('nabu_log_finish();') == 1
    assert timer.index('if (!as_panic)') < timer.index('nabu_log_finish();')
    assert timer.index('nabu_log_finish();') < timer.index('hakios_var_save_on_return();')
    assert timer.index('nabu_log_finish();') < timer.index('cpu_xcall(')
    assert 'nabu_log_finish' not in function(loader, 'loader_return_test')
    assert 'nabu_log_finish' not in function(loader, 'loader_return')
    seal = function(loader, 'nabu_log_capture_seal')
    assert all(token not in seal for token in ('printf(', 'loader_log_line(', 'nabu_log_finish(', 'IOLock'))
    assert 'return locked ? 0 : EBUSY;' in seal

    prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <pthread.h>

static uint32_t loader_log_lock;
static bool force_lock_failure;
static _Thread_local uint64_t fake_daif;
#define O_relaxed __ATOMIC_RELAXED
#define O_acquire __ATOMIC_ACQUIRE
#define O_release __ATOMIC_RELEASE
#define os_atomic_load(p,o) __atomic_load_n((p),O_##o)
#define os_atomic_store(p,v,o) __atomic_store_n((p),(v),O_##o)
#define os_atomic_or(p,v,o) __atomic_or_fetch((p),(v),O_##o)
#define os_atomic_inc(p,o) __atomic_add_fetch((p),1,O_##o)
#define os_atomic_cmpxchg(p,old,value,o) __extension__ ({ \
  __typeof__(*(p)) expected = (old); \
  bool fail = (void *)(p) == (void *)&loader_log_lock && force_lock_failure; \
  !fail && __atomic_compare_exchange_n((p),&expected,(value),false,O_##o,__ATOMIC_RELAXED); \
})
#define __builtin_arm_rsr64(reg) fake_daif
#define __builtin_arm_wsr(reg,value) (fake_daif |= (value))
#define __builtin_arm_wsr64(reg,value) (fake_daif = (value))
#define DAIFSC_IRQF 2
#define DAIFSC_FIQF 1
#include "NabuLogCapture.h"
static struct NabuLogCaptureState nabu_capture;
#define LOADER_LOG_SIZE (1536 * 1024)
#define LOADER_LOG_HEAD (256 * 1024)
#define LOADER_LOG_RING (1024 * 1024)
static char loader_log[LOADER_LOG_SIZE];
static uint32_t loader_log_len, loader_log_ring_at;
static bool loader_log_linear, loader_log_wrapped;
static void loader_log_put_locked(char);
struct msgbuf { int msg_magic, msg_size, msg_bufx, msg_bufr; char *msg_bufc; };
static char message_bytes[8];
static struct msgbuf message_buffer = {0,8,0,0,message_bytes};
static struct msgbuf *msgbufp = &message_buffer;
static bool bsd_lock_available=true;
static unsigned oslog_msgbuf_dropped_charcount;
static bool oslog_is_safe(void) { return true; }
static bool bsd_log_lock(bool safe) { (void)safe; return bsd_lock_available; }
static void bsd_log_unlock(void) { }
static void logwakeup(struct msgbuf *p) { assert(p==msgbufp); }
'''
    names = ('nabu_log_capture_data', 'nabu_log_capture_length', 'nabu_log_capture_lost',
             'nabu_log_capture_seal', 'nabu_log_capture_msgbuf',
             'loader_log_putc', 'loader_log_line', 'loader_log_put_locked')
    production = '\n'.join(function(loader, name) for name in names)
    production += function(msgbuf, 'log_putc_locked').replace('#if defined(__arm64__)', '#if 1')
    production += function(msgbuf, 'log_putc').replace('#if defined(__arm64__)', '#if 1')
    tests = r'''
static void reset(void) {
  memset(&nabu_capture,0,sizeof(nabu_capture));
  memset(loader_log,0,sizeof(loader_log));
  loader_log_lock=loader_log_len=loader_log_ring_at=0;
  loader_log_linear=loader_log_wrapped=force_lock_failure=false;
  fake_daif=0x240;
  bsd_lock_available=true;oslog_msgbuf_dropped_charcount=0;
  memset(message_bytes,0,sizeof(message_bytes));message_buffer.msg_bufx=0;
}
static char pattern(uint32_t i) { return (char)((i*29U+7U)%251U); }
static void producer_tests(void) {
  reset();
  loader_log_line("alpha\r\n");
  nabu_log_capture_msgbuf('K');loader_log_putc('\r');loader_log_putc('!');
  assert(nabu_log_capture_length()==8);
  assert(!memcmp(nabu_log_capture_data(),"alpha\nK!",8));
  assert(loader_log_len==7 && !memcmp(loader_log,"alpha\n!",7));
  assert(fake_daif==0x240 && loader_log_lock==0);
  force_lock_failure=true;
  loader_log_putc('X');loader_log_line("Y\r\n");nabu_log_capture_msgbuf('Z');
  assert(nabu_log_capture_length()==8 && nabu_log_capture_lost()==4);
  assert(!memcmp(nabu_log_capture_data(),"alpha\nK!",8));
  assert(nabu_log_capture_seal()==EBUSY);
  assert(!(nabu_capture.loss_and_seal&NABU_LOG_CAPTURE_SEALED));
  assert(fake_daif==0x240);
  force_lock_failure=false;loader_log_putc('x');
  assert(nabu_log_capture_length()==9 && nabu_log_capture_data()[8]=='x');
  assert(nabu_log_capture_seal()==0 && nabu_log_capture_seal()==0);
  loader_log_putc('q');loader_log_line("after\n");nabu_log_capture_msgbuf('r');
  force_lock_failure=true;nabu_log_capture_msgbuf('s');
  assert(nabu_log_capture_length()==9 && nabu_log_capture_lost()==4);
  assert(fake_daif==0x240);
}
static void message_buffer_tests(void) {
  reset();char other_bytes[8]={0};struct msgbuf other={0,8,0,0,other_bytes};
  for(unsigned i=0;i<32;i++) log_putc_locked(msgbufp,(char)('a'+i%26));
  assert(nabu_log_capture_length()==32 && loader_log_len==0);
  for(unsigned i=0;i<32;i++) assert(nabu_log_capture_data()[i]==(char)('a'+i%26));
  log_putc_locked(&other,'X');assert(nabu_log_capture_length()==32);
  log_putc_locked(msgbufp,'\r');assert(nabu_log_capture_length()==32);
  log_putc('N');assert(nabu_log_capture_length()==33 && nabu_log_capture_data()[32]=='N');
  int saved=msgbufp->msg_bufx;bsd_lock_available=false;
  log_putc('F');assert(msgbufp->msg_bufx==saved && oslog_msgbuf_dropped_charcount==1);
  assert(nabu_log_capture_length()==34 && nabu_log_capture_data()[33]=='F');
  assert(nabu_log_capture_seal()==0);
  log_putc_locked(msgbufp,'Z');assert(nabu_log_capture_length()==34);
}
static void capacity_tests(void) {
  reset();
  assert(NABU_LOG_CAPTURE_BYTES==56U*1024U*1024U);
  for(uint32_t i=0;i<NABU_LOG_CAPTURE_BYTES;i++) nabuLogCapturePutLocked(&nabu_capture,pattern(i));
  assert(nabu_log_capture_length()==NABU_LOG_CAPTURE_BYTES && nabu_log_capture_lost()==0);
  /* Exact production capacity is exercised, including history far beyond the
   * old 1 MiB screen ring. A rejected suffix cannot change any prefix byte. */
  for(unsigned i=0;i<47;i++) nabuLogCapturePutLocked(&nabu_capture,'!');
  assert(nabu_log_capture_lost()==47 && nabu_log_capture_length()==NABU_LOG_CAPTURE_BYTES);
  for(uint32_t i=0;i<NABU_LOG_CAPTURE_BYTES;i++) assert(nabu_log_capture_data()[i]==pattern(i));
  assert(nabu_log_capture_seal()==0);
  nabuLogCaptureLost(&nabu_capture);assert(nabu_log_capture_lost()==47);
}
static bool writer_done;
static void *prefix_writer(void *unused) {
  (void)unused;
  for(uint32_t i=0;i<4U*1024U*1024U;i++) nabuLogCapturePutLocked(&nabu_capture,pattern(i));
  __atomic_store_n(&writer_done,true,__ATOMIC_RELEASE);return NULL;
}
static void publication_test(void) {
  reset();writer_done=false;pthread_t t;assert(!pthread_create(&t,NULL,prefix_writer,NULL));
  uint32_t checked=0;
  do {
    uint32_t published=nabu_log_capture_length();assert(published>=checked);
    for(;checked<published;checked++) assert(nabu_log_capture_data()[checked]==pattern(checked));
  } while(!__atomic_load_n(&writer_done,__ATOMIC_ACQUIRE));
  assert(!pthread_join(t,NULL));
  for(;checked<nabu_log_capture_length();checked++) assert(nabu_log_capture_data()[checked]==pattern(checked));
  assert(checked==4U*1024U*1024U && nabu_log_capture_lost()==0);
}
static void *loss_writer(void *unused) {
  (void)unused;
  for(unsigned i=0;i<25000;i++) nabuLogCaptureLost(&nabu_capture);
  return NULL;
}
static void loss_atomic_test(void) {
  reset();pthread_t t[4];
  for(unsigned i=0;i<4;i++) assert(!pthread_create(t+i,NULL,loss_writer,NULL));
  for(unsigned i=0;i<4;i++) assert(!pthread_join(t[i],NULL));
  assert(nabu_log_capture_lost()==100000 && nabu_log_capture_length()==0);
  assert(nabu_log_capture_seal()==0);
  for(unsigned i=0;i<4;i++) assert(!pthread_create(t+i,NULL,loss_writer,NULL));
  for(unsigned i=0;i<4;i++) assert(!pthread_join(t[i],NULL));
  assert(nabu_log_capture_lost()==100000 && nabu_log_capture_length()==0);
  reset();nabu_capture.loss_and_seal=NABU_LOG_CAPTURE_LOST_MASK-1;
  nabuLogCaptureLost(&nabu_capture);nabuLogCaptureLost(&nabu_capture);
  assert(nabu_log_capture_lost()==NABU_LOG_CAPTURE_LOST_MASK);
  assert(nabu_log_capture_seal()==0);
  assert(nabu_log_capture_lost()==NABU_LOG_CAPTURE_LOST_MASK);
}
int main(void) {
  producer_tests();message_buffer_tests();capacity_tests();publication_test();loss_atomic_test();
  puts("5 production capture suites passed: producers, msgbuf, 56 MiB boundary, immutable-prefix publication, atomic loss/seal");
}
'''
    c = args.output / 'capture.c'
    exe = args.output / 'capture'
    c.write_text(prelude + production + tests, encoding='utf-8')
    compiler = host_command(['clang', '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-pthread', host_path(c), '-o', host_path(exe)])
    run(compiler)
    result = run(host_command([host_path(exe)])).strip()
    report = {
        'passed': True, 'host_result': result, 'capture_bytes': 56 * 1024 * 1024,
        'source_files': [{'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in (loader_path, msgbuf_path, core, ROOT / 'patches/8796/nabu-log-capture.patch')],
        'normal_return_finish_before_shutdown': True,
        'seal_return_contract': '0 success / EBUSY leaves stream unsealed',
        'scope': 'Extracted production producer functions and core with ASan/UBSan and host pthread atomics; '
                 'DAIF effects mocked. Native kernel layout, actual ARM concurrency, disk and device behavior not verified here.',
        'coverage': 'kprintf + explicit loader lines + user console + live msgbuf characters; existing mirrored source '
                    'messages retained; CR normalization matches loader text; post-seal output is outside saved stream.'}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
