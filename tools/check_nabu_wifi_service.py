#!/usr/bin/env python3
"""Test actual native control and association/data adapter against controlled peers."""
import argparse
import json
import re
from pathlib import Path
import shutil
import struct
import subprocess

from check_darwinboot_8796 import host_command, host_path
from make_nabu_adt import make_tree, parse

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    tree = out / 'source'
    target = tree / 'bsd/dev/hakios.apple80211.c'
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'src/hakios-8796/drivers/wifi/hakios.apple80211.c', target)
    patch = ROOT / 'patches/8796/nabu-wifi-control-state.patch'
    subprocess.run(host_command(['patch', '-p1', '-d', host_path(tree), '-i', host_path(patch)]), check=True)
    source = target.read_text()
    start = source.index('static int\nget(struct apple80211req *request)')
    end = source.index('\n\tcase 15:', start)
    get = source[start:end] + '\n\tdefault: return EINVAL;\n\t}\n}\n'
    control = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <errno.h>
struct apple80211req { int req_type; unsigned req_len; void *req_data; };
struct hakios_sta_state;
static bool present, powered;
static bool hakios_sta_present(void) { return present; }
static bool hakios_sta_powered(void) { return present && powered; }
static int give(struct apple80211req *r, const void *p, size_t n) {
    assert(r->req_len >= n); memcpy(r->req_data,p,n); return 0;
}
''' + get + r'''
int main(void) {
    uint32_t power[6]; unsigned char caps[13]; char name[256];
    struct apple80211req r = {19,sizeof(power),power};
    for (unsigned p=0;p<2;p++) for (unsigned on=0;on<2;on++) {
        present=p;powered=on;assert(get(&r)==0);
        assert(power[0]==1 && power[1]==1 && power[2]==(p&&on));
        assert(!power[3]&&!power[4]&&!power[5]);
    }
    for(unsigned p=0;p<2;p++) {
        present=p;r=(struct apple80211req){12,sizeof(caps),caps};
        assert(get(&r)==0);assert(caps[0]==8 && caps[1]==64);
        for(unsigned i=2;i<sizeof(caps);i++)assert(!caps[i]);
    }
    r=(struct apple80211req){44,sizeof(name),name};assert(get(&r)==0);
    assert(strstr(name,"Nabu")&&strstr(name,"WCN399x")&&!strstr(name,"WCN6750"));
    return 0;
}
'''
    signal_start = source.index('void\nhakios_apple80211_signal(')
    signal_end = source.index('\n/* What the station side says', signal_start)
    event_enum = re.search(r'enum \{ EVENT_POWER_CHANGED.*?\};', source, re.S).group()
    signal = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
static unsigned emitted;
static int expected;
static void post(unsigned code, const void *data, size_t length) {
    const uint8_t *bytes=data;int32_t rssi;
    assert(code==39 && length==180 && bytes[0]==1);
    memcpy(&rssi,bytes+4,4);assert(rssi==expected);
    for(unsigned i=1;i<180;i++) if(i<4||i>=8) assert(bytes[i]==0);
    emitted++;
}
''' + event_enum + '\n' + source[signal_start:signal_end] + r'''
int main(void) {
    const int samples[]={-42,-90,-65,-127,0};
    for(unsigned i=0;i<sizeof(samples)/sizeof(samples[0]);i++) {
        expected=samples[i];hakios_apple80211_signal(expected);
    }
    assert(emitted==5);return 0;
}
'''
    service = (ROOT / 'patches/nabu-wireless/NabuWlanService.cpp').read_text()
    service = '\n'.join(s for s in service.splitlines() if not s.startswith('#include'))
    fixtures = ROOT / 'tools/fixtures/nabu_wifi_service'
    native = (fixtures / 'host.h').read_text() + '\n' + service + '\n' + (fixtures / 'replay.cpp').read_text()
    for name, text, compiler, standard in [('control', control, 'clang-18', 'c11'),
                                           ('signal', signal, 'clang-18', 'c11'),
                                           ('service', native, 'clang++-18', 'c++17')]:
        src = out / (name + ('.c' if standard == 'c11' else '.cpp'))
        binary = out / (name + '-test')
        src.write_text(text, newline="\n")
        subprocess.run(host_command([compiler, '-std=' + standard, '-pthread', '-fsanitize=address,undefined',
            '-I' + host_path(ROOT / 'src/hakios-8796/xnu/files/bsd'),
            '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-g', host_path(src), '-o', host_path(binary)]), check=True)
        result = subprocess.run(host_command([host_path(binary)]), capture_output=True, check=True)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
    mac = bytes([2, 7, 8, 9, 10, 11])
    _, children = parse(make_tree(bytes(64), wifi_mac=mac, wlan_native_service=True).encode())
    defaults, = [props for props, _ in children if props['name'] == b'defaults\0']
    assert defaults['AAPL,ignore'] == struct.pack('<I', 1)
    assert defaults['sleep-disabled'] == struct.pack('<I', 1)
    assert defaults['kern.vm_compressor'] == struct.pack('<I', 2)
    wlan, = [props for props, _ in children if props['name'] == b'wlan\0']
    assert 'AAPL,ignore' not in wlan
    assert wlan['local-mac-address'] == mac
    assert wlan['compatible'] == b'qcom,wcn3990-wifi\0'
    assert struct.unpack('<2Q', wlan['reg']) == (0x18800000, 0x800000)
    _, children = parse(make_tree(bytes(64), wifi_mac=mac).encode())
    assert not any(props['name'] == b'wlan\0' for props, _ in children)
    report = {'hardware_tested': False, 'source_patch_applied': str(patch),
              'sanitizers': ['address', 'undefined'],
              'passed': ['no backend reports off', 'attached backend power preserved',
                         'only CCMP and WPA2 capability bits advertised', 'Nabu driver identity', '20F66 event39 encoding carries only valid real RSSI',
                         'backend MAC and readiness required', 'native power/scan preserve backend errors',
                         'late join publication gated by native commit', 'AP loss differs from fatal withdrawal',
                         'explicit device discovery', 'one stable down interface', 'copied TX queue, overflow/errors, control drain, AP loss and fatal tested',
                         'real wlan ADT address and register geometry']}
    report['passed'].append('ADT defaults ignore flag/config retained; WLAN selected; live nub behavior not asserted')
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
