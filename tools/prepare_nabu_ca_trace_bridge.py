#!/usr/bin/env python3
"""Install bounded CA diagnostic marker transport; ordinary kdebug is unchanged."""
import argparse
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def install(tree):
    folder = tree/'bsd/kern/nabu_ca_trace'
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('NabuCaTraceBridge.h', 'NabuCaTraceBridge.c'):
        shutil.copyfile(ROOT/'patches/nabu-diagnostics'/name, folder/name)
    path = tree/'bsd/kern/kdebug.c'
    text = path.read_text()
    if 'nabu_ca_trace_user_marker(uap->code' not in text:
        anchor = '\tif (__probable(kdebug_enable == 0)) {\n'
        begin = text.index('kdebug_trace64(__unused struct proc *p,')
        at = text.index(anchor, begin)
        text = text[:at] + ('\tif (uap->code >= 0x31ca8144u && uap->code <= 0x31ca81fcu && !(uap->code & 3)) {\n'
                           '\t\tnabu_ca_trace_user_marker(uap->code, uap->arg1, uap->arg2,\n'
                           '\t\t    uap->arg3, uap->arg4, (uint32_t)proc_pid(p), thread_tid(current_thread()));\n'
                           '\t}\n') + text[at:]
        text = '#include "nabu_ca_trace/NabuCaTraceBridge.h"\n' + text
        path.write_text(text)
    conf = tree/'bsd/conf/files'
    text = conf.read_text()
    entry = 'bsd/kern/nabu_ca_trace/NabuCaTraceBridge.c standard'
    if entry not in text: conf.write_text(text+'\n'+entry+'\n')
    return dict(core_bridge=str(folder), default_recording=False, marker_events=[81, 127],
                transport='BSD syscall179; kdebug_trace64 original behavior retained')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tree',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args(); report=install(a.tree)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
