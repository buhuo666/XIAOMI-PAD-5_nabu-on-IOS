#!/usr/bin/env python3
"""Exercise the production Bluetooth byte queue with fragmented HCI/ACL traffic."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdio>
#include <deque>
#include <vector>
#include "NabuBluetoothTransport.h"

static uint32_t word(const uint8_t *bytes, unsigned n) {
    uint32_t value=0; for(unsigned i=0;i<n;++i)value|=(uint32_t)bytes[i]<<(i*8); return value;
}

int main() {
    NabuBluetoothRx queue{};
    // One event followed by an ACL packet longer than the old 256-byte HCI buffer.
    std::vector<uint8_t> stream{4,0x0e,4,1,3,0x0c,0,2,0x01,0x20,0x01,0x10};
    for(unsigned i=0;i<4097;++i)stream.push_back((i*13+7)&255);
    for(unsigned at=0;at<stream.size();) {
        unsigned n=1+at%4; if(n>stream.size()-at)n=stream.size()-at;
        assert(queue.push_word(word(stream.data()+at,n),n)); at+=n;
    }
    std::vector<uint8_t> recovered;
    const unsigned reads[]={1,2,7,31,512};
    for(unsigned i=0;queue.count;++i) {
        uint8_t out[512];unsigned n=queue.peek(out,reads[i%5]);
        unsigned before=queue.count;assert(queue.peek(out,n)==n&&queue.count==before);
        recovered.insert(recovered.end(),out,out+n);queue.consume(n);
    }
    assert(recovered==stream);

    // Fill exactly, reject a word without losing queued bytes, then wrap around.
    for(unsigned i=0;i<NabuBluetoothRx::capacity/4;++i)assert(queue.push_word(i,4));
    unsigned head=queue.head;assert(!queue.push_word(0xdeadbeef,4));
    assert(queue.count==NabuBluetoothRx::capacity&&queue.head==head);
    uint8_t out[17];assert(queue.peek(out,4)==4&&word(out,4)==0);queue.consume(4);
    assert(queue.push_word(0xdeadbeef,4));
    for(unsigned i=1;i<NabuBluetoothRx::capacity/4;++i) {
        assert(queue.peek(out,4)==4&&word(out,4)==i);queue.consume(4);
    }
    assert(queue.peek(out,4)==4&&word(out,4)==0xdeadbeef);queue.consume(4);

    // Compare mixed producer/consumer fragmentation through many ring wraps.
    std::deque<uint8_t> oracle; uint32_t seed=0x91b71;
    for(unsigned i=0;i<350000;++i) {
        seed=1664525*seed+1013904223;
        if((seed&3)!=0&&queue.count<=NabuBluetoothRx::capacity-4) {
            unsigned n=1+((seed>>8)&3);assert(queue.push_word(seed,n));
            for(unsigned k=0;k<n;++k)oracle.push_back(seed>>(8*k));
        } else {
            unsigned n=queue.peek(out,1+((seed>>16)%17));
            assert(n==((oracle.size()<1+((seed>>16)%17))?oracle.size():1+((seed>>16)%17)));
            // Model a short copy-out: only successfully copied bytes are consumed.
            unsigned moved=n?1+(seed%n):0;
            for(unsigned k=0;k<moved;++k){assert(out[k]==oracle.front());oracle.pop_front();}
            queue.consume(moved);
        }
        assert(queue.count==oracle.size());
    }
    auto generation=queue.generation;queue.clear();
    assert(!queue.count&&queue.generation!=generation);
    puts("Bluetooth RX: fragmented event/4097-byte ACL, 1/2/7/31-byte reads, capacity rejection, wraps and short-copy retention passed");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / 'bluetooth-stream.cpp'
    binary = args.output / 'bluetooth-stream-test'
    source.write_text(HARNESS)
    subprocess.run(host_command(['clang++-18', '-std=c++17', '-fsanitize=address,undefined',
                   '-fno-omit-frame-pointer', '-I'+host_path(ROOT/'patches/nabu-wireless'),
                   host_path(source), '-o', host_path(binary)]), check=True)
    result = subprocess.run(host_command([host_path(binary)]), capture_output=True)
    (args.output/'test.log').write_bytes(result.stdout)
    (args.output/'test.stderr').write_bytes(result.stderr)
    result.check_returncode()
    report = {'production_rx_queue_tested': True, 'sanitizers': ['address', 'undefined'],
              'hardware_tested': False, 'result': result.stdout.decode().strip()}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
