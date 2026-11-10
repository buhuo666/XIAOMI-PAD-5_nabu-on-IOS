#!/usr/bin/env python3
"""Check SSC controls against original Android packets and independent wire fixtures."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdio>
#include <fstream>
#include <string>
#include <vector>
#include "NabuSscCensus.h"
#include "NabuSscControl.h"
using Bytes=std::vector<uint8_t>;
using Status=NabuSsc::ControlStatus;
static Bytes unhex(const std::string &s){
    Bytes b;for(size_t i=0;i<s.size();i+=2)b.push_back(uint8_t(std::stoul(s.substr(i,2),nullptr,16)));return b;
}
struct IO {
    Bytes last;
    bool blocked=false;
    unsigned sends=0;
    bool send_ssc(uint32_t node,uint32_t port,uint32_t from,const uint8_t *p,uint32_t n){
        assert(node==9&&port==12&&from==0x100); // Same Census connection; never 0x102.
        if(blocked)return false;
        ++sends;last.assign(p,p+n);return true;
    }
    void ssc_event(unsigned,NabuSsc::Suid,uint32_t,uint64_t,NabuSsc::Span){}
};
static unsigned tlv(const Bytes &bytes,unsigned type){
    for(unsigned at=7;at<bytes.size();at+=3+NabuSsc::u16(bytes.data()+at+1))
        if(bytes[at]==type)return at+3;
    assert(false);return 0;
}
static Bytes without_tlv(Bytes bytes,unsigned type){
    const unsigned at=tlv(bytes,type)-3,size=3+NabuSsc::u16(bytes.data()+at+1);
    bytes.erase(bytes.begin()+at,bytes.begin()+at+size);NabuSsc::put16(bytes.data()+5,bytes.size()-7);return bytes;
}
static void rate(uint64_t us){
    float independent=float(1000000.0L/static_cast<long double>(us));uint32_t bits;
    memcpy(&bits,&independent,4);assert(NabuSsc::interval_rate_bits(us)==bits);
}
int main(int argc,char **argv){
    assert(argc==3);
    assert(NabuSsc::interval_rate_bits(0)==0);
    unsigned rate_checks=0;
    for(uint64_t us=1;us<=100000;++us){rate(us);++rate_checks;}
    for(unsigned n=0;n<64;++n){
        uint64_t us=uint64_t(1)<<n;rate(us);++rate_checks;
        if(us>1){rate(us-1);++rate_checks;}
        if(us!=UINT64_MAX){rate(us+1);++rate_checks;}
    }
    uint64_t random=0xc24e26c9c68931d7ULL;
    for(unsigned n=0;n<10000;++n){random^=random<<13;random^=random>>7;random^=random<<17;rate(random);++rate_checks;}
    rate(UINT64_MAX);++rate_checks;
    static IO census_io;static NabuSsc::Census<IO> census(census_io);
    census.stream(nullptr,nullptr);census.start(9,12,100);census.tick(100);
    std::ifstream capture(argv[1]);assert(capture.good());std::string line;Bytes response,indication;
    while(std::getline(capture,line)){
        Bytes bytes=unhex(line);
        if(bytes[0]==2&&response.empty())response=bytes;
        if(bytes[0]==4&&indication.empty())indication=bytes;
        census.receive(9,12,0x100,bytes.data(),bytes.size());census.tick(100);
    }
    assert(census.stream_count==4&&census.result.has_client&&census.result.invalid==0);
    std::vector<Bytes> expected;std::ifstream fixtures(argv[2]);assert(fixtures.good());
    while(std::getline(fixtures,line))expected.push_back(unhex(line));
    assert(expected.size()==6);
    IO io;NabuSsc::ControlSession<IO> control(io);NabuSsc::ControlCompletion completion;
    assert(control.queue(0,0,20000,100)==Status::NotReady);
    assert(!control.bind(0,{},false));
    control.start(9,12,census.result.client);
    for(unsigned n=0;n<census.stream_count;++n){
        const auto &s=census.streams[n];assert(s.configured&&s.samples);
        assert(control.bind(s.type,s.suid,s.type==3));
    }
    assert(!control.settings(4)&&!control.bind(4,{},false));
    assert(control.queue(0,0,0,100)==Status::BadArgument);
    assert(control.queue(0,1,uint64_t(UINT32_MAX)+1,100)==Status::BadArgument);
    assert(control.queue(0,0,20000,100,0)==Status::BadArgument);
    assert(control.queue(0,9,20000,100)==Status::Unsupported);
    assert(control.queue(3,0,20000,100)==Status::Unsupported);
    auto ack=[&](uint64_t now){
        Bytes bytes=response;NabuSsc::put16(bytes.data()+1,NabuSsc::u16(io.last.data()+1));
        assert(control.receive(9,12,0x100,bytes.data(),bytes.size(),now));return bytes;
    };
    auto take=[&](Status status){
        assert(control.status()==status&&control.take_result(completion));
        assert(completion.status==status&&control.status()==Status::Idle);
        assert(!control.take_result(completion));
    };
    auto send=[&](unsigned kind,unsigned field,uint64_t us,unsigned fixture){
        const auto before=*control.settings(kind);
        assert(control.queue(kind,field,us,100)==Status::Queued);
        assert(control.queue(kind,field,us,100)==Status::Busy);
        assert(!control.take_result(completion));
        io.blocked=true;unsigned sent=io.sends;control.tick(100);
        assert(control.status()==Status::Queued&&io.sends==sent);
        io.blocked=false;control.tick(101);assert(control.status()==Status::Waiting&&io.sends==sent+1);
        for(unsigned n=102;n<110;++n)control.tick(n);
        assert(io.sends==sent+1); // No retransmit or additional subscription.
        assert(control.settings(kind)->report_interval_us==before.report_interval_us);
        assert(control.settings(kind)->batch_interval_us==before.batch_interval_us);
        Bytes wanted=expected[fixture];NabuSsc::put16(wanted.data()+1,NabuSsc::u16(io.last.data()+1));
        assert(io.last==wanted); // Independent Python encoding from original proto and captured SUID.
        Bytes bytes=ack(110);assert(control.status()==Status::Accepted);
        assert(control.queue(kind,field,us,110)==Status::Busy); // Owner must consume completion first.
        control.receive(9,12,0x100,bytes.data(),bytes.size(),110);
        take(Status::Accepted);assert(completion.sent&&completion.kind==kind&&completion.control==field&&completion.microseconds==us);
    };
    send(0,0,20000,0);assert(control.settings(0)->report_interval_us==20000);
    send(0,1,250000,1);assert(control.settings(0)->report_interval_us==20000&&control.settings(0)->batch_interval_us==250000);
    send(0,0,33333,2);assert(control.settings(0)->report_interval_us==33333&&control.settings(0)->batch_interval_us==250000);
    send(0,1,0,3);assert(control.settings(0)->batch_interval_us==0);
    send(3,1,100000,4);assert(control.settings(3)->report_interval_us==0&&control.settings(3)->batch_interval_us==100000);
    send(2,0,UINT64_MAX,5);assert(control.settings(2)->report_interval_us==UINT64_MAX);
    assert(control.bind(0,census.streams[0].suid,false));assert(control.settings(0)->report_interval_us==33333);
    // Low Census transactions and reports bypass the control demultiplexer.
    assert(!control.receive(9,12,0x100,response.data(),response.size(),100));
    assert(!control.receive(9,12,0x100,indication.data(),indication.size(),100));
    assert(control.queue(0,0,40000,100)==Status::Queued);
    Bytes bytes=response;NabuSsc::put16(bytes.data()+1,0x8006);
    control.receive(9,12,0x100,bytes.data(),bytes.size(),101);assert(control.status()==Status::Queued);
    control.tick(101);
    control.receive(8,12,0x100,bytes.data(),bytes.size(),102);
    control.receive(9,13,0x100,bytes.data(),bytes.size(),102);
    control.receive(9,12,0x102,bytes.data(),bytes.size(),102);
    Bytes foreign=bytes;foreign[tlv(foreign,0x10)]^=1;
    control.receive(9,12,0x100,foreign.data(),foreign.size(),102);
    Bytes unknown=bytes;NabuSsc::put16(unknown.data()+1,0x8123);
    control.receive(9,12,0x100,unknown.data(),unknown.size(),102);
    assert(control.status()==Status::Waiting&&control.foreign==4&&control.settings(0)->report_interval_us==33333);
    ack(103);take(Status::Accepted);
    // A legal QMI error may omit the success-only client/response TLVs.
    assert(control.queue(0,0,20000,100)==Status::Queued);control.tick(100);
    Bytes error{2,0,0,0x20,0,7,0,2,4,0,1,0,0x5e,0};NabuSsc::put16(error.data()+1,NabuSsc::u16(io.last.data()+1));
    control.receive(9,12,0x100,error.data(),error.size(),101);take(Status::Rejected);
    assert(completion.qmi_result==1&&completion.qmi_error==0x5e&&control.settings(0)->report_interval_us==40000);
    // Success without SSC response or client ID is never treated as acceptance.
    assert(control.queue(0,0,20000,100)==Status::Queued);control.tick(100);
    error[10]=0;error[12]=0;NabuSsc::put16(error.data()+1,NabuSsc::u16(io.last.data()+1));
    control.receive(9,12,0x100,error.data(),error.size(),101);take(Status::InvalidResponse);
    assert(control.settings(0)->report_interval_us==40000);
    for(unsigned missing:{0x10u,0x11u}){
        assert(control.queue(0,0,20000,100)==Status::Queued);control.tick(100);
        Bytes incomplete=without_tlv(response,missing);NabuSsc::put16(incomplete.data()+1,NabuSsc::u16(io.last.data()+1));
        control.receive(9,12,0x100,incomplete.data(),incomplete.size(),101);take(Status::InvalidResponse);
        assert(control.settings(0)->report_interval_us==40000);
    }
    assert(control.queue(0,0,20000,100)==Status::Queued);control.tick(100);
    Bytes rejected=response;NabuSsc::put16(rejected.data()+1,NabuSsc::u16(io.last.data()+1));rejected[tlv(rejected,0x11)]=2;
    control.receive(9,12,0x100,rejected.data(),rejected.size(),101);take(Status::Rejected);assert(completion.ssc_response==2);
    // The deadline covers backpressure AND a sent request. A late ack is not success.
    io.blocked=true;unsigned count=io.sends;
    assert(control.queue(0,0,20000,100,5)==Status::Queued);control.tick(104);control.tick(105);
    take(Status::TimedOut);assert(!completion.sent&&io.sends==count);io.blocked=false;
    assert(control.queue(0,0,20000,100,5)==Status::Queued);control.tick(100);ack(105);
    take(Status::TimedOut);assert(completion.sent&&control.settings(0)->report_interval_us==40000);
    assert(control.queue(0,0,20000,100)==Status::Queued);control.tick(100);control.unbind(0);
    ack(101);take(Status::Cancelled);assert(!control.settings(0));
    assert(control.queue(0,0,20000,100)==Status::NotReady);
    assert(control.queue(1,0,20000,100)==Status::Queued);control.stop();take(Status::Cancelled);
    for(unsigned k=0;k<4;++k)assert(!control.settings(k));
    // Exercise the reserved transaction rollover with one fixed pending slot.
    control.start(9,12,census.result.client);assert(control.bind(0,census.streams[0].suid,false));
    bool wrapped=false;uint16_t previous=0;
    for(unsigned n=0;n<0x8001;++n){
        assert(control.queue(0,0,40000,100)==Status::Queued);control.tick(100);
        uint16_t txn=NabuSsc::u16(io.last.data()+1);assert(txn>=0x8000);
        if(previous==0xffff){assert(txn==0x8000);wrapped=true;}previous=txn;
        ack(101);take(Status::Accepted);
    }
    assert(wrapped);
    printf("PASS: %u interval conversions, original Android discovery/replies, six independent wire fixtures, preserved controls, same client, one pending slot, rejection, deadline, cancellation and transaction rollover\n",rate_checks);
}
'''

KERNEL_HARNESS = r'''
#include <IOKit/IOLib.h>
#include "NabuSscControl.h"
extern "C" bool nabu_control_test_send(uint32_t,uint32_t,uint32_t,const uint8_t *,uint32_t);
struct KernelIO {
    bool send_ssc(uint32_t node,uint32_t port,uint32_t local,const uint8_t *data,uint32_t size){
        return nabu_control_test_send(node,port,local,data,size);
    }
};
template class NabuSsc::ControlSession<KernelIO>;
extern "C" uint32_t nabu_control_test_rate(uint64_t us){return NabuSsc::interval_rate_bits(us);}
'''


def varint(value):
    out = bytearray()
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    return bytes(out) + bytes([value])


def message(field, payload):
    return varint((field << 3) | 2) + varint(len(payload)) + payload


def expected_request(suid, on_change, report, batch):
    number = int(suid, 16)
    uid = b'\x09' + struct.pack('<Q', number & ((1 << 64) - 1)) + b'\x11' + struct.pack('<Q', number >> 64)
    request = message(1, b'\x08' + varint(batch))
    if not on_change:
        request += message(2, b'\x0d' + struct.pack('<f', 1000000 / report))
    body = message(1, uid) + b'\x15' + struct.pack('<I', 514 if on_change else 513)
    body += message(3, b'\x08\x01\x10\x00') + message(4, request)
    tlvs = b'\x01' + struct.pack('<HH', len(body) + 2, len(body)) + body + b'\x10\x01\x00\x01'
    return b'\x00\x00\x80\x20\x00' + struct.pack('<H', len(tlvs)) + tlvs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--kernel-compile-report', type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in args.capture.read_text().splitlines()]
    received = [row['hex'] for row in rows if row['kind'] == 'rx' and row['node'] == 9 and row['port'] == 12]
    suids = {row['type']: row['suid'] for row in rows if row['kind'] == 'attributes'}
    fixtures = [expected_request(suids['accel'], False, 20000, 0),
                expected_request(suids['accel'], False, 20000, 250000),
                expected_request(suids['accel'], False, 33333, 250000),
                expected_request(suids['accel'], False, 33333, 0),
                expected_request(suids['ambient_light'], True, 0, 100000),
                expected_request(suids['mag'], False, (1 << 64) - 1, 0)]
    replay = output / 'android-replies.txt'
    replay.write_text('\n'.join(received) + '\n', newline='\n')
    fixture = output / 'expected-controls.txt'
    fixture.write_text('\n'.join(packet.hex() for packet in fixtures) + '\n', newline='\n')
    source = output / 'ssc-control.cpp'
    source.write_text(HARNESS, newline='\n')
    binary = output / 'ssc-control'
    command = host_command(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g',
                            '-I' + host_path(ROOT / 'patches/nabu-sensors'), host_path(source), '-o', host_path(binary)])
    compiled = subprocess.run(command, capture_output=True)
    (output / 'compile.log').write_bytes(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        raise SystemExit(compiled.stderr.decode(errors='replace'))
    result = subprocess.run(host_command([host_path(binary), host_path(replay), host_path(fixture)]), capture_output=True, timeout=30)
    (output / 'run.log').write_bytes(result.stdout + result.stderr)
    report = dict(passed=result.returncode == 0, capture=str(args.capture), captured_replies=len(received),
                  independently_encoded_controls=len(fixtures), command=command,
                  stdout=result.stdout.decode(errors='replace'), device_execution=False)
    if result.returncode:
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        raise SystemExit(result.stderr.decode(errors='replace'))
    if args.kernel_compile_report:
        saved = json.loads(args.kernel_compile_report.read_text())['command']
        kernel_source = output / 'ssc-control-kernel.cpp'
        kernel_source.write_text(KERNEL_HARNESS, newline='\n')
        obj = output / 'ssc-control-kernel.o'
        kernel_command = saved[:saved.index('-c')] + ['-I' + host_path(ROOT / 'patches/nabu-sensors'),
                                                      '-c', host_path(kernel_source), '-o', host_path(obj)]
        kernel = subprocess.run(host_command(kernel_command), capture_output=True)
        (output / 'kernel-compile.log').write_bytes(kernel.stdout + kernel.stderr)
        report['kernel_compiled'] = kernel.returncode == 0
        if kernel.returncode:
            raise SystemExit(kernel.stderr.decode(errors='replace'))
        assembly = subprocess.run(host_command(['llvm-objdump-18', '-d', host_path(obj)]), capture_output=True, check=True).stdout.decode()
        (output / 'ssc-control-kernel.asm').write_text(assembly)
        fp = [line for line in assembly.splitlines() if '\t' in line and re.search(r'\b[vsdq][0-9]+\b', line.split('\t')[-1])]
        report['kernel_floating_point_instructions'] = fp
        report['kernel_largest_stack_frame'] = max(int(row.rsplit('\t', 2)[1]) for row in obj.with_suffix('.su').read_text().splitlines())
        report['kernel_undefined_symbols'] = subprocess.run(host_command(['llvm-nm-18', '--undefined-only', host_path(obj)]),
                                                          capture_output=True, check=True).stdout.decode().splitlines()
        report['passed'] &= not fp
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(report['stdout'])
    print(json.dumps({key: value for key, value in report.items() if key.startswith('kernel_')}, indent=2))
    if not report['passed']:
        raise SystemExit('Kernel general-register check failed')


if __name__ == '__main__':
    main()
