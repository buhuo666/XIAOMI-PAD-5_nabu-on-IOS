#!/usr/bin/env python3
"""Replay A640 stock OPP tables and HFI startup using production power code."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / "patches/nabu-gpu"
A640 = ROOT / "src/nabu/gpu/a640"

TYPES = r"""
#pragma once
#include <cstdint>
using IOReturn = uint32_t;
enum : IOReturn {
    kIOReturnSuccess, kIOReturnBadArgument, kIOReturnBusy, kIOReturnIOError,
    kIOReturnTimeout, kIOReturnBadMedia, kIOReturnUnsupported,
    kIOReturnNotFound, kIOReturnNoSpace, kIOReturnNoMemory,
    kIOReturnNotReady
};
"""

HARNESS = r"""
#include "NativeAdrenoA6xxPower.h"
#include "NativeAdrenoA6xxGmu.h"
#include <kern/locks.h>
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <map>
#include <tuple>
#include <vector>

extern "C" {
lck_mtx_t hakios_aop_mailbox_lock;
lck_mtx_t hakios_rsc_lock;
}

struct Reference {
    uint32_t khz, arc, ddr, vote, sh0, mc0;
};
static constexpr Reference references[] = {
    {257000, 64, 1799000, 0x00400203, 899, 1799},
    {499200, 224, 6215000, 0x00e00406, 3107, 6215},
    {585000, 256, 7211000, 0x01000407, 3605, 7211},
    {675000, 320, 8363000, 0x01400508, 4181, 8363},
};
constexpr uint32_t commit = 1u << 30, valid = 1u << 29;
constexpr uint32_t queueOffset = 224, queueWords = 1024;
static uint32_t gmuOffset(uint32_t reg) { return reg * 4 - 0x6a000; }

struct Request { uint32_t id, header; std::vector<uint32_t> payload; };
struct alignas(4096) Buffer { uint8_t bytes[0x5000]{}; };
struct Mock {
    std::vector<uint8_t> database = std::vector<uint8_t>(0x20000);
    std::map<std::pair<uint32_t, uint32_t>, uint32_t> registers;
    std::vector<std::tuple<uint32_t, uint32_t, uint32_t>> writes;
    std::vector<Request> requests;
    std::array<Buffer, 5> buffers;
    uint8_t firmware[20]{};
    uint64_t delayedUs = 0;
    uint32_t reads = 0, wakes = 0, failureId = 0;
    bool missingReply = false, wrongReply = false;

