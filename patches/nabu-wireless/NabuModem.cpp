// SPDX-License-Identifier: BSD-2-Clause-Patent
// Nabu modem PAS boot prerequisite for WLAN. Board values: captured Android FDT.
// Protocols: Qualcomm SMEM/SMP2P, QMP, RPMh and PAS (Linux and HakiOS sources).
// This trial starts the original signed image, observes SMP2P, then stops it.
// It does not configure cellular service, IPA, WLAN DMA or network interfaces.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include <kern/locks.h>
#include <mach/vm_param.h>
#include <vm/memory_types.h>
#include <pexpert/pexpert.h>
#include "NabuSmem.h"
#include "NabuWirelessLog.h"

extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t, vm_size_t, unsigned int);
extern "C" void ml_io_unmap(vm_offset_t, vm_size_t);
extern "C" lck_mtx_t hakios_aop_mailbox_lock;
extern "C" lck_mtx_t hakios_rsc_lock;
extern "C" lck_mtx_t hakios_smem_alloc_lock;
extern "C" void nabu_glink_trial(vm_offset_t, vm_offset_t);
extern "C" bool nabu_rmtfs_prepare(IORegistryEntry *);
extern "C" void nabu_rmtfs_finish();
extern "C" void nabu_msa_finish();

static vm_offset_t aop, ipc, rsc, smem_va;
static uint32_t mailbox, our_item;
static vm_offset_t map_region(const char *name, vm_offset_t pa, vm_size_t size, unsigned flags) {
    nabu_wireless_log("NABU MODEM: map %s physical=%#llx bytes=%#llx\n", name, (uint64_t)pa, (uint64_t)size);
    // ml_io_map and ml_io_map_wcomb share an 8 MiB permanent submap.
    // The modem image alone has a 15 MiB segment; use kernel_map instead.
    vm_offset_t address = ml_io_map_unmappable(pa, size, flags);
    nabu_wireless_log("NABU MODEM: map %s complete=%u\n", name, address != 0);
    return address;
}
static uint32_t rd(vm_offset_t at) { return *(volatile uint32_t *)at; }
static void wr(vm_offset_t at, uint32_t value) {
    *(volatile uint32_t *)at = value;
    __asm__ volatile("dsb sy" ::: "memory");
}
static bool wait_value(vm_offset_t at, uint32_t value, unsigned ms) {
    for (unsigned i = 0; i < ms; ++i) { if (rd(at) == value) return true; IOSleep(1); }
    return false;
}
static bool scm(unsigned command, uint64_t types, uint64_t a, uint64_t b, uint64_t c) {
    uint64_t session = 0;
    nabu_wireless_log("NABU MODEM: PAS command=%u arg0=%#llx arg1=%#llx arg2=%#llx\n", command, a, b, c);
    for (unsigned attempt = 0; attempt < 100; ++attempt) {
        register uint64_t x0 __asm__("x0") = attempt ? 1 : 0x42000200 | command;
        register uint64_t x1 __asm__("x1") = types;
        register uint64_t x2 __asm__("x2") = a;
        register uint64_t x3 __asm__("x3") = b;
        register uint64_t x4 __asm__("x4") = c;
        register uint64_t x5 __asm__("x5") = 0;
        register uint64_t x6 __asm__("x6") = session;
        register uint64_t x7 __asm__("x7") = 0;
        __asm__ volatile("smc #0" : "+r"(x0), "+r"(x1), "+r"(x2), "+r"(x3), "+r"(x4), "+r"(x5), "+r"(x6), "+r"(x7)
            : : "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15", "x16", "x17", "memory");
        session = x6;
        if (x0 != 1) {
            nabu_wireless_log("NABU MODEM: PAS command=%u result=%lld response=%#llx\n", command, x0, x1);
            return x0 == 0 && x1 == 0;
        }
    }
    return false;
}

static bool qmp_open() {
    if (rd(aop) != 0x4d41494c || rd(aop + 4) != 1) return false;
    mailbox = rd(aop + 0x38);
    unsigned size = rd(aop + 0x34);
    if (mailbox < 0x3c || mailbox > 0x1000 || size < 68 || size > 0x1000 - mailbox) return false;
    wr(aop + 0x10, rd(aop + 0x0c)); wr(aop + 0x24, 0xffff); wr(ipc, 1);
    if (!wait_value(aop + 0x28, 0xffff, 1000)) return false;
    wr(aop + 0x2c, 0xffff); wr(ipc, 1);
    if (!wait_value(aop + 0x14, 0xffff, 1000)) return false;
    wr(aop + 0x18, 0xffff); wr(ipc, 1);
    return wait_value(aop + 0x30, 0xffff, 1000);
}
static bool qmp_send(bool on) {
    lck_mtx_lock(&hakios_aop_mailbox_lock);
    bool open = mailbox || qmp_open();
    bool ok = false;
    if (open && rd(aop + mailbox) == 0) {
        char text[64] = {};
        snprintf(text, sizeof(text), "{class: image, res: load_state, name: modem, val: %s}", on ? "on" : "off");
        for (unsigned i = 0; i < 16; ++i) { uint32_t word; memcpy(&word, text + 4 * i, 4); wr(aop + mailbox + 4 + i * 4, word); }
        wr(aop + mailbox, sizeof(text)); wr(ipc, 1);
        ok = wait_value(aop + mailbox, 0, 1000);
    }
    lck_mtx_unlock(&hakios_aop_mailbox_lock);
    nabu_wireless_log("NABU MODEM: AOP load-state=%s open=%u accepted=%u\n", on ? "on" : "off", open, ok);
    return ok;
}

