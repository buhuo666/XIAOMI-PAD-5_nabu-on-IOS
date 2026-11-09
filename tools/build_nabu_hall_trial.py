#!/usr/bin/env python3
"""Add GPIO9 Hall input to an existing qualified kernel object set."""
import argparse
import json
from pathlib import Path
import shutil
import sys

from build_nabu_slpi_trial import run
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline-link-command', type=Path, required=True)
    p.add_argument('--compile-report', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    command = json.loads(a.compile_report.read_text())['command']
    flags = command[:command.index('-c')]
    flags += ['-DNABU_POWER_SERVICE=1', '-DNABU_USB_SERVICE=1',
              '-DNABU_WIRELESS_SERVICE=1', '-DNABU_GPU_SERVICE=1', '-DNABU_HALL_SERVICE=1']
    link = json.loads(a.baseline_link_command.read_text())
    objects = [link[i+1] for i, v in enumerate(link[:-1]) if v == '--object']
    if any(Path(o).name == 'NabuSlpi.o' for o in objects): flags.append('-DNABU_SLPI_TRIAL=1')
    commands = {}
    for name, source in [('NabuHall', 'patches/nabu-input/NabuHall.cpp'),
                         ('NabuDataKmod', 'patches/nabu-storage/NabuDataKmod.cpp')]:
        cmd = flags + ['-c', host_path(ROOT/source), '-o', host_path(a.output/(name+'.o'))]
        run(host_command(cmd), a.output/(name+'-compile.log'))
        commands[name] = cmd
    link[link.index('--output')+1] = str(a.output/'linked')
    entries = [i+1 for i, v in enumerate(link[:-1]) if v=='--object' and Path(link[i+1]).name=='NabuDataKmod.o']
    assert len(entries) == 1
    link[entries[0]] = str(a.output/'NabuDataKmod.o')
    link += ['--object', str(a.output/'NabuHall.o')]
    recipe = a.output/'link-command.json'
    recipe.write_text(json.dumps(link, indent=2)+'\n')
    run([sys.executable, *link], a.output/'link.log')
    run([sys.executable, str(ROOT/'tools/check_nabu_link_branches.py'), '--command', str(recipe),
         '--output', str(a.output/'branch-check.json')], a.output/'branch-check.log')
    run([sys.executable, str(ROOT/'tools/patch_nabu_return_trace.py'),
         '--kernel', str(a.output/'linked/kernel.native-apfs.macho'), '--output', str(a.output/'kernel')],
        a.output/'return-trace.log')
    for rel in ['patches/nabu-input/NabuHall.cpp', 'patches/nabu-input/NabuHall.h',
                'patches/nabu-storage/NabuDataKmod.cpp', 'userland/nabu/src/input_bridge.c',
                'tools/build_nabu_input_bridge.py', 'tools/build_nabu_hall_trial.py']:
        dest = a.output/'sources'/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/rel, dest)
    report = dict(kernel=str(a.output/'kernel/kernel.native-apfs.macho'),
                  target='arm64-apple-ios16.5', baseline_link=str(a.baseline_link_command.resolve()),
                  commands=commands, link_command_file=str(recipe), boot_argument='nabu-hall=1',
                  required_userland='Hall-enabled libnabu.input.dylib; nabu-input=1',
                  hardware='GPIO9, NORTH, active low, SW_LID', gpio_pa='0x03109000',
                  device_tested=False, deep_sleep_wake_verified=False)
    (a.output/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