    void put16(uint32_t offset, uint16_t value) {
        database.at(offset) = uint8_t(value);
        database.at(offset + 1) = uint8_t(value >> 8);
    }
    void put32(uint32_t offset, uint32_t value) {
        for (unsigned byte = 0; byte < 4; ++byte)
            database.at(offset + byte) = uint8_t(value >> (byte * 8));
    }
    static void word(uint8_t *at, uint32_t value) {
        for (unsigned byte = 0; byte < 4; ++byte) at[byte] = uint8_t(value >> (byte * 8));
    }
    void set(uint32_t domain, uint32_t offset, uint32_t value) {
        registers[{domain, offset}] = value;
    }
    void setGmu(uint32_t reg, uint32_t value) {
        set(NativeAdrenoA6xxGmuRegisters, gmuOffset(reg), value);
    }
    void record(uint32_t offset, const char *name, uint32_t address,
        uint32_t auxiliary, uint32_t length) {
        for (unsigned byte = 0; name[byte]; ++byte) database.at(offset + byte) = uint8_t(name[byte]);
        put32(offset + 16, address);
        put32(offset + 20, (auxiliary << 16) | length);
    }
    void arc(uint32_t offset, const std::vector<uint16_t> &levels) {
        for (unsigned index = 0; index < levels.size(); ++index)
            put16(offset + index * 2, levels[index]);
    }
    void bcm(uint32_t offset, uint32_t unit, uint16_t width, uint8_t vcd) {
        put32(offset, unit);
        put16(offset + 4, width);
        database.at(offset + 6) = vcd;
    }
    Mock() {
        // A synthetic command-db preserves the unit's resource addresses/VCDs.
        // Different ARC arrays check secondary dependencies and retained floors.
        put32(0, 1); put32(4, 0x0c0330db);
        put32(8, (0x100u << 16) | 3); put32(12, (4u << 16) | 0x400);
        put32(24, (0x800u << 16) | 5); put32(28, (6u << 16) | 0xa00);
        const char *arcNames[] = {"gfx.lvl", "mx.lvl", "cx.lvl", "xo.lvl"};
        const uint32_t arcAddresses[] = {0x30050, 0x30010, 0x30000, 0x30090};
        for (unsigned index = 0; index < 4; ++index)
            record(144 + 0x100 + index * 24, arcNames[index],
                arcAddresses[index], index * 32, 32);
        arc(144 + 0x400, {0, 16, 48, 64, 128, 192, 224, 256, 320, 384});
        arc(144 + 0x420, {0, 16, 64, 192, 256, 384});
        arc(144 + 0x440, {0, 16, 64, 128, 192, 256, 384});
        arc(144 + 0x460, {0, 16, 48, 64});
        const char *bcmNames[] = {"SH0", "MC0", "ACV", "SH2", "SN15", "SN3"};
        const uint32_t bcmAddresses[] = {0x5003c, 0x50000, 0x5000c, 0x50034, 0x5007c, 0x5004c};
        const uint8_t vcd[] = {1, 0, 11, 1, 3, 3};
        for (unsigned index = 0; index < 6; ++index) {
            record(144 + 0x800 + index * 24, bcmNames[index],
                bcmAddresses[index], index * 8, 8);
            bcm(144 + 0xa00 + index * 8, index < 2 ? 1000000u : 1000u,
                index == 2 ? 0 : (index == 1 ? 4 : 8), vcd[index]);
        }
        set(NativeAdrenoA6xxAop, 0, 0x4d41494c);
        set(NativeAdrenoA6xxAop, 4, 1);
        set(NativeAdrenoA6xxAop, 12, 0xffff);
        set(NativeAdrenoA6xxAop, 20, 0xffff);
        set(NativeAdrenoA6xxAop, 40, 0xffff);
        set(NativeAdrenoA6xxAop, 48, 0xffff);
        set(NativeAdrenoA6xxAop, 52, 0x100);
        set(NativeAdrenoA6xxAop, 56, 0x100);
        set(NativeAdrenoA6xxRpmh, 0xc, (2u << 12) | (4u << 27));
        set(NativeAdrenoA6xxRpmh, 0xd18, 1);
        set(NativeAdrenoA6xxRpmh, 0xd04, 1);
        for (unsigned index = 0; index < 4; ++index)
            set(NativeAdrenoA6xxRpmh, 0xd3c + index * 20, 0x10100);
        set(NativeAdrenoA6xxGcc, 0, 1u << 31);
        set(NativeAdrenoA6xxGpuCc, 0x1540, 1u << 31);
        set(NativeAdrenoA6xxGpuCc, 0x100c, 1u << 31);
        setGmu(0x1d3f8, 0x20010004);
        setGmu(0x1d3fc, 0x20000000);
        setGmu(0x1f981, 0x20000000);
        word(firmware + 4, 4);
        word(firmware + 16, 0x6401cafe);
    }
    void respond() {
        auto *shared = reinterpret_cast<uint32_t *>(buffers[4].bytes);
        uint32_t *command = shared + 6;
        uint32_t *data = shared + queueOffset / 4;
        const uint32_t at = command[10], header = data[at];
        const uint32_t count = (header >> 8) & 0xff;
        assert(count > 0 && count <= 160);
        Request request{header & 0xff, header, {}};
        for (unsigned index = 1; index < count; ++index)
            request.payload.push_back(data[(at + index) & (queueWords - 1)]);
        requests.push_back(request);
        command[10] = (at + ((count + 3) & ~3u)) & (queueWords - 1);
        assert(command[10] == command[11]);
        if (request.id == failureId && missingReply) return;
        uint32_t *response = shared + 6 + 12;
        uint32_t *reply = shared + queueOffset / 4 + queueWords;
        const uint32_t write = response[11];
        const uint32_t replyWords = request.id == 1 ? 4 : 3;
        reply[write] = (header & 0xfff000ff) | (1u << 16) | (replyWords << 8);
        reply[(write + 1) & (queueWords - 1)] =
            request.id == failureId && wrongReply ? header ^ (1u << 20) : header;
        reply[(write + 2) & (queueWords - 1)] =
            request.id == failureId && !wrongReply ? 7 : 0;
        if (replyWords == 4) reply[(write + 3) & (queueWords - 1)] = 0x20000000;
        response[11] = (write + 4) & (queueWords - 1);
        setGmu(0x1f992, 2);
    }
    static int read(void *cookie, uint32_t domain, uint32_t offset, uint32_t *out) {
        auto &mock = *static_cast<Mock *>(cookie);
        ++mock.reads;
        if (domain == NativeAdrenoA6xxCommandDb) {
            assert(!(offset & 3) && offset + 4 <= mock.database.size());
            *out = 0;
            for (unsigned byte = 0; byte < 4; ++byte)
                *out |= uint32_t(mock.database[offset + byte]) << (8 * byte);
        } else {
            *out = mock.registers[{domain, offset}];
        }
        return 0;
    }
    static int write(void *cookie, uint32_t domain, uint32_t offset, uint32_t value) {
        auto &mock = *static_cast<Mock *>(cookie);
        assert(domain != NativeAdrenoA6xxCommandDb);
        mock.writes.emplace_back(domain, offset, value);
        mock.set(domain, offset, value);
        if (domain == NativeAdrenoA6xxAopDoorbell) mock.set(NativeAdrenoA6xxAop, 0x100, 0);
        if (domain == NativeAdrenoA6xxGpuCc && offset == 0x1120)
            mock.set(domain, offset, value & ~1u);
        if (domain == NativeAdrenoA6xxGmuRegisters) {
            if (offset == gmuOffset(0x1f800) && value == 0) mock.setGmu(0x1f81c, 0xbabeface);
            if (offset == gmuOffset(0x1f986) && value == 1) mock.setGmu(0x1f980, 1);
            if (offset == gmuOffset(0x1f991)) {
                auto key = std::make_pair(domain, gmuOffset(0x1f992));
                mock.registers[key] &= ~value;
            }
            if (offset == gmuOffset(0x1f994) && value == 1) mock.respond();
            if (offset == gmuOffset(0x1f994) && value == (1u << 30)) {
                assert(!mock.requests.empty() && mock.requests.back().id == 30);
                auto *shared = reinterpret_cast<uint32_t *>(mock.buffers[4].bytes);
                assert(shared[6 + 12 + 10] == shared[6 + 12 + 11]);
                assert(!mock.failureId);
                ++mock.wakes;
                mock.setGmu(0x1f992, 1u << 31);
            }
        }
        return 0;
    }
    static void delay(void *cookie, uint32_t us) {
        static_cast<Mock *>(cookie)->delayedUs += us;
    }
    NativeAdrenoA6xxIo io() { return {this, read, write, delay}; }
    NativeAdrenoA6xxGmuConfig config(const NativeAdrenoA6xxTables &tables) {
        NativeAdrenoA6xxGmuConfig config{};
        config.io = io(); config.firmware = firmware; config.firmwareBytes = sizeof(firmware);
        config.tables = &tables; config.chipId = 0x06040001;
        for (unsigned index = 0; index < 5; ++index)
            config.buffers[index] = {buffers[index].bytes, 0x10000000u + index * 0x10000u,
                index == 4 ? 0x5000u : 0x1000u};
        return config;
    }
};

