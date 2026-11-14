#!/usr/bin/env python3
"""Exercise the production keyboard geometry rule without UIKit or a device."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path

ROOT=Path(__file__).resolve().parents[1]

HARNESS=r'''#include "keyboard_geometry.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
int main(void) {
    struct screen { double scale,width,height; int nabu; } screens[]={
        {2,1600,2560,1},{2,2560,1600,1},{1,1600,2560,0},{3,1600,2560,0},
        {2,1599,2560,0},{2,1600,2561,0},{2,1536,2048,0},{2,2048,2732,0},
        {2,0,0,0},{2.0001,1600,2560,0}
    };
    const double widths[]={0,-1,320,800,1280};
    const double heights[]={0,-1,1,258,320,352};
    unsigned count=0;
    for(unsigned s=0;s<sizeof(screens)/sizeof(screens[0]);s++)
        for(unsigned w=0;w<sizeof(widths)/sizeof(widths[0]);w++)
            for(unsigned h=0;h<sizeof(heights)/sizeof(heights[0]);h++) {
                double expected=heights[h];
                if(screens[s].nabu && w>=2 && h==0) expected=-1;
                double actual=nabu_keyboard_layout_height(widths[w],heights[h],
                    screens[s].scale,screens[s].width,screens[s].height);
                assert(actual==expected); count++;
            }
    assert(isnan(nabu_keyboard_layout_height(800,NAN,2,1600,2560)));
    assert(nabu_keyboard_layout_height(NAN,0,2,1600,2560)==0);
    printf("{\"passed\":true,\"geometry_cases\":%u,\"nan_values_preserved\":true,\"device_executed\":false}\n",count);
    return 0;
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'test.c').write_text(HARNESS)
    command=['clang-18','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined','-I'+host_path(ROOT/'userland/nabu/src'),
        host_path(out/'test.c'),'-o',host_path(out/'test')]
    r=subprocess.run(host_command(command),capture_output=True)
    (out/'compile.log').write_bytes(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
    r=subprocess.run(host_command([host_path(out/'test')]),capture_output=True)
    (out/'test.log').write_bytes(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
    report=json.loads(r.stdout)
    report.update(sanitizers=['address','undefined'],scope='Pure geometry only; UIKit layout audit and keyboard presentation are separate')
    (out/'host-check.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
