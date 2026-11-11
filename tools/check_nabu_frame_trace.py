#!/usr/bin/env python3
"""Exercise bounded trace windows, immutable export/retry, overflow and callers' serialization."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from check_darwinboot_8796 import host_command, host_path
from nabu_frame_trace import WIRE, save_export, validate_export
from check_nabu_dpu_display_lifecycle import body

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include "NabuFrameTraceCore.h"
#include <cassert>
#include <cstdio>
#include <mutex>
#include <thread>
#include <vector>
using namespace NabuFrameTrace;
void boundaries() {
    Recorder r;Record storage[4],out[4];uint32_t n=99;
    assert(r.start(100,1)==Invalid);
    assert(r.initialize(storage,4)==Ok&&r.initialize(storage,4)==Invalid);
    assert(r.start(100,0)==Invalid&&r.start(UINT64_MAX,1)==Invalid);
    assert(r.start(100,1)==Ok);
    assert(!r.append(99,1,0));assert(r.append(100,1,1));assert(r.append(1099,2,2));
    assert(r.read(0,out,4,&n)==NotStopped&&n==0);
    assert(!r.append(1100,3,3));
    assert(!r.metadata().active&&r.metadata().endUs==1100&&r.metadata().count==2);
    assert(r.start(2000,1)==Busy);assert(r.read(0,out,4,&n)==Ok&&n==2);
    assert(out[0].identity==1&&out[1].timeUs==1099&&out[1].window==1);
    assert(r.start(2000,1)==Busy);assert(r.acknowledge(1)==Invalid);
    assert(r.acknowledge(2)==Ok&&r.acknowledge(2)==Ok);
    assert(r.start(2000,1)==Ok&&r.metadata().window==2);r.stop(2001);
    assert(r.metadata().endUs==2001);
    assert(r.acknowledge(0)==Ok);
}
void overflow_export_and_retry() {
    Recorder r;Record storage[4],out[4];uint32_t n;
    assert(r.initialize(storage,4)==Ok&&r.start(10,10)==Ok);
    for(unsigned i=0;i<9;++i)assert(r.append(11+i,1,i)==(i<4));
    assert(r.metadata().dropped==5&&r.metadata().count==4);r.stop(30);
    assert(r.read(3,out,1,&n)==Ok&&n==1&&r.metadata().exportedThrough==0);
    assert(r.start(40,1)==Busy);
    assert(r.acknowledge(4)==Invalid);
    assert(r.read(0,out,2,&n)==Ok&&n==2&&out[0].identity==0&&out[1].identity==1);
    assert(r.read(0,out,2,&n)==Ok&&n==2&&r.metadata().exportedThrough==2);
    assert(r.read(4,out,1,&n)==Ok&&n==0&&r.metadata().exportedThrough==2);
    assert(r.read(5,out,1,&n)==Invalid&&n==0);
    assert(r.read(2,out,2,&n)==Ok&&n==2&&r.metadata().exportedThrough==4);
    assert(r.start(40,1)==Busy&&r.acknowledge(3)==Invalid);
    assert(r.acknowledge(4)==Ok);
    assert(r.start(40,1)==Ok&&r.metadata().dropped==0&&r.metadata().count==0);
}
void serialized_concurrent_producers() {
    Recorder r;std::vector<Record> storage(12000),out(12000);std::mutex lock;
    assert(r.initialize(storage.data(),storage.size())==Ok&&r.start(100,60000)==Ok);
    std::vector<std::thread> threads;
    for(unsigned t=0;t<4;++t)threads.emplace_back([&,t]{
        for(unsigned i=0;i<3000;++i){std::lock_guard<std::mutex> held(lock);
            assert(r.append(101+i,7,uint64_t(t)*3000+i));}
    });
    for(auto &t:threads)t.join();r.stop(4000);
    uint32_t n;assert(r.read(0,out.data(),out.size(),&n)==Ok&&n==12000);
    std::vector<bool> seen(12000,false);
    for(const auto &row:out){assert(row.identity<seen.size()&&!seen[row.identity]);seen[row.identity]=true;}
    assert(r.metadata().dropped==0);
}
int main(){boundaries();overflow_export_and_retry();serialized_concurrent_producers();
    puts("trace: window boundaries, exact overflow, retry, contiguous export and serialized12000events passed");}
'''

REJECTION = r'''
#include "NabuFrameTraceEvents.h"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
using IOReturn=uint32_t;
constexpr IOReturn kIOReturnBadArgument=0xe00002c2, kIOReturnUnsupported=0xe00002c7;
constexpr unsigned SwapId=0x50, Surface=0x54, Source=0x64, Enabled=0xa4, Destination=0xc4, LayersSet=0x104, Cleared=0x108;
struct Trace { uint64_t time,identity,a,b,c; uint32_t event; };
std::vector<Trace> events;unsigned logs;
uint64_t nowUs(){return 500;}
uint32_t word(const uint8_t *p,unsigned offset){uint32_t v;memcpy(&v,p+offset,4);return v;}
void traceFrame(uint64_t t,uint32_t e,uint64_t id,uint64_t a,uint64_t b,uint64_t c){events.push_back({t,id,a,b,c,e});}
void IOLog(const char *,...){++logs;}
__REJECTION__
int main(){
    assert(rejectPresent(nullptr,1,NabuGpuTrace::ShortSwap)==kIOReturnBadArgument);
    assert(events.size()==1&&events[0].identity==0&&events[0].c==1&&logs==1);
    uint8_t swap[0x46c]{};
    auto put=[&](unsigned at,uint32_t value){memcpy(swap+at,&value,4);};
    put(SwapId,123);put(Cleared,0xa5);put(LayersSet,0x5a);
    for(unsigned i=0;i<4;++i){put(Surface+i*4,100+i);put(Enabled+i*4,400+i);}
    for(unsigned layer=0;layer<4;++layer)for(unsigned i=0;i<4;++i){
        put(Source+layer*16+i*4,200+layer*10+i);put(Destination+layer*16+i*4,300+layer*10+i);}
    for(uint32_t reason=1;reason<=4;++reason){
        events.clear();logs=0;
        for(unsigned i=0;i<120;++i)assert(rejectPresent(swap,sizeof(swap),reason)==kIOReturnUnsupported);
        assert(logs==12&&events.size()==1320);
        assert(events[0].event==NabuGpuTrace::PresentRejected&&events[0].identity==123&&events[0].a==reason);
        assert(events[1].a==(uint64_t(101)<<32|100)&&events[1].b==(uint64_t(103)<<32|102)&&events[1].c==0xa5);
        assert(events[2].a==(uint64_t(401)<<32|400)&&events[2].b==(uint64_t(403)<<32|402)&&events[2].c==0x5a);
        for(unsigned layer=0;layer<4;++layer){
            const auto &s=events[3+layer*2], &d=events[4+layer*2];
            assert(s.a==(uint64_t(201+layer*10)<<32|(200+layer*10))&&s.c==layer);
            assert(d.b==(uint64_t(303+layer*10)<<32|(302+layer*10))&&d.c==layer);
        }
        assert(events[1309].c==120);
    }
}
'''


def check_export_protocol():
    metadata = dict(schema_version=1, record_bytes=48, window=3, active=False,
                    status=0, count=2, capacity=8, dropped=0, start_us=100,
                    end_us=150, deadline_us=200, clock='mach_absolute_time_us')
    raw = WIRE.pack(110, 7, 1, 2, 3, 1, 3) + WIRE.pack(150, 8, 4, 5, 6, 2, 3)
    assert validate_export(metadata, raw, 3) == 2
    for bad in (raw[:-1], WIRE.pack(110, 7, 1, 2, 3, 1, 4) + raw[48:]):
        try: validate_export(metadata, bad, 3)
        except ValueError: pass
        else: raise AssertionError('Truncated or cross-window trace accepted')
    with tempfile.TemporaryDirectory() as folder:
        output = Path(folder); actions = []
        def request(fields):
            actions.append(fields['TraceCommand'])
            if fields['TraceCommand'] == 'Export':
                return {'result': metadata, 'afc_trace_path': '/trace.bin'}
            assert (output/'records.bin').read_bytes() == raw
            assert json.loads((output/'metadata.json').read_text()) == metadata
            assert fields == {'TraceCommand': 'Acknowledge', 'Window': 3, 'Count': 2}
            return {'result': {'acknowledged': True}}
        try: save_export(request, lambda _: raw[:-1], 3, output)
        except ValueError: pass
        else: raise AssertionError('Incomplete export accepted')
        assert actions == ['Export'] and not (output/'records.bin').exists()
        actions.clear()
        result = save_export(request, lambda _: raw, 3, output)
        assert result['complete_record_stream'] and actions == ['Export', 'Acknowledge']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); out = args.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    check_export_protocol()
    source = out / 'trace.cpp'; source.write_text(HARNESS)
    binary = out / 'trace'
    compile_command = ['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                       '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
                       '-I' + host_path(ROOT / 'patches/nabu-gpu'), host_path(source), '-o', host_path(binary)]
    for name, argv in [('compile', compile_command), ('run', [host_path(binary)])]:
        r = subprocess.run(host_command(argv), capture_output=True, timeout=120)
        (out / (name + '.log')).write_bytes(r.stdout + r.stderr)
        if r.returncode: raise RuntimeError((r.stdout + r.stderr).decode(errors='replace')[-6000:])
    rejection = out/'rejection.cpp'; rejection_binary = out/'rejection'
    production = (ROOT/'patches/nabu-display/NabuDpuDisplay.cpp').read_text()
    rejection.write_text(REJECTION.replace('__REJECTION__',body(production,'static IOReturn rejectPresent(')))
    command = [arg.replace(host_path(source),host_path(rejection)).replace(host_path(binary),host_path(rejection_binary))
               for arg in compile_command]
    for name, argv in [('rejection-compile',command), ('rejection-run',[host_path(rejection_binary)])]:
        r = subprocess.run(host_command(argv),capture_output=True,timeout=120)
        (out/(name+'.log')).write_bytes(r.stdout+r.stderr)
        if r.returncode: raise RuntimeError((r.stdout+r.stderr).decode(errors='replace')[-6000:])
    report = {'passed': True, 'scope': 'production portable recorder core; caller lock supplied by host mutex',
              'record_bytes': 48, 'concurrent_records': 12000, 'sanitizers': ['address', 'undefined'],
              'durable_export_ack_protocol_checked': True,
              'actual_display_rejection_reason_and_raw_fields_checked': True,
              'kernel_wrapper_exercised': False, 'hardware_timestamps_exercised': False,
              'device_executed': False}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n'); print(json.dumps(report))


if __name__ == '__main__':
    main()
