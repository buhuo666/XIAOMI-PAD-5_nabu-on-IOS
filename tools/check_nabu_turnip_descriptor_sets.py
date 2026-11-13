#!/usr/bin/env python3
"""Compare the actual descriptor-recording functions and their submission expansion."""
import argparse
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path
from nabu_turnip_descriptor_sets import transform

HARNESS = r'''
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <set>
#include <stdexcept>
#include <tuple>
#include <vector>
#define TU_HAS_DARWIN 1
enum { TU_RESOURCE_READ=1, VK_DESCRIPTOR_SET_LAYOUT_CREATE_PUSH_DESCRIPTOR_BIT_KHR=1,
       VK_DESCRIPTOR_BINDING_UPDATE_AFTER_BIND_BIT=2,
       VK_DESCRIPTOR_BINDING_UPDATE_UNUSED_WHILE_PENDING_BIT=4,
       TU_RESOURCE_FALLBACK_DEVICE_ADDRESS=8, TU_RESOURCE_FALLBACK_UPDATE_AFTER_BIND=16,
       VK_ERROR_OUT_OF_HOST_MEMORY=-1 };
struct tu_resource_range { uint64_t iova, size; uint32_t access; };
struct layout { uint32_t flags=0, binding_flags=0; };
struct tu_descriptor_set { struct layout *layout; uint64_t va=4096, size=32;
    uint32_t resource_count; tu_resource_range *resources; bool resource_addresses_unknown=false; };
struct util_dynarray { std::vector<tu_descriptor_set *> items; };
struct tu_cmd_buffer { struct { int error=0; } vk; util_dynarray resource_descriptor_sets;
    std::vector<tu_resource_range> ranges; uint32_t resource_fallback_reasons=0; };
static tu_descriptor_set **grow(util_dynarray *a) { a->items.push_back(nullptr); return &a->items.back(); }
#define util_dynarray_grow(a,t,n) grow(a)
#define util_dynarray_foreach(a,t,p) for (t *p=(a)->items.data(); p!=(a)->items.data()+(a)->items.size(); ++p)
static void tu_cmd_use_range(tu_cmd_buffer *c,tu_resource_range r) { c->ranges.push_back(r); }
template<class T> static void vk_command_buffer_set_error(T *v,int e) { v->error=e; }
namespace before {
/* BEFORE */
}
namespace after {
/* AFTER */
}
using Recorder=void(*)(tu_cmd_buffer *,tu_descriptor_set *);
using Ranges=std::set<std::tuple<uint64_t,uint64_t,uint32_t>>;
static std::vector<tu_resource_range> expand(const tu_cmd_buffer &c) {
    auto result=c.ranges;
    for (auto *s:c.resource_descriptor_sets.items) {
        if (s->layout->binding_flags & (VK_DESCRIPTOR_BINDING_UPDATE_AFTER_BIND_BIT |
                                        VK_DESCRIPTOR_BINDING_UPDATE_UNUSED_WHILE_PENDING_BIT)) continue;
        result.insert(result.end(),s->resources,s->resources+s->resource_count);
    }
    return result;
}
static Ranges effective(const tu_cmd_buffer &c) {
    Ranges out; for (const auto &r:expand(c)) out.emplace(r.iova,r.size,r.access); return out;
}
static void check(bool ok,const char *what) { if (!ok) throw std::runtime_error(what); }
static void semantics() {
    layout normal{},push{1,0},updated{0,2};
    tu_resource_range resources[2]={{8192,64,1},{16384,128,3}};
    tu_descriptor_set set{&normal,4096,32,2,resources,false};
    tu_cmd_buffer a,b;
    for (unsigned i=0;i<40;i++) { before::tu_cmd_use_descriptor_set(&a,&set); after::tu_cmd_use_descriptor_set(&b,&set); }
    check(a.resource_descriptor_sets.items.size()==40 && b.resource_descriptor_sets.items.size()==1,"repeated set");
    check(effective(a)==effective(b),"ordinary resource coverage");
    resources[0]={32768,256,2};
    check(effective(a)==effective(b) && effective(b).count({32768,256,2}),"submission reads current resources");
    a={};b={};set.layout=&push;set.resource_addresses_unknown=true;
    before::tu_cmd_use_descriptor_set(&a,&set);after::tu_cmd_use_descriptor_set(&b,&set);
    resources[0]={65536,512,1};
    before::tu_cmd_use_descriptor_set(&a,&set);after::tu_cmd_use_descriptor_set(&b,&set);
    check(effective(a)==effective(b) && effective(b).count({32768,256,2}) && effective(b).count({65536,512,1}),"push snapshots");
    check(a.resource_fallback_reasons==b.resource_fallback_reasons,"push unknown-address flag");
    a={};b={};set.layout=&updated;
    for (unsigned i=0;i<2;i++) { before::tu_cmd_use_descriptor_set(&a,&set); after::tu_cmd_use_descriptor_set(&b,&set); }
    check(a.resource_fallback_reasons==16 && b.resource_fallback_reasons==16,"update-after-bind flag");
    a={};b={};set.layout=&normal;
    before::tu_cmd_use_descriptor_set(&a,&set);after::tu_cmd_use_descriptor_set(&b,&set);
    check(b.resource_descriptor_sets.items.size()==1 && effective(a)==effective(b),"new recording after reset");
}
static volatile size_t sink=0;
static void bench(const char *name,Recorder record,unsigned unique,unsigned bindings,unsigned resources_per_set) {
    layout normal;
    std::vector<std::vector<tu_resource_range>> ranges(unique);
    std::vector<tu_descriptor_set> sets;
    for (unsigned i=0;i<unique;i++) {
        for (unsigned j=0;j<resources_per_set;j++) ranges[i].push_back({0x100000+uint64_t(i*resources_per_set+j)*4096,4096,1});
        sets.push_back({&normal,0x1000+uint64_t(i)*256,128,resources_per_set,ranges[i].data(),false});
    }
    constexpr unsigned loops=200;
    uint64_t recording=0,expansion=0;size_t references=0,expanded=0;
    for (unsigned iteration=0;iteration<loops;iteration++) {
        tu_cmd_buffer c;
        const auto start=std::chrono::steady_clock::now();
        for (unsigned i=0;i<bindings;i++) record(&c,&sets[i%unique]);
        const auto mid=std::chrono::steady_clock::now();
        auto result=expand(c);
        const auto end=std::chrono::steady_clock::now();
        recording+=std::chrono::duration_cast<std::chrono::nanoseconds>(mid-start).count();
        expansion+=std::chrono::duration_cast<std::chrono::nanoseconds>(end-mid).count();
        references=c.resource_descriptor_sets.items.size();expanded=result.size();sink+=expanded;
    }
    std::printf("{\"case\":\"%s\",\"unique_sets\":%u,\"bindings\":%u,\"references\":%zu,\"expanded_ranges\":%zu,\"record_ns\":%.1f,\"expand_ns\":%.1f}\n",
        name,unique,bindings,references,expanded,double(recording)/loops,double(expansion)/loops);
}
int main() {
    semantics();
    bench("repeated-before",before::tu_cmd_use_descriptor_set,8,384,128);
    bench("repeated-after",after::tu_cmd_use_descriptor_set,8,384,128);
    bench("unique-before",before::tu_cmd_use_descriptor_set,128,128,16);
    bench("unique-after",after::tu_cmd_use_descriptor_set,128,128,16);
}
'''


