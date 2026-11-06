// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <IOKit/IOLib.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include <vm/memory_types.h>
#include "NabuRmtfs.h"
#include "NabuRmtfsSparse.h"
#include "NabuWirelessLog.h"

extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t, vm_size_t, unsigned);
extern "C" void ml_io_unmap(vm_offset_t, vm_size_t);
static NabuRmtfs state;
static bool shared;
// Android FDT reserves 0x99100000+0x1400000 for CDSP. This trial never starts CDSP.
// Use its first 3 MiB, outside the XNU-owned memory, with HLOS/MSS permissions.
static constexpr uint32_t buffer_pa = 0x99100000, buffer_bytes = 0x300000;

static bool assign(bool in) {
    IOPhysicalAddress physical = 0;
    uint8_t *page = (uint8_t *)IOMallocContiguous(16384, 16384, &physical);
    if (!page) return false;
    bzero(page, 16384);
    uint64_t *range = (uint64_t *)page; range[0] = buffer_pa; range[1] = buffer_bytes;
    uint32_t *source = (uint32_t *)(page+64); source[0] = 3; if (!in) source[1] = 15;
    struct Permission { uint32_t vmid, permission; uint64_t context; uint32_t context_size, reserved; };
    Permission *dest = (Permission *)(page+128); dest[0] = {3, 6, 0, 0, 0}; if (in) dest[1] = {15, 6, 0, 0, 0};
    uint64_t *more = (uint64_t *)(page+256); more[0] = in ? 4 : 8; more[1] = physical+128; more[2] = in ? 48 : 24;
    for (uintptr_t line = (uintptr_t)page; line < (uintptr_t)page+16384; line += 64) __asm__ volatile("dc civac, %0" :: "r"(line));
    __asm__ volatile("dsb sy" ::: "memory");
    nabu_wireless_log("NABU RMTFS: assign buffer=%#x+%#x to=%s\n", buffer_pa, buffer_bytes, in ? "HLOS,MSS" : "HLOS");
    uint64_t session = 0, result = ~0ull, response = ~0ull;
    for (unsigned attempt = 0; attempt < 100; ++attempt) {
        register uint64_t x0 __asm__("x0") = attempt ? 1 : 0x42000c16;
        register uint64_t x1 __asm__("x1") = 0x1117;
        register uint64_t x2 __asm__("x2") = physical;
        register uint64_t x3 __asm__("x3") = 16;
        register uint64_t x4 __asm__("x4") = physical+64;
        register uint64_t x5 __asm__("x5") = physical+256;
        register uint64_t x6 __asm__("x6") = session;
        register uint64_t x7 __asm__("x7") = 0;
        __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
            :: "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
        session = x6; result = x0; response = x1; if (result != 1) break;
    }
    IOFreeContiguous(page, 16384);
    nabu_wireless_log("NABU RMTFS: assign result=%lld response=%#llx\n", result, response);
    return result == 0 && response == 0;
}

extern "C" bool nabu_rmtfs_available() { return shared; }
extern "C" bool nabu_rmtfs_prepare(IORegistryEntry *entry) {
    if (!entry->getProperty("rmtfs-modemst1")) return true;
    const char *properties[] = {"rmtfs-modemst1", "rmtfs-modemst2", "rmtfs-fsg", "rmtfs-fsc"};
    const char *paths[] = {"/boot/modem_fs1", "/boot/modem_fs2", "/boot/modem_fsg", "/boot/modem_fsc"};
    for (unsigned i = 0; i < 4; ++i) {
        OSData *file = OSDynamicCast(OSData, entry->getProperty(properties[i]));
        if (!file || file->getLength() < 16) return false;
        const uint8_t *packed = (const uint8_t *)file->getBytesNoCopy();
        unsigned size = NabuRmtfs::u32(packed+4);
        if (size != (i == 3 ? 262144u : 8388608u)) return false;
        state.files[i] = {paths[i], (uint8_t *)IOMalloc(size), size, false};
        if (!state.files[i].data) return false;
        if (!nabu_rmtfs_unpack(packed, file->getLength(), state.files[i].data, size)) return false;
        nabu_wireless_log("NABU RMTFS: snapshot %s bytes=%u packed=%u; writes remain in RAM\n", paths[i], size, file->getLength());
    }
    if (!assign(true)) return false;
    shared = true;
    state.buffer = (volatile uint8_t *)ml_io_map_unmappable(buffer_pa, buffer_bytes, VM_WIMG_WCOMB);
    state.physical = buffer_pa; state.buffer_size = buffer_bytes;
    for (unsigned i = 0; i < buffer_bytes; i += 8) *(volatile uint64_t *)(state.buffer+i) = 0;
    __asm__ volatile("dsb sy" ::: "memory");
    return true;
}
extern "C" unsigned nabu_rmtfs_request(const uint8_t *data, unsigned bytes, uint8_t *answer) {
    unsigned result = state.answer(data, bytes, answer);
    __asm__ volatile("dsb sy" ::: "memory");
    if (state.requests <= 40 && result)
        nabu_wireless_log("NABU RMTFS: message=%u result=%u error=%u reads=%u writes-in-RAM=%u\n", NabuRmtfs::u16(data+3), answer[10], answer[12], state.reads, state.writes);
    return result;
}
extern "C" void nabu_rmtfs_finish() {
    if (!shared || !assign(false)) return;
    shared = false;
    ml_io_unmap((vm_offset_t)state.buffer, buffer_bytes); state.buffer = nullptr;
    for (auto &file : state.files) { IOFree(file.data, file.size); file.data = nullptr; }
    nabu_wireless_log("NABU RMTFS: stopped requests=%u reads=%u writes-in-RAM=%u; device partitions unchanged\n", state.requests, state.reads, state.writes);
}