static void table(const NativeAdrenoA6xxTables &tables, const Reference &reference) {
    const uint32_t *perf = tables.performance, *bw = tables.bandwidth;
    assert(perf[0] == 2 && perf[1] == 2 && perf[2] == 0 &&
        perf[3] == 0xffffffff && perf[4] == 0);
    assert(perf[5] == reference.vote && perf[6] == 0xffffffff && perf[7] == reference.khz);
    assert(perf[50] == 0 && perf[51] == 0 && perf[52] == 0x00400202 && perf[53] == 200000);
    for (unsigned index = 8; index < 50; ++index) assert(perf[index] == 0);
    for (unsigned index = 54; index < 58; ++index) assert(perf[index] == 0);
    assert(tables.gfxIndex == (reference.vote & 0xff));
    assert(tables.cxIndex == 6 && tables.mxIndex == 5);
    assert(tables.gfxAddress == 0x30050 && tables.mxAddress == 0x30010 &&
        tables.cxAddress == 0x30000 && tables.xoAddress == 0x30090);
    assert(bw[0] == 2 && bw[1] == 3 && bw[2] == 3 && bw[3] == 5 && bw[4] == 7);
    assert(bw[5] == 0x50034 && bw[6] == 0x5007c && bw[7] == 0x5004c);
    assert(bw[11] == commit && bw[12] == 0 && bw[13] == commit);
    assert(bw[17] == (commit | valid | 100) && bw[18] == (valid | 100) &&
        bw[19] == (commit | valid | 100));
    assert(bw[23] == 0x50000 && bw[24] == 0x5003c && bw[25] == 0x5000c);
    assert(bw[31] == commit && bw[32] == commit && bw[33] == commit);
    assert(bw[39] == (commit | valid | reference.mc0));
    assert(bw[40] == (commit | valid | reference.sh0));
    assert(bw[41] == (commit | valid | 8));
    for (unsigned index = 47; index < 159; ++index) assert(bw[index] == 0);
}