static bool proxy_power() {
    NabuSmem db{(const volatile uint8_t *)map_region("command-db", 0x85f20000, 0x20000, VM_WIMG_IO), 0x20000};
    if (!db.data || db.u32(4) != 0x0c0330db) return false;
    const char *names[] = {"cx.lvl", "mss.lvl"};
    uint32_t addresses[2] = {}, positions[2] = {};
    for (unsigned s = 0; s < 8; ++s) {
        uint32_t slave = 8 + 16 * s, first = 144 + db.u16(slave + 2), count = db.u16(slave + 6);
        if (!db.u16(slave) || !db.span(first, count * 24)) continue;
        for (unsigned i = 0; i < count; ++i) {
            unsigned at = first + i * 24;
            char name[9] = {}; for (unsigned j = 0; j < 8; ++j) name[j] = db.data[at + j];
            for (unsigned rail = 0; rail < 2; ++rail) if (!strcmp(name, names[rail])) {
                unsigned aux = 144 + db.u16(slave + 4) + db.u16(at + 22), length = db.u16(at + 20);
                if (!db.span(aux, length)) return false;
                for (unsigned level = 0; level < length / 2; ++level) if (db.u16(aux + level * 2) >= 384) {
                    addresses[rail] = db.u32(at + 16); positions[rail] = level;
                    nabu_wireless_log("NABU MODEM: proxy %s resource=%#x position=%u level=%u\n", name, addresses[rail], level, db.u16(aux + level * 2));
                    break;
                }
            }
        }
    }
    if (!addresses[0] || !addresses[1]) return false;
    lck_mtx_lock(&hakios_rsc_lock);
    vm_offset_t tcs = rsc + 0xd00;
    if (!rd(tcs + 0x18) || rd(tcs + 0x1c)) { lck_mtx_unlock(&hakios_rsc_lock); return false; }
    wr(rsc + 0xd08, 1);
    for (unsigned i = 0; i < 2; ++i) {
        wr(tcs + 0x30 + i * 20, 0x10108); wr(tcs + 0x34 + i * 20, addresses[i]); wr(tcs + 0x38 + i * 20, positions[i]);
    }
    wr(tcs + 0x10, 3); wr(tcs + 0x1c, 3); wr(tcs + 0x14, 1u << 16); wr(tcs + 0x14, (1u << 16) | (1u << 24));
    bool done = false;
    for (unsigned i = 0; i < 5000; ++i) { if (rd(rsc + 0xd04) & 1) { done = true; break; } IODelay(10); }
    uint32_t a = rd(tcs + 0x3c), b = rd(tcs + 0x50);
    wr(tcs + 0x14, 0); wr(tcs + 0x1c, 0); wr(tcs + 0x10, 0); wr(rsc + 0xd08, 1);
    lck_mtx_unlock(&hakios_rsc_lock);
    nabu_wireless_log("NABU MODEM: proxy RPMh completed=%u status=%#x,%#x\n", done, a, b);
    // Keep the APPS CX vote until reboot: no general CX consumer accounting exists yet.
    return done && (a & 0x10000) && (b & 0x10000);
}

