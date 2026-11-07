#!/usr/bin/env python3
"""Exercise the actual framebuffer configuration method, then inspect linked code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

from check_capacity_kernel import symbols
from check_darwinboot_8796 import host_command, host_path
from make_nabu_adt import make_tree, parse

ROOT = Path(__file__).resolve().parents[1]


def method(source, name):
    start = source.index('\nbool\nIOMobileFramebuffer::' + name + '(')
    body = source.index('{', start)
    end, depth = body + 1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--candidate', type=Path)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    source_path = a.tree / 'iokit/Kernel/MiniIOMobileFramebuffer.cpp'
    source = source_path.read_text()
    config = method(source, 'configureDisplay')
    start = method(source, 'start')
    assert start.index('if (!configureDisplay())') < start.index('kernel_thread_start')
    assert 'fWidth =' not in start and 'fHeight =' not in start
    pitch = source[source.index('\tcase kFBMethodGetDotPitch:'):]
    pitch = pitch[:pitch.index('\n\tcase ', 1)]
    assert 'out[0] = fOwner->fDotsPerInch;' in pitch
    assert 'kFBDotsPerInch' not in pitch

    prelude = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
struct OSObject { virtual ~OSObject() = default; };
struct OSData : OSObject {
    uint32_t value[2] = {147400,235900};
    unsigned length = 8;
    unsigned getLength() { return length; }
    const void * getBytesNoCopy() { return value; }
};
static OSData sizeProperty;
static OSObject wrongType;
static bool nodePresent = true;
static OSObject * property = &sizeProperty;
static unsigned releases, scaleWrites;
static int gIODTPlane;
struct IORegistryEntry {
    static IORegistryEntry * fromPath(const char *, int) {
        static IORegistryEntry entry;
        return nodePresent ? &entry : nullptr;
    }
    OSObject * getProperty(const char * key) {
        assert(!strcmp(key,"nabu-panel-size-um")); return property;
    }
    void setProperty(const char *, const void *, unsigned) { scaleWrites++; }
    void release() { releases++; }
};
#define OSDynamicCast(type,object) dynamic_cast<type *>(object)
#define IOLog(...) ((void)0)
#define kFBDefaultWidth 1125
#define kFBDotsPerInch 458
#define kFBPointsWide 375
#define kFBPointsHigh 812
#define kFBDefaultScale 3
static uint32_t gFBWidth=1125, gFBHeight=2436, gFBScale=0;
static struct { uintptr_t v_baseaddr; uint32_t v_width, v_height, v_rowbytes; }
    vinfo = {0x1000,1600,2560,6400};
struct IOMobileFramebuffer {
    uint8_t * fBase;
    uint32_t fPanelWidth, fPanelHeight, fRowBytes, fWidth, fHeight, fDotsPerInch;
    bool configureDisplay();
};
'''
    tests = r'''
int main() {
    unsigned cases=0;
    IOMobileFramebuffer fb{};
    auto native = [&]() {
        assert(fb.configureDisplay());
        assert(fb.fWidth==1600 && fb.fHeight==2560 && fb.fRowBytes==6400);
        assert(fb.fDotsPerInch==276 && scaleWrites==0);
        // A native full frame reaches every panel pixel without unequal scaling.
        assert(uint64_t(fb.fWidth)*fb.fPanelHeight == uint64_t(fb.fHeight)*fb.fPanelWidth);
        cases++;
    };
    native();
    gFBScale=2; native(); // formerly forced 750x1624 phone geometry
    gFBScale=3; gFBWidth=2048; gFBHeight=1536; native();
    gFBScale=0; sizeProperty.length=4; assert(!fb.configureDisplay()); cases++;
    sizeProperty.length=12; assert(!fb.configureDisplay()); cases++;
    sizeProperty.length=8; property=&wrongType; assert(!fb.configureDisplay()); cases++;
    property=&sizeProperty; sizeProperty.value[0]=0; assert(!fb.configureDisplay()); cases++;
    sizeProperty.value[0]=147400; sizeProperty.value[1]=0; assert(!fb.configureDisplay()); cases++;
    sizeProperty.value[1]=235900; vinfo.v_width=0; assert(!fb.configureDisplay()); cases++;
    vinfo.v_width=1600; vinfo.v_height=0; assert(!fb.configureDisplay()); cases++;
    vinfo.v_height=2560; vinfo.v_rowbytes=6399; assert(!fb.configureDisplay()); cases++;
    vinfo.v_rowbytes=6400; vinfo.v_width=UINT32_MAX; assert(!fb.configureDisplay()); cases++;
    vinfo.v_width=1600; sizeProperty.value[0]=UINT32_MAX; assert(!fb.configureDisplay()); cases++;
    sizeProperty.value[0]=10000; assert(!fb.configureDisplay()); cases++; // >2000 PPI
    sizeProperty.value[0]=147400;
    property=nullptr; gFBWidth=1125; gFBHeight=2436;
    assert(fb.configureDisplay() && fb.fWidth==1125 && fb.fHeight==2436 && fb.fDotsPerInch==458); cases++;
    gFBScale=2;
    assert(fb.configureDisplay() && fb.fWidth==750 && fb.fHeight==1624 && fb.fDotsPerInch==305);
    assert(scaleWrites==2); cases++;
    nodePresent=false; gFBScale=0; gFBWidth=0; gFBHeight=0;
    assert(fb.configureDisplay() && fb.fWidth==1600 && fb.fHeight==2560); cases++;
    // Missing node owns no reference; each earlier attempt released its lookup.
    assert(releases==18);
    printf("%u native/invalid/legacy display cases passed\n",cases);
}
'''
    cpp, binary = a.output/'display-policy.cpp', a.output/'display-policy'
    cpp.write_text(prelude + config + tests)
    subprocess.run(host_command(['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                                 '-fsanitize=address,undefined', host_path(cpp), '-o', host_path(binary)]), check=True)
    result = subprocess.check_output(host_command([host_path(binary)]), text=True).strip()
    # Donor software identity changes model and its exact product-id; every
    # other property, including hardware nodes, pixels, memory and scale, agrees.
    trees = [parse(make_tree(bytes(64), bootstrap=True, userland_model=m).encode())
             for m in (None, 'iPad7,11')]
    products = [next(props for props, _ in tree[1] if props['name'] == b'product\0')
                for tree in trees]
    assert 'product-id' not in products[0]
    assert products[1].pop('product-id') == bytes.fromhex('4d013e8fae976e61a7b3b69cdb5a015fa7ff04bb')
    assert trees[0][1] == trees[1][1]
    assert {k:v for k,v in trees[0][0].items() if k != 'model'} == {
        k:v for k,v in trees[1][0].items() if k != 'model'}
    report = {'passed': True, 'host_result': result,
              'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
              'model_independent_hardware_nodes': True,
              'identity_only_differences': ['/model', '/product/product-id'],
              'scope': 'Actual configuration method under ASan/UBSan with registry/boot-video mocks; no panel or desktop claim.'}
    if a.candidate:
        data = a.candidate.read_bytes()
        syms, segments = symbols(data)
        names = [n for n in syms if n.startswith('__ZN') and any(token in n for token in (
            'IOMobileFramebuffer16configureDisplay', 'IOMobileFramebuffer5start',
            'IOMobileFramebuffer12publishModes', 'IOMobileFramebuffer9drawLayer',
            'IOMobileFramebufferUserClient14externalMethod'))]
        assert len(names) == 5, names
        ranges = []
        for name in names:
            address = syms[name]
            end = min(v for v in syms.values() if v > address)
            count = end-address
            assert count > 0 and count % 4 == 0
            seg = next(s for s in segments if s[0] <= address and address+count <= s[0]+s[3])
            off = seg[2]+address-seg[0]
            ranges.append({'name': name, 'status': 'code-range', 'address': hex(address), 'bytes': count,
                           'sha256': hashlib.sha256(data[off:off+count]).hexdigest()})
        plan = {'scope': 'Native display configuration and consumer ranges; static LLDB, no process',
                'targets': [{'label': 'native-display', 'path': str(a.candidate.resolve()),
                             'sha256': hashlib.sha256(data).hexdigest(), 'symbols': ranges}]}
        plan_path = a.output.resolve()/'native-plan.json'
        plan_path.write_text(json.dumps(plan, indent=2)+'\n')
        native_path = a.output.resolve()/'native-instructions.json'
        env = dict(os.environ, NABU_NATIVE_ANALYSIS_PLAN=str(plan_path), NABU_NATIVE_ANALYSIS_OUTPUT=str(native_path))
        lldb = subprocess.check_output(['xcrun','--find','lldb'], text=True).strip()
        run = subprocess.run([lldb, '--batch', '--no-lldbinit', '-o',
                              'command script import "'+str(ROOT/'tools/lldb_20f66.py')+'"'], env=env, capture_output=True, text=True)
        (a.output/'lldb.log').write_text(run.stdout+run.stderr)
        assert run.returncode == 0
        native = json.loads(native_path.read_text())
        assert native['all_ranges_decoded']
        config_address = syms['__ZN19IOMobileFramebuffer16configureDisplayEv']
        start_code = next(s for s in native['targets'][0]['symbols']
                          if s['name'] == '__ZN19IOMobileFramebuffer5startEP9IOService')
        calls = []
        for instruction in start_code['instructions']:
            word = int.from_bytes(bytes.fromhex(instruction['bytes']), 'little')
            if word & 0xfc000000 == 0x94000000:
                delta = word & 0x03ffffff
                if delta & 0x02000000:
                    delta -= 0x04000000
                calls.append(int(instruction['address'], 16) + delta*4)
        assert config_address in calls, 'Linked start must invoke native display configuration'
        report['linked_start_calls_configuration'] = True
        report['candidate_sha256'] = hashlib.sha256(data).hexdigest()
        report['native_summary'] = native['summary']
    (a.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