static NativeAdrenoA6xxTables power(Mock &mock, const Reference &reference, bool defaultOpp = false) {
    NativeAdrenoA6xxPower power;
    const IOReturn status = defaultOpp ? power.enableCx(mock.io(), 0xc, 1) :
        power.enableCx(mock.io(), 0xc, 1, reference.khz);
    assert(status == kIOReturnSuccess && power.report().phase == NativeAdrenoA6xxPower::CxReady);
    const NativeAdrenoA6xxTables result = power.tables();
    table(result, reference);
    const uint32_t floor[] = {5, 6, reference.vote & 0xff, 3};
    for (unsigned index = 0; index < 4; ++index)
        assert(mock.registers[std::make_pair(uint32_t(NativeAdrenoA6xxRpmh), 0xd38 + index * 20)] == floor[index]);
    assert(power.enableGx() == kIOReturnSuccess);
    return result;
}

static void startup(const NativeAdrenoA6xxTables &tables, uint32_t failureId = 0,
    bool missing = false, bool wrong = false) {
    Mock mock;
    mock.failureId = failureId; mock.missingReply = missing; mock.wrongReply = wrong;
    NativeAdrenoA6xxGmu gmu;
    const IOReturn status = gmu.start(mock.config(tables));
    if (!failureId) {
        assert(status == kIOReturnSuccess && gmu.running() && mock.wakes == 1);
        const uint32_t order[] = {1, 4, 3, 11, 14, 30, 10};
        assert(mock.requests.size() == 7 && gmu.report().acknowledged == 7);
        for (unsigned index = 0; index < 7; ++index) assert(mock.requests[index].id == order[index]);
        assert(mock.requests[1].payload == std::vector<uint32_t>(tables.performance, tables.performance + 58));
        assert(mock.requests[2].payload == std::vector<uint32_t>(tables.bandwidth, tables.bandwidth + 159));
        assert(mock.requests[5].payload == std::vector<uint32_t>({1, 1, 1}));
        assert(gmu.poll() == kIOReturnSuccess);
        assert(gmu.stop() == kIOReturnSuccess && !gmu.running());
    } else {
        assert(status == ((missing || wrong) ? kIOReturnTimeout : kIOReturnIOError));
        assert(!gmu.running() && !mock.wakes && mock.requests.back().id == failureId);
        if (missing || wrong) assert(mock.delayedUs >= 100000);
        else assert(gmu.report().hfiError == 7);
        assert(gmu.stop() == kIOReturnSuccess && !gmu.running());
    }
}