static bool allocate_item(NabuSmem &smem, uint16_t id, uint32_t bytes, uint32_t *offset) {
    uint32_t base, line;
    if (!smem.partition(1, &base, &line)) return false;
    NabuSmemItem existing;
    vm_offset_t lock = map_region("SMEM-lock3", 0x01f43000, 0x1000, VM_WIMG_IO);
    if (!lock) return false;
    lck_mtx_lock(&hakios_smem_alloc_lock);
    bool held = false;
    for (unsigned i = 0; i < 1000; ++i) { wr(lock, 1); if (rd(lock) == 1) { held = true; break; } IODelay(10); }
    if (!held) { lck_mtx_unlock(&hakios_smem_alloc_lock); return false; }
    if (smem.item_in(base, line, id, &existing)) {
        wr(lock, 0); lck_mtx_unlock(&hakios_smem_alloc_lock);
        *offset = existing.offset; return existing.size == bytes;
    }
    uint32_t size = (bytes + 7) & ~7u;
    uint32_t free = smem.u32(base + 12), limit = smem.u32(base + 16);
    bool ok = free >= 32 && limit >= free && limit - free >= 16 + size;
    if (ok) {
        unsigned header = base + free;
        wr(smem_va + header, 0xa5a5 | ((uint32_t)id << 16)); wr(smem_va + header + 4, size);
        wr(smem_va + header + 8, size - bytes); wr(smem_va + header + 12, 0);
        *offset = header + 16;
        for (unsigned at = 0; at < size; at += 4) wr(smem_va + *offset + at, 0);
        wr(smem_va + base + 12, free + 16 + size);
    }
    wr(lock, 0); lck_mtx_unlock(&hakios_smem_alloc_lock);
    nabu_wireless_log("NABU MODEM: SMEM allocate item=%u bytes=%u result=%u\n", id, bytes, ok);
    return ok;
}

static bool make_smp2p(NabuSmem &smem) {
    NabuSmemItem existing;
    if (smem.find(435, &existing) || smem.find(428, &existing)) {
        nabu_wireless_log("NABU MODEM: modem items already exist; cold-boot trial stops\n"); return false;
    }
    if (!allocate_item(smem, 428, 340, &our_item)) return false;
    wr(smem_va + our_item, 0x504d5324); wr(smem_va + our_item + 8, 1u << 16);
    const char name[16] = "master-kernel";
    for (unsigned at = 0; at < 16; at += 4) { uint32_t word; memcpy(&word, name + at, 4); wr(smem_va + our_item + 20 + at, word); }
    wr(smem_va + our_item + 12, 16 | (1u << 16)); wr(smem_va + our_item + 4, 0x101); wr(ipc, 1u << 14);
    nabu_wireless_log("NABU MODEM: SMP2P item428 created at=%#x, master-kernel entry\n", 0x86000000 + our_item);
    return true;
}

static uint32_t modem_state(NabuSmem &smem, bool announce) {
    NabuSmemItem item;
    if (!smem.find(435, &item) || item.size < 340 || smem.u32(item.offset) != 0x504d5324) return 0;
    uint32_t version = smem.u32(item.offset + 4), flags = smem.u32(item.offset + 16);
    unsigned count = smem.u16(item.offset + 14);
    if (count > 16 || (version & 255) != 1) return 0;
    wr(smem_va + our_item + 4, ((version >> 8) & 1) << 8 | 1);
    uint32_t ours = smem.u32(our_item + 16), ack = (flags & 1) ? 2 : 0;
    if ((version & 0x100) && (ours & 2) != ack) { wr(smem_va + our_item + 16, ack); wr(ipc, 1u << 14); }
    uint32_t state = 0;
    for (unsigned i = 0; i < count; ++i) {
        char name[17] = {}; for (unsigned j = 0; j < 16; ++j) name[j] = smem.data[item.offset + 20 + 20 * i + j];
        uint32_t value = smem.u32(item.offset + 36 + 20 * i);
        if (!strcmp(name, "slave-kernel")) state = value;
        if (announce) nabu_wireless_log("NABU MODEM: peer SMP2P %s=%#x\n", name, value);
    }
    return state;
}

