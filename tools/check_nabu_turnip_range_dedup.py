#!/usr/bin/env python3
"""Run the actual Turnip resource collector before/after exact-range deduplication."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from nabu_turnip_submit_dedup import apply_range_dedup

ROOT = Path(__file__).resolve().parents[1]


def function(source, name):
    match = re.search(r'^static [^\n]+\n' + re.escape(name) + r'\(', source, re.M)
    if not match:
        raise ValueError('Missing actual source function: ' + name)
    opening = source.index('{', match.start())
    # The selected functions have no braces in strings. Comments are stripped
    # only from the scan, not from the actual copied function body.
    depth = 0
    for end in range(opening, len(source)):
        if source[end] == '{': depth += 1
        elif source[end] == '}':
            depth -= 1
            if depth == 0:
                return source[match.start():end + 1]
    raise ValueError('Unclosed source function: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path,
        default=ROOT/'build/mesa-v164-focused/src/freedreno/vulkan/tu_knl_darwin.cc')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    source = args.source.read_text(encoding='utf-8')
    supplied_candidate = '\ndarwin_deduplicate_submit_ranges(' in source
    supplied_algorithm = 'hash' if '\ndarwin_raw_range_hash(' in source else 'qsort'
    baseline = apply_range_dedup(source, reverse=True,algorithm=supplied_algorithm) if supplied_candidate else source
    candidate = apply_range_dedup(baseline)
    sorted_candidate = apply_range_dedup(baseline,algorithm='qsort')
    if supplied_candidate and apply_range_dedup(baseline,algorithm=supplied_algorithm) != source:
        raise ValueError('Candidate did not roundtrip through the qualified transform')
    shared_names = ['darwin_resource_handle_compare', 'darwin_native_range_compare',
                    'darwin_add_native_range', 'darwin_collect_submit_resources']
    previous = '\n\n'.join(function(baseline, n) for n in shared_names)
    sorted_previous = '\n\n'.join(function(sorted_candidate, n) for n in
        ['darwin_raw_range_compare', 'darwin_deduplicate_submit_ranges', *shared_names])
    updated = '\n\n'.join(function(candidate, n) for n in
        ['darwin_raw_range_compare', 'darwin_raw_range_hash', 'darwin_deduplicate_submit_ranges', *shared_names])
    for name in shared_names[:-1]:
        assert function(baseline, name) == function(candidate, name), name
    fixture = (ROOT/'tools/fixtures/nabu_turnip_range_dedup.cpp').read_text(encoding='utf-8')
    lookup = function(baseline, 'darwin_lookup_bo_locked').replace(
        '\ndarwin_lookup_bo_locked(', '\nactual_darwin_lookup_bo_locked(', 1)
    cleanup = function(baseline, 'darwin_submit_finish')
    fixture = fixture.replace('/* ACTUAL_LOOKUP */', lookup)
    fixture = fixture.replace('/* ACTUAL_BASELINE */', previous)
    fixture = fixture.replace('/* ACTUAL_QSORT */', sorted_previous)
    fixture = fixture.replace('/* ACTUAL_CANDIDATE */', updated)
    fixture = fixture.replace('/* ACTUAL_CLEANUP */', cleanup)
    target = output/'actual-collector.cpp'; target.write_text(fixture, encoding='utf-8', newline='\n')
    report = dict(result='running', source=str(args.source.resolve()),
        input_already_patched=supplied_candidate, compared_algorithms=['original','qsort_all','hash_then_sort_unique'], actual_source_functions=shared_names +
        ['darwin_raw_range_compare','darwin_raw_range_hash','darwin_deduplicate_submit_ranges','darwin_lookup_bo_locked','darwin_submit_finish'],
        adapter_scope='Minimal byte dynarray, balanced BO index, native pthread mutex, BO refcount and diagnostic transport only',
        commands=[])
    def run(command, label):
        report['commands'].append(command)
        result = subprocess.run(host_command(command), capture_output=True)
        (output/(label+'.stdout')).write_bytes(result.stdout)
        (output/(label+'.stderr')).write_bytes(result.stderr)
        if result.returncode:
            raise RuntimeError(label + ' failed:\n' + result.stdout.decode(errors='replace')[-4000:] +
                               result.stderr.decode(errors='replace')[-5000:])
        return result.stdout.decode('utf-8', errors='replace')
    try:
        sanitized = output/'collector-sanitized'; release = output/'collector-release'
        common = ['clang++','-std=c++17','-Wall','-Wextra','-Werror','-pthread',host_path(target)]
        run(common + ['-O1','-g','-fno-omit-frame-pointer','-fsanitize=address,undefined',
                      '-o',host_path(sanitized)], 'compile-sanitized')
        report['semantic'] = json.loads(run([host_path(sanitized),'--semantic'], 'semantic'))
        run(common + ['-O2','-o',host_path(release)], 'compile-release')
        report['benchmark'] = json.loads(run([host_path(release),'--benchmark'], 'benchmark'))
        report['result'] = 'pass'
        report['limits'] = ('Host release timings are not iPadOS latency. Allocation-failure cases verify cleanup, '
            'not identical failure order after sorting. Native permission ranges and retained BO handles match; '
            'the unused per-object first-access field is not treated as a native permission union.')
    finally:
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k != 'commands'}, indent=2))


if __name__ == '__main__':
    main()
