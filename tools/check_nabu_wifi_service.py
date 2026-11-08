#!/usr/bin/env python3
"""Replay the new native Wi-Fi discovery and unavailable control behavior."""
import argparse
import json
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
        assert(get(&r)==0);for(unsigned i=0;i<sizeof(caps);i++)assert(!caps[i]);
    }
    r=(struct apple80211req){44,sizeof(name),name};assert(get(&r)==0);
    assert(strstr(name,"Nabu")&&strstr(name,"WCN399x")&&!strstr(name,"WCN6750"));
    return 0;
}
'''
    service = (ROOT / 'patches/nabu-wireless/NabuWlanService.cpp').read_text()
    service = '\n'.join(s for s in service.splitlines() if not s.startswith('#include'))
    native = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstddef>
#include <cerrno>
#define KERNEL 1
extern "C" {
#include <sys/hakios.sta.h>
}
using mbuf_t=void *;
struct hakios_net_link { const char *name;unsigned unit;uint8_t address[6];bool wireless,up;
    bool (*transmit)(mbuf_t,size_t);unsigned (*poll)(); };
static bool selected=false;static unsigned attaches;
static uint8_t address[6]={2,7,8,9,10,11};
struct OSData {unsigned getLength(){return 6;}const void *getBytesNoCopy(){return address;}};
struct IORegistryEntry {
    static IORegistryEntry *fromPath(const char *p,const char *) {
        assert(!strcmp(p,"/wlan"));static IORegistryEntry node;return selected?&node:nullptr;
    }
    OSData *getProperty(const char *p){assert(!strcmp(p,"local-mac-address"));static OSData mac;return &mac;}
    void release(){}
};
#define OSDynamicCast(type,value) (value)
static const char *gIODTPlane="IODeviceTree";
static void nabu_wireless_log(const char *,...){}
static const hakios_sta_ops *attached_ops;
static bool live=true;
static unsigned invalidations, lost_calls, link_calls, power_calls, scan_calls;
static int scan_errno;
extern "C" int nabu_ath10k_os_radio_powered(){return live;}
void hakios_sta_attach(const hakios_sta_ops *ops){attached_ops=ops;}
extern "C" void hakios_sta_invalidate(int){++invalidations;attached_ops=nullptr;}
bool hakios_sta_present(){return attached_ops!=nullptr;}
bool hakios_sta_powered(){return attached_ops!=nullptr;}
void hakios_sta_lost(int error){assert(error==ECONNRESET);++lost_calls;}
void hakios_net_link_state(bool up){assert(!up);++link_calls;}
static int raw_power(bool on){++power_calls;return on?EIO:0;}
static int raw_scan(const hakios_sta_scan *what){++scan_calls;assert(what->passive);return scan_errno;}
extern "C" bool hakios_net_attach(const hakios_net_link *link) {
    ++attaches;assert(link->wireless&&!link->up&&link->unit==0&&!link->poll);
    assert(!memcmp(link->address,address,6));assert(!link->transmit(nullptr,0));return true;
}
''' + service + r'''
int main() {
    nabu_wlan_service_publish();assert(!attaches);
    selected=true;nabu_wlan_service_publish();assert(attaches==1);
    nabu_wlan_service_publish();assert(attaches==1);
    hakios_sta_ops raw={};raw.power=raw_power;raw.scan=raw_scan;
    uint8_t wrong[6]={0};nabu_ath10k_os_net_attach(wrong);
    nabu_ath10k_os_station(&raw);assert(!attached_ops);
    nabu_ath10k_os_net_attach(address);live=false;
    nabu_ath10k_os_station(&raw);assert(!attached_ops);
    live=true;nabu_ath10k_os_station(&raw);assert(attached_ops&&!attached_ops->join);
    assert(attached_ops->power(true)==EIO&&attached_ops->power(false)==0&&power_calls==2);
    hakios_sta_scan scan={};scan.passive=true;
    assert(attached_ops->scan(&scan)==0);scan_errno=ETIMEDOUT;
    assert(attached_ops->scan(&scan)==ETIMEDOUT&&scan_calls==2);
    nabu_ath10k_os_net_link(1);nabu_ath10k_os_net_input(wrong,sizeof(wrong));
    nabu_ath10k_os_station_lost(ECONNRESET);assert(attached_ops&&lost_calls==1);
    nabu_wlan_service_invalidate(ENXIO);assert(invalidations==1&&!attached_ops);
    nabu_ath10k_os_station(nullptr);assert(!backend&&link_calls>=3&&attaches==1);
    return 0;
}
'''
    for name, text, compiler, standard in [('control', control, 'clang-18', 'c11'),
                                           ('service', native, 'clang++-18', 'c++17')]:
        src = out / (name + ('.c' if standard == 'c11' else '.cpp'))
        binary = out / (name + '-test')
        src.write_text(text)
        subprocess.run(host_command([compiler, '-std=' + standard, '-fsanitize=address,undefined',
            '-I' + host_path(ROOT / 'src/hakios-8796/xnu/files/bsd'),
            '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-g', host_path(src), '-o', host_path(binary)]), check=True)
        result = subprocess.run(host_command([host_path(binary)]), capture_output=True, check=True)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
    mac = bytes([2, 7, 8, 9, 10, 11])
    _, children = parse(make_tree(bytes(64), wifi_mac=mac, wlan_native_service=True).encode())
    wlan, = [props for props, _ in children if props['name'] == b'wlan\0']
    assert wlan['local-mac-address'] == mac
    assert wlan['compatible'] == b'qcom,wcn3990-wifi\0'
    assert struct.unpack('<2Q', wlan['reg']) == (0x18800000, 0x800000)
    _, children = parse(make_tree(bytes(64), wifi_mac=mac).encode())
    assert not any(props['name'] == b'wlan\0' for props, _ in children)
    report = {'hardware_tested': False, 'source_patch_applied': str(patch),
              'sanitizers': ['address', 'undefined'],
              'passed': ['no backend reports off', 'attached backend power preserved',
                         'scan-only backend advertises no encryption capabilities', 'Nabu driver identity',
                         'backend MAC and readiness required', 'native power/scan preserve backend errors',
                         'association unavailable and link-up refused', 'AP loss differs from fatal withdrawal',
                         'explicit device discovery', 'one stable down interface', 'unavailable transmit refused',
                         'real wlan ADT address and register geometry']}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