def function(source):
    begin = source.index('static void\ntu_cmd_use_descriptor_set(')
    opening = source.index('{', begin)
    depth = 0
    for end in range(opening, len(source)):
        depth += (source[end] == '{') - (source[end] == '}')
        if depth == 0:
            return source[begin:end + 1]
    raise ValueError('Descriptor recording function is incomplete')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    candidate = args.source.read_text()
    baseline = transform(candidate, reverse=True)
    text = HARNESS.replace('/* BEFORE */', function(baseline)).replace('/* AFTER */', function(candidate))
    args.output.mkdir(parents=True, exist_ok=True)
    cpp = args.output / 'descriptor-sets.cpp'
    cpp.write_text(text, encoding='utf-8', newline='\n')
    exe = args.output / 'descriptor-sets'
    subprocess.run(host_command(['clang++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                                 host_path(cpp), '-o', host_path(exe)]), check=True)
    result = subprocess.run(host_command([host_path(exe)]), check=True, capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    report = {'result': 'pass', 'source': str(args.source),
              'semantics': ['ordinary duplicates', 'late resource updates', 'push snapshots',
                            'fallback flags', 'reset'],
              'benchmark': [json.loads(line) for line in result.stdout.splitlines()],
              'limits': 'Synthetic host recording and expansion workloads; device performance remains to be measured.'}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
