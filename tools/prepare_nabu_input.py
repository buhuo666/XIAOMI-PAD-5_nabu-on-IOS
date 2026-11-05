#!/usr/bin/env python3
"""Connect nabu's point/PMIC producers to the existing input queue."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    copied = []
    for name, parent in [('NabuTouch.cpp', 'iokit/Kernel/nabu_input'),
                         ('NabuTouchPackets.h', 'iokit/Kernel/nabu_input'),
                         ('NabuTouchReady.h', 'iokit/Kernel/nabu_input'),
                         ('NabuButtons.c', 'bsd/dev/nabu_input')]:
        dest = args.tree/parent/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = (ROOT/'patches/nabu-input'/name).read_text(encoding='utf-8')
        dest.write_text(text, encoding='utf-8')
        copied.append({'path': dest.relative_to(args.tree).as_posix(),
                       'source': 'patches/nabu-input/'+name,
                       'sha256_lf': hashlib.sha256(text.encode()).hexdigest()})
    for rel, entry in [('iokit/conf/files.arm64', 'iokit/Kernel/nabu_input/NabuTouch.cpp'),
                       ('bsd/conf/files.arm64', 'bsd/dev/nabu_input/NabuButtons.c')]:
        with (args.tree/rel).open('a') as output:
            output.write('\n'+entry+' optional nos_arm_asm\n')
    bsd = args.tree/'bsd/kern/bsd_init.c'
    text = bsd.read_text()
    anchor = '\t\thakios_input_init();           /* /dev/hakios-touch */'
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor+'\n\t\textern void nabu_touch_init(void);'
                        '\n\t\textern void nabu_buttons_init(void);'
                        '\n\t\tnabu_touch_init();\n\t\tnabu_buttons_init();')
    bsd.write_text(text)
    # The reference input queue had a hidden five-finger timed exit. Keep it
    # opt-in now that the user is testing real multi-touch without timed stops.
    queue = args.tree/'bsd/dev/hakios.input.c'
    text = queue.read_text()
    anchor = '\texit_call = thread_call_allocate(exit_hold_elapsed, NULL);'
    assert text.count(anchor) == 1
    text = text.replace(anchor, '\tuint32_t touch_exit = 0;\n'
        '\tPE_parse_boot_argn("touch_exit", &touch_exit, sizeof(touch_exit));\n'
        '\tif (touch_exit) exit_call = thread_call_allocate(exit_hold_elapsed, NULL);')
    queue.write_text(text)
    report = {'generated': copied, 'entrypoints': ['nabu_touch_init', 'nabu_buttons_init'],
              'queue': '/dev/hakios-touch', 'five_finger_exit': 'opt-in touch_exit=1',
              'scope': 'Source integration; hardware input requires device execution'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