extern "C" void nabu_modem_start_trial() {
    nabu_wireless_log("NABU MODEM: trial entry; resolve firmware node\n");
    IORegistryEntry *entry = IORegistryEntry::fromPath("/nabu-modem", gIODTPlane);
    if (!entry) return;
    OSData *metadata = OSDynamicCast(OSData, entry->getProperty("metadata"));
    if (!metadata || metadata->getLength() > 16384 || metadata->getLength() < 52) { entry->release(); return; }
    nabu_wireless_log("NABU MODEM: metadata bytes=%u; map control and shared memory\n", metadata->getLength());
    aop = map_region("AOP", 0x0c300000, 0x1000, VM_WIMG_IO);
    ipc = map_region("APCS", 0x17c0000c, 4, VM_WIMG_IO);
    rsc = map_region("RPMh", 0x18220000, 0x4000, VM_WIMG_IO);
    // Keep the survey's existing SMEM memory attributes for this alias.
    smem_va = map_region("SMEM", 0x86000000, 0x200000, VM_WIMG_IO);
    if (!aop || !ipc || !rsc || !smem_va) { entry->release(); return; }
    NabuSmem smem{(const volatile uint8_t *)smem_va, 0x200000};
    nabu_wireless_log("NABU MODEM: signed image PAS4 trial begin; reserved=0x8e000000+0x9600000\n");
    if (!make_smp2p(smem) || !proxy_power()) { entry->release(); return; }
    uint32_t level = 0;
    PE_parse_boot_argn("nabu-wireless", &level, sizeof(level));
    if (level >= 5) {
        uint32_t descriptor = 0, fifo = 0;
        if (!allocate_item(smem, 478, 32, &descriptor) || !allocate_item(smem, 479, 16384, &fifo)) { entry->release(); return; }
        wr(smem_va + descriptor + 4, 0); wr(smem_va + descriptor + 8, 0);
    }
    IOPhysicalAddress physical = 0;
    nabu_wireless_log("NABU MODEM: allocate PAS metadata buffer\n");
    void *header = IOMallocContiguous(16384, 16384, &physical);
    if (!header) { entry->release(); return; }
    bzero(header, 16384); memcpy(header, metadata->getBytesNoCopy(), metadata->getLength());
    for (uintptr_t at = (uintptr_t)header; at < (uintptr_t)header + 16384; at += 64) __asm__ volatile("dc civac, %0" : : "r"(at));
    __asm__ volatile("dsb sy" ::: "memory");
    bool prepared = scm(1, 0x82, 4, physical, 0) && scm(2, 3, 4, 0x8e000000, 0x9600000);
    if (!prepared) { IOFreeContiguous(header, 16384); entry->release(); return; }
    NabuSmem elf{(const volatile uint8_t *)metadata->getBytesNoCopy(), metadata->getLength()};
    unsigned offset = elf.u32(28), count = elf.u16(44), loaded = 0;
    uint64_t file_bytes = 0, memory_bytes = 0;
    bool copied = true;
    for (unsigned i = 0; i < count; ++i) {
        unsigned at = offset + i * 32;
        if (!elf.span(at, 32)) { copied = false; break; }
        uint32_t kind = elf.u32(at), pa = elf.u32(at + 12), bytes = elf.u32(at + 16), mem = elf.u32(at + 20), flags = elf.u32(at + 24);
        if (kind != 1 || !mem || ((flags >> 24) & 7) == 2) continue;
        if (pa < 0x8e000000 || pa >= 0x97600000 || mem > 0x97600000 - pa || bytes > mem) { copied = false; break; }
        char name[20]; snprintf(name, sizeof(name), "segment-%02u", i);
        OSData *segment = OSDynamicCast(OSData, entry->getProperty(name));
        if (bytes && (!segment || segment->getLength() != bytes)) { copied = false; break; }
        vm_offset_t page = trunc_page(pa);
        vm_size_t mapping_bytes = round_page(pa - page + mem);
        vm_offset_t mapping = map_region(name, page, mapping_bytes, VM_WIMG_WCOMB);
        if (!mapping) { copied = false; break; }
        vm_offset_t target = mapping + pa - page;
        if (bytes) memcpy((void *)target, segment->getBytesNoCopy(), bytes);
        bzero((void *)(target + bytes), mem - bytes);
        __asm__ volatile("dsb sy" ::: "memory");
        ml_io_unmap(mapping, mapping_bytes);
        file_bytes += bytes; memory_bytes += mem; loaded++;
    }
    nabu_wireless_log("NABU MODEM: copied=%u segments=%u file-bytes=%llu memory-bytes=%llu\n", copied, loaded, file_bytes, memory_bytes);
    bool started = copied && nabu_rmtfs_prepare(entry) && qmp_send(true) && scm(5, 1, 4, 0, 0);
    uint32_t state = 0;
    if (started) {
        for (unsigned i = 0; i < 1500; ++i) { state = modem_state(smem, false); if (state & 3) break; IOSleep(10); }
        modem_state(smem, true);
        nabu_wireless_log("NABU MODEM: started=%u ready=%u state=%#x\n", started, !!(state & 2), state);
        for (unsigned id = 478; id <= 480; ++id) {
            NabuSmemItem item; bool found = smem.find(id, &item);
            nabu_wireless_log("NABU MODEM: GLINK item=%u found=%u size=%u\n", id, found, found ? item.size : 0);
        }
        if (state & 2) {
            if (level >= 5) nabu_glink_trial(smem_va, ipc);
            wr(smem_va + our_item + 36, 1); wr(ipc, 1u << 14);
            for (unsigned i = 0; i < 500; ++i) { state = modem_state(smem, false); if (state & 9) break; IOSleep(10); }
            nabu_wireless_log("NABU MODEM: stop-ack=%u state=%#x\n", !!(state & 8), state);
            wr(smem_va + our_item + 36, 0); wr(ipc, 1u << 14);
        }
        if (scm(6, 1, 4, 0, 0)) { qmp_send(false); nabu_msa_finish(); nabu_rmtfs_finish(); }
    }
    IOFreeContiguous(header, 16384);
    entry->release();
    nabu_wireless_log("NABU MODEM: trial finished started=%u last-state=%#x; GLINK/QRTR and WLAN data path pending\n", started, state);
}
