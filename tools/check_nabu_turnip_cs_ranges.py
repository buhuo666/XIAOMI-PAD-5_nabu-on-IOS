#!/usr/bin/env python3
"""Check actual CS recording/forwarding and resulting native resource permissions."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from check_darwinboot_8796 import host_command,host_path
from check_nabu_turnip_range_dedup import function
from nabu_turnip_cs_ranges import transform as apply_record_range_index, HEADER
from nabu_turnip_submit_dedup import apply_range_dedup

ROOT=Path(__file__).resolve().parents[1]
FILES=('tu_cs.cc','tu_cs.h','tu_cmd_buffer.cc')
PRELUDE=r'''
#include <stdlib.h>
#include <string.h>
static void recording_free(void *pointer){if(pointer)collector_free(pointer);}
#define calloc collector_calloc
#define free recording_free
#include "tu_resource_range_index.h"
#undef calloc
#undef free
static void util_dynarray_clear(util_dynarray *array){array->size=0;}
enum {TU_CS_MODE_GROW,TU_CS_MODE_EXTERNAL};
struct tu_cs {
    util_dynarray resource_ranges{};
    tu_resource_range_index resource_range_index{};
    tu_cs *parent=nullptr;
    int mode=TU_CS_MODE_GROW;
    VkResult record_result=VK_SUCCESS;
};
struct tu_cmd_buffer {
    struct {VkResult error=VK_SUCCESS;} vk;
    util_dynarray resource_ranges{};
};
static void tu_cs_set_error(tu_cs *cs,VkResult result){if(cs->record_result==VK_SUCCESS)cs->record_result=result;}
template<class Vk> static void vk_command_buffer_set_error(Vk *vk,VkResult result){if(vk->error==VK_SUCCESS)vk->error=result;}
#define TU_HAS_DARWIN 1
namespace record_before {
/* RECORD_BEFORE */
}
namespace record_after {
/* RECORD_AFTER */
}
'''


def recording_function(source,name):
    start=source.index('void\n'+name+'(')
    opening=source.index('{',start);depth=0
    for end in range(opening,len(source)):
        if source[end]=='{':depth+=1
        elif source[end]=='}':
            depth-=1
            if depth==0:return source[start:end+1]
    raise ValueError('Unclosed recording function '+name)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True,help='Patched Mesa src/freedreno/vulkan directory')
    p.add_argument('--driver-source',type=Path,
        default=ROOT/'build/mesa-v164-focused/src/freedreno/vulkan/tu_knl_darwin.cc')
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    sources={name:(a.source/name).read_text(encoding='utf-8') for name in FILES}
    before=apply_record_range_index(sources,reverse=True)
    if apply_record_range_index(before)!=sources:
        raise ValueError('Actual recording patch does not roundtrip')
    header=(a.source/HEADER).read_text(encoding='utf-8')
    if header!=(ROOT/'patches/nabu-vulkan'/HEADER).read_text(encoding='utf-8'):
        raise ValueError('Actual record index header differs from tested source')
    (out/HEADER).write_text(header,encoding='utf-8',newline='\n')
    driver=a.driver_source.read_text(encoding='utf-8')
    if '\ndarwin_deduplicate_submit_ranges(' in driver:
        driver=apply_range_dedup(driver,reverse=True,
            algorithm='hash' if '\ndarwin_raw_range_hash(' in driver else 'qsort')
    candidate=apply_range_dedup(driver);sorted_driver=apply_range_dedup(driver,algorithm='qsort')
    shared=['darwin_resource_handle_compare','darwin_native_range_compare',
            'darwin_add_native_range','darwin_collect_submit_resources']
    harness=(ROOT/'tools/fixtures/nabu_turnip_range_dedup.cpp').read_text(encoding='utf-8')
    harness=harness.replace('/* ACTUAL_LOOKUP */',function(driver,'darwin_lookup_bo_locked').replace(
        '\ndarwin_lookup_bo_locked(','\nactual_darwin_lookup_bo_locked(',1))
    harness=harness.replace('/* ACTUAL_CLEANUP */',function(driver,'darwin_submit_finish'))
    harness=harness.replace('/* ACTUAL_BASELINE */','\n\n'.join(function(driver,n) for n in shared))
    harness=harness.replace('/* ACTUAL_QSORT */','\n\n'.join(function(sorted_driver,n) for n in
        ['darwin_raw_range_compare','darwin_deduplicate_submit_ranges',*shared]))
    harness=harness.replace('/* ACTUAL_CANDIDATE */','\n\n'.join(function(candidate,n) for n in
        ['darwin_raw_range_compare','darwin_raw_range_hash','darwin_deduplicate_submit_ranges',*shared]))
    # For recording failure injection count only genuine growing realloc sites;
    # the collector fixture's preallocated arrays remain its adapter boundary.
    old='''    grows++;
    if (allocation_fail_after == 0) return nullptr;
    if (allocation_fail_after > 0) allocation_fail_after--;
    const size_t extra = count * element, before = a->size;
    if (before + extra > a->capacity) {'''
    new='''    const size_t extra = count * element, before = a->size;
    if (before + extra > a->capacity) {
        grows++;
        if (allocation_fail_after == 0) return nullptr;
        if (allocation_fail_after > 0) allocation_fail_after--;'''
    if harness.count(old)!=1:raise ValueError('Dynarray allocation adapter changed')
    harness=harness.replace(old,new,1).replace('int main(int argc,char **argv)',
        'int collector_adapter_main(int argc,char **argv)',1)
    # The original fixture's main has C++'s implicit return; the renamed helper does not.
    harness=harness.rstrip()[:-1]+'    return 0;\n}\n'
    def funcs(items):
        return '\n\n'.join(recording_function(items[file],name) for file,name in
            [('tu_cs.cc','tu_cs_use_range'),('tu_cs.cc','tu_cs_use_resources'),
             ('tu_cmd_buffer.cc','tu_cmd_use_range')])
    prelude=PRELUDE.replace('/* RECORD_BEFORE */',funcs(before)).replace('/* RECORD_AFTER */',funcs(sources))
    extension=(ROOT/'tools/fixtures/nabu_turnip_cs_ranges.cpp').read_text(encoding='utf-8')
    harness+='\n'+extension.replace('/* RECORDING_PRELUDE */',prelude)
    source=out/'actual-recording.cpp';source.write_text(harness,encoding='utf-8',newline='\n')
    report=dict(result='running',source=str(a.source.resolve()),commands=[],
        actual_functions=['tu_cs_use_range','tu_cs_use_resources','tu_cmd_use_range',
                          'darwin_collect_submit_resources','darwin_lookup_bo_locked','darwin_submit_finish'],
        metadata_scope='Exact address/size keys only, same effective access; no adjacent or overlapping key merge')
    def run(command,label):
        report['commands'].append(command)
        result=subprocess.run(host_command(command),capture_output=True)
        (out/(label+'.log')).write_bytes(result.stdout+result.stderr)
        if result.returncode:raise RuntimeError((result.stdout+result.stderr).decode(errors='replace')[-6000:])
        return result.stdout.decode()
    try:
        common=['clang++','-std=c++17','-Wall','-Wextra','-Werror','-pthread','-I'+host_path(out),host_path(source)]
        sanitized=out/'recording-sanitized';release=out/'recording-release'
        run(common+['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer','-o',host_path(sanitized)],'compile-sanitized')
        report['semantic']=json.loads(run([host_path(sanitized),'--semantic'],'semantic'))
        run(common+['-O2','-o',host_path(release)],'compile-release')
        report['benchmark']=json.loads(run([host_path(release),'--benchmark'],'benchmark'))
        report['result']='pass'
        report['limits']='Host timings do not establish iPadOS gains. Native array shape may differ; '
        report['limits']+='compare access coverage at every per-BO interval boundary, fallback and exact retained BO handles. '
        report['limits']+='Reset/finish wiring is verified by the exact source transform and complete iOS build.'
    finally:
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='commands'},indent=2))


if __name__=='__main__':
    main()
