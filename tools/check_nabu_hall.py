#!/usr/bin/env python3
"""Exercise the production Hall debounce and HID dispatch code on the host."""
import argparse
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def function(text, name):
    start = text.index('\n'+name+'(')+1
    opening = text.index('{', start)
    depth = 1
    end = opening+1
    while depth:
        if text[end] == '{': depth += 1
        if text[end] == '}': depth -= 1
        end += 1
    return text[start:end]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    source = (ROOT/'userland/nabu/src/input_bridge.c').read_text()
    fixture = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define FIELD_IS_BUILT_IN 4
typedef void *id;
typedef void *SEL;
typedef void *IOHIDServiceClientRef;
struct Event { unsigned page, usage, builtin; bool closed; };
typedef struct Event *IOHIDEventRef;
static struct Event event;
static unsigned tick, attempts, accepted, released;
static bool observed[8];
static jmp_buf stop;
static bool read_hall(bool *closed) {
    static const int states[] = {-1,0,0,1,1,1,0,0};
    assert(tick < sizeof(states)/sizeof(states[0]));
    *closed = states[tick] == 1; return states[tick] >= 0;
}
static unsigned long long mach_absolute_time(void) { return 100+tick; }
static void say(const char *format, ...) { (void)format; }
static int pthread_setname_np(const char *name) { assert(!strcmp(name,"nabu hall")); return 0; }
static int usleep(unsigned usec) { assert(usec==32000); if (++tick==8) longjmp(stop,1); return 0; }
static IOHIDEventRef IOHIDEventCreateKeyboardEvent(void *allocator, unsigned long long time,
    unsigned page, unsigned usage, bool closed, unsigned options) {
    assert(!allocator && !options && time==100+tick);
    event=(struct Event){page,usage,0,closed}; return &event;
}
static void IOHIDEventSetIntegerValue(IOHIDEventRef e, unsigned field, unsigned value) {
    assert(e==&event && field==4 && value==1); e->builtin=value;
}
static bool IOHIDVirtualServiceClientDispatchEvent(IOHIDServiceClientRef s, IOHIDEventRef e) {
    assert(s==(void *)1 && e->page==0xff09 && e->usage==1 && e->builtin==1);
    ++attempts;
    if (tick==3) return false; /* actual transition must retry, not disappear */
    observed[accepted++]=e->closed; return true;
}
static void CFRelease(IOHIDEventRef e) { assert(e==&event); ++released; }
static id original_init(id self, SEL command, uint64_t supported, uint64_t disengaged, bool attached, bool unknown) {
    assert(self==(void *)2 && command==(void *)3);
    assert(supported==1 && disengaged==0 && !attached && !unknown);
    return self;
}
static id (*hall_original_init)(id,SEL,uint64_t,uint64_t,bool,bool)=original_init;
'''
    fixture += '\nstatic IOHIDEventRef\n'+function(source,'hall_event')+'\n'
    fixture += '\nstatic void *\n'+function(source,'hall_thread')+'\n'
    fixture += '\nstatic id\n'+function(source,'hall_init')+'\n'
    fixture += r'''
int main(void) {
    struct NabuHallState s={0};
    assert(!nabu_hall_sample(&s,1)); assert(nabu_hall_sample(&s,1) && !s.closed);
    for (unsigned i=0;i<1000;i++) assert(!nabu_hall_sample(&s,1));
    /* One-sample magnetic chatter must not close the display. */
    assert(!nabu_hall_sample(&s,0)); assert(!nabu_hall_sample(&s,1));
    assert(!nabu_hall_sample(&s,1));
    assert(!nabu_hall_sample(&s,0)); assert(nabu_hall_sample(&s,0) && s.closed);
    assert(!nabu_hall_sample(&s,0));
    assert(!nabu_hall_sample(&s,1)); assert(nabu_hall_sample(&s,1) && !s.closed);
    /* Covers already closed at boot publish closed, with unrelated IO bits ignored. */
    s=(struct NabuHallState){0};
    assert(!nabu_hall_sample(&s,0xaaaa)); assert(nabu_hall_sample(&s,0xaaaa) && s.closed);
    uint32_t config=0xa5a5ffff;
    assert(nabu_hall_input_config(config)==(config & ~0x23cu));
    assert(NABU_HALL_GPIO_PA==0x03909000 && NABU_HALL_POLL_MS>=15);
    if (!setjmp(stop)) hall_thread((void *)1);
    assert(attempts==4 && accepted==3 && released==4);
    assert(!observed[0] && observed[1] && !observed[2]);
    tick=4;
    assert(hall_init((void *)2,(void *)3,15,15,true,true)==(void *)2);
    puts("PASS: GPIO9 level/debounce/boot state, original HID bridge held-state suppression, failed-dispatch retry, ff09/1 closed/open and single-HES initialization");
}
'''
    c = a.output/'hall.c'
    c.write_text('#include "'+host_path(ROOT/'patches/nabu-input/NabuHall.h')+'"\n'+fixture)
    binary = a.output/'hall'
    command = ['clang', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', host_path(c), '-o', host_path(binary)]
    subprocess.run(host_command(command), check=True)
    result = subprocess.run(host_command([host_path(binary)]), capture_output=True, check=True)
    (a.output/'hall.log').write_bytes(result.stdout+result.stderr)
    report = dict(passed=True, result=result.stdout.decode().strip(), command=command,
                  scope='Production debounce and extracted production userland functions; synthetic GPIO/HID APIs, no hardware execution')
    (a.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__=='__main__': main()