int main() {
    unsigned suites = 0;
    NativeAdrenoA6xxTables high{};
    for (const Reference &reference : references) {
        NativeAdrenoA6xxOpp selected{};
        assert(nativeAdrenoA640Opp(reference.khz, &selected) &&
            selected.gpuKhz == reference.khz && selected.arcLevel == reference.arc &&
            selected.ddrKbps == reference.ddr);
        Mock mock;
        auto tables = power(mock, reference);
        startup(tables);
        if (reference.khz == 675000) high = tables;
        ++suites;
    }
    {
        Mock mock;
        auto tables = power(mock, references[3], true);
        assert(!std::memcmp(tables.performance, high.performance, sizeof(high.performance)));
        assert(!std::memcmp(tables.bandwidth, high.bandwidth, sizeof(high.bandwidth)));
        ++suites;
    }
    {
        Mock mock;
        NativeAdrenoA6xxPower power;
        assert(power.enableCx(mock.io(), 0xc, 1, 700000) == kIOReturnBadArgument);
        assert(mock.writes.empty() && mock.reads == 0);
        auto invalid = high; invalid.performance[7] = 700000;
        NativeAdrenoA6xxGmu gmu;
        assert(gmu.start(mock.config(invalid)) == kIOReturnBadArgument);
        assert(mock.writes.empty() && mock.reads == 0);
        ++suites;
    }
    for (uint32_t failure : {4u, 3u, 30u}) {
        startup(high, failure);
        startup(high, failure, true);
        suites += 2;
    }
    startup(high, 30, false, true); ++suites;
    std::printf("A640 OPP: %u suites passed; default 675MHz, ARC/DDR tables, retained floors, and real HFI ACK/rejection/timeout path\n", suites);
}
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    include = output / "include"
    (include / "IOKit").mkdir(parents=True, exist_ok=True)
    (include / "kern").mkdir(exist_ok=True)
    (include / "IOKit/IOTypes.h").write_text(TYPES, encoding="utf-8")
    (include / "IOKit/IOLib.h").write_text(
        "#pragma once\n#include <IOKit/IOTypes.h>\n"
        "template<class... Args> inline void IOLog(const char*, Args...) {}\n",
        encoding="utf-8")
    (include / "kern/locks.h").write_text(
        "#pragma once\n#include <mutex>\nstruct lck_mtx_t {std::mutex value;};\n"
        "inline void lck_mtx_lock(lck_mtx_t *lock) {lock->value.lock();}\n"
        "inline void lck_mtx_unlock(lck_mtx_t *lock) {lock->value.unlock();}\n",
        encoding="utf-8")
    shutil.copyfile(GPU / "NativeAdrenoA6xxPower.h", include / "NativeAdrenoA6xxPower.h")
    shutil.copyfile(A640 / "NativeAdrenoA6xxGmu.h", include / "NativeAdrenoA6xxGmu.h")
    shutil.copyfile(GPU / "NativeAdrenoA6xxPower.cpp", output / "NativeAdrenoA6xxPower.cpp")
    gmu = (GPU / "NativeAdrenoA6xxGmu.cpp").read_text(encoding="utf-8")
    substitutions = {
        '__asm__ volatile("dsb oshst" ::: "memory");': "__atomic_thread_fence(__ATOMIC_RELEASE);",
        '__asm__ volatile("dmb oshld" ::: "memory");': "__atomic_thread_fence(__ATOMIC_ACQUIRE);",
    }
    for source, replacement in substitutions.items():
        assert gmu.count(source) == 1
        gmu = gmu.replace(source, replacement)
    (output / "NativeAdrenoA6xxGmu.cpp").write_text(gmu, encoding="utf-8")
    (output / "opp.cpp").write_text(HARNESS, encoding="utf-8")
    binary = output / "opp"
    command = ["clang++", "-std=c++17", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
               "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-pthread",
               "-I" + host_path(include), host_path(output / "opp.cpp"),
               host_path(output / "NativeAdrenoA6xxPower.cpp"),
               host_path(output / "NativeAdrenoA6xxGmu.cpp"), "-o", host_path(binary)]
    for name, argv in [("compile", command), ("run", [host_path(binary)])]:
        result = subprocess.run(host_command(argv), capture_output=True, timeout=90)
        (output / (name + ".log")).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + ": " + (result.stdout + result.stderr).decode(errors="replace")[-6000:])
    report = {
        "passed": True, "suites": 13, "default_gpu_khz": 675000,
        "qualified_gpu_khz": [257000, 499200, 585000, 675000],
        "production_power_and_gmu_startup": True,
        "actual_hfi_exchange_and_ack_decode": True,
        "matching_arc_and_ddr_tables": True, "shared_cx_mx_floors_preserved": True,
        "cnoc_and_off_rows_preserved": True, "compressed_hfi_vote": [1, 1, 1],
        "failed_or_missing_ack_blocks_gpu_wake": True,
        "sanitizers": ["address", "undefined"],
        "mocked": ["command-db auxiliary data", "MMIO and firmware responses",
                   "AOP/RPMh completion", "AArch64 publication/acquire barriers"],
        "device_executed": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
