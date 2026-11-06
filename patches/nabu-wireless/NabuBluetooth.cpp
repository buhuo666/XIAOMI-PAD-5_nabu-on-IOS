// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8150 GENI UART13 / WCN3991-compatible ROM transport.
// The first powered trial sends only power pulses and EDL Get Version.
// Register and protocol definitions: MiCode nabu-r-oss GENI/GCC/RPMh;
// Linux hci_qca/btqca. Board pins/resources were read in device run 76.
#include <IOKit/IOLib.h>
#include <kern/locks.h>
#include <pexpert/pexpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include "NabuWirelessLog.h"

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" lck_mtx_t hakios_rsc_lock;

static uint32_t rd(vm_offset_t at) { return *(volatile uint32_t *)at; }
static void wr(vm_offset_t at, uint32_t value) {
    *(volatile uint32_t *)at = value;
    __asm__ volatile("dsb sy" ::: "memory");
}

static bool wait_bit(vm_offset_t at, uint32_t mask, bool set, unsigned usec)
{
    for (unsigned elapsed = 0; elapsed < usec; elapsed += 10) {
        if (!!(rd(at) & mask) == set) return true;
        IODelay(10);
    }
    return false;
}

static bool enable_supply(vm_offset_t rsc, const char *name, uint32_t resource, uint32_t mv)
{
    vm_offset_t tcs = rsc + 0xd00;
    lck_mtx_lock(&hakios_rsc_lock);
    if (!rd(tcs + 0x18) || rd(tcs + 0x1c)) {
        lck_mtx_unlock(&hakios_rsc_lock);
        nabu_wireless_log("NABU BT: %s: active TCS0 busy\n", name); return false;
    }
    // Voltage in mV, PMIC5 LDO HPM=7, enable=1; command completion requested.
    const uint32_t offsets[] = {0, 8, 4}, values[] = {mv, 7, 1};
    wr(rsc + 0xd08, 1);
    for (unsigned i = 0; i < 3; ++i) {
        vm_offset_t command = tcs + 0x30 + 20 * i;
        wr(command, 0x10108);
        wr(command + 4, resource + offsets[i]);
        wr(command + 8, values[i]);
    }
    wr(tcs + 0x10, 7); wr(tcs + 0x1c, 7);
    wr(tcs + 0x14, 1u << 16);
    wr(tcs + 0x14, (1u << 16) | (1u << 24));
    bool done = wait_bit(rsc + 0xd04, 1, true, 50000);
    uint32_t status[3] = {rd(tcs + 0x3c), rd(tcs + 0x50), rd(tcs + 0x64)};
    wr(tcs + 0x14, 0); wr(tcs + 0x1c, 0); wr(tcs + 0x10, 0); wr(rsc + 0xd08, 1);
    lck_mtx_unlock(&hakios_rsc_lock);
    nabu_wireless_log("NABU BT: supply=%s mv=%u completed=%u status=%#x,%#x,%#x\n", name, mv, done, status[0], status[1], status[2]);
    return done && (status[0] & 0x10000) && (status[1] & 0x10000) && (status[2] & 0x10000);
}

static bool serial_clock(vm_offset_t gcc)
{
    // Run76: wrapper2 AHB vote bits1/2 already set; serial3 bit7 absent.
    // 300MHz GPLL0-even * 384/15625 = 7.3728MHz. Same table entry as Android.
    wr(gcc + 0x52014, rd(gcc + 0x52014) | 0x86);
    uint32_t cfg = rd(gcc + 0x1e4dc);
    wr(gcc + 0x1e4e0, 384);
    wr(gcc + 0x1e4e4, (~(15625u - 384u)) & 0xffff);
    wr(gcc + 0x1e4e8, (~15625u) & 0xffff);
    wr(gcc + 0x1e4dc, (cfg & ~0x371fu) | 0x2601);
    wr(gcc + 0x1e4d8, rd(gcc + 0x1e4d8) | 3);
    bool updated = wait_bit(gcc + 0x1e4d8, 1, false, 10000);
    bool running = updated && wait_bit(gcc + 0x1e4d4, 0x80000000, false, 10000);
    nabu_wireless_log("NABU BT: clock updated=%u running=%u vote=%#x serial=%#x rcg=%#x cfg=%#x\n",
        updated, running, rd(gcc + 0x52014), rd(gcc + 0x1e4d4), rd(gcc + 0x1e4d8), rd(gcc + 0x1e4dc));
    return running;
}

static bool cancel_commands(vm_offset_t uart)
{
    if (rd(uart + 0x40) & 1) {
        wr(uart + 0x604, 4);
        if (!wait_bit(uart + 0x40, 1, false, 10000)) return false;
    }
    if (rd(uart + 0x40) & 0x1000) {
        wr(uart + 0x634, 4);
        if (!wait_bit(uart + 0x40, 0x1000, false, 10000)) return false;
    }
    wr(uart + 0x618, 0xffffffff); wr(uart + 0x648, 0xffffffff);
    return true;
}

static bool configure_uart(vm_offset_t uart, unsigned divisor)
{
    if (!cancel_commands(uart)) {
        nabu_wireless_log("NABU BT: UART sequencer did not stop, status=%#x\n", rd(uart + 0x40)); return false;
    }
    wr(uart + 0x28, rd(uart + 0x28) | 0x7f); // GENI clock gating controls
    wr(uart + 0xe30, rd(uart + 0xe30) | 0xf); // AHB/DMA clock gating controls, no DMA start
    wr(uart + 0x24, 0x7f); wr(uart + 0x20, 1);
    wr(uart + 0xe18, 0); // no GSI events
    wr(uart + 0x258, 0); // FIFO, no DMA or SMMU involvement
    wr(uart + 0xe1c, 0); // polling only; no GIC IRQ routed by this trial
    wr(uart + 0x614, 0); wr(uart + 0x644, 0);
    wr(uart + 0x260, 0x0000000f); wr(uart + 0x264, 0); // TX one byte per FIFO word
    wr(uart + 0x284, 0x0004380e); wr(uart + 0x288, 0x000c3e0e); // RX four bytes
    wr(uart + 0x22c, 0); // no loopback
    wr(uart + 0x25c, 2); // 8N1, CTS ignored while sending power pulses
    wr(uart + 0x280, 0); wr(uart + 0x2a4, 0); wr(uart + 0x2a8, 0);
    wr(uart + 0x268, 8); wr(uart + 0x28c, 8); wr(uart + 0x26c, 0);
    wr(uart + 0x294, 160);
    wr(uart + 0x80c, 2); wr(uart + 0x810, 2); wr(uart + 0x814, 14);
    wr(uart + 0x48, (divisor << 4) | 1); wr(uart + 0x4c, (divisor << 4) | 1);
    wr(uart + 0x2ac, 0);
    return true;
}

static bool transmit(vm_offset_t uart, const uint8_t *bytes, unsigned count, bool quiet = false)
{
    unsigned depth = (rd(uart + 0xe24) >> 16) & 0x3f;
    if (!depth) return false;
    wr(uart + 0x618, 0xffffffff);
    wr(uart + 0x270, count); wr(uart + 0x600, 1u << 27);
    for (unsigned i = 0; i < count; ++i) {
        unsigned tries;
        for (tries = 0; tries < 1000 && (rd(uart + 0x800) & 0x0fffffff) >= depth; ++tries) IODelay(10);
        if (tries == 1000) return false;
        wr(uart + 0x700, bytes[i]);
    }
    bool done = wait_bit(uart + 0x610, 1, true, 50000);
    if (!quiet || !done) nabu_wireless_log("NABU BT: TX bytes=%u done=%u irq=%#x status=%#x ios=%#x\n",
        count, done, rd(uart + 0x610), rd(uart + 0x40), rd(uart + 0x908));
    wr(uart + 0x618, rd(uart + 0x610));
    return done;
}

static unsigned receive(vm_offset_t uart, uint8_t *bytes, unsigned capacity)
{
    unsigned size = 0;
    for (unsigned elapsed = 0; elapsed < 1000; ++elapsed) {
        uint32_t status = rd(uart + 0x804);
        unsigned words = status & 0x01ffffff;
        for (unsigned word = 0; word < words; ++word) {
            uint32_t data = rd(uart + 0x780);
            unsigned valid = 4;
            if (word + 1 == words && status & 0x80000000) {
                unsigned last = (status >> 28) & 7;
                if (last && last < 4) valid = last;
            }
            for (unsigned i = 0; i < valid && size < capacity; ++i) bytes[size++] = data >> (i * 8);
        }
        wr(uart + 0x648, rd(uart + 0x640));
        if (size >= 3 && bytes[0] == 4 && size >= 3u + bytes[2]) break;
        IOSleep(1);
    }
    return size;
}

static void log_reply(const char *label, const uint8_t *reply, unsigned size)
{
    char hex[769]; unsigned at = 0;
    for (unsigned i = 0; i < size; ++i) at += snprintf(hex + at, sizeof(hex) - at, "%02x ", reply[i]);
    hex[at] = 0;
    nabu_wireless_log("NABU BT: %s RX bytes=%u data=%s\n", label, size, hex);
}

static bool download_tlv(vm_offset_t uart, OSData *blob, const char *name, bool skip_intermediate)
{
    const uint8_t *data = (const uint8_t *)blob->getBytesNoCopy();
    unsigned bytes = blob->getLength();
    unsigned segment = 0;
    for (unsigned at = 0; at < bytes; ++segment) {
        unsigned size = bytes - at < 243 ? bytes - at : 243;
        uint8_t command[249] = {1, 0, 0xfc, (uint8_t)(size + 2), 0x1e, (uint8_t)size};
        memcpy(command + 6, data + at, size);
        if (!transmit(uart, command, size + 6, true)) return false;
        at += size;
        if (!skip_intermediate || at == bytes) {
            uint8_t reply[256];
            unsigned received = receive(uart, reply, sizeof(reply));
            // WCN3991 command-complete return payload is only {status, subcommand}.
            bool ok = received == 8 && reply[0] == 4 && reply[1] == 0x0e && reply[2] == 5 &&
                reply[4] == 0 && reply[5] == 0xfc && reply[6] == 0 && reply[7] == 0x1e;
            if (!ok || at == bytes) log_reply(name, reply, received);
            if (!ok) {
                nabu_wireless_log("NABU BT: %s segment=%u rejected or timed out\n", name, segment); return false;
            }
        }
        if (segment % 128 == 0 || at == bytes)
            nabu_wireless_log("NABU BT: %s sent=%u/%u segments=%u\n", name, at, bytes, segment + 1);
    }
    return true;
}

extern "C" bool nabu_bluetooth_load_firmware(vm_offset_t uart)
{
    IORegistryEntry *entry = IORegistryEntry::fromPath("/nabu-bluetooth", gIODTPlane);
    if (!entry) { nabu_wireless_log("NABU BT: firmware ADT node absent\n"); return false; }
    OSData *patch = OSDynamicCast(OSData, entry->getProperty("rampatch"));
    OSData *nvm = OSDynamicCast(OSData, entry->getProperty("nvm"));
    OSData *address = OSDynamicCast(OSData, entry->getProperty("address-hci"));
    if (!patch || !nvm || !address || address->getLength() != 6) { entry->release(); return false; }
    nabu_wireless_log("NABU BT: loading original crbtfw32 at 115200; nvm uses this board address, sleep disabled\n");
    bool ok = download_tlv(uart, patch, "rampatch", true) && download_tlv(uart, nvm, "nvm", false);
    uint8_t reply[256];
    if (ok) {
        const uint8_t reset[] = {1, 3, 0x0c, 0};
        ok = transmit(uart, reset, sizeof(reset));
        unsigned size = ok ? receive(uart, reply, sizeof(reply)) : 0;
        log_reply("HCI Reset", reply, size);
        ok = size == 7 && reply[0] == 4 && reply[1] == 0x0e && reply[2] == 4 &&
             reply[4] == 3 && reply[5] == 0x0c && reply[6] == 0;
    }
    if (ok) {
        const uint8_t read_address[] = {1, 9, 0x10, 0};
        ok = transmit(uart, read_address, sizeof(read_address));
        unsigned size = ok ? receive(uart, reply, sizeof(reply)) : 0;
        ok = size == 13 && reply[0] == 4 && reply[1] == 0x0e && reply[4] == 9 &&
             reply[5] == 0x10 && reply[6] == 0 && !memcmp(reply + 7, address->getBytesNoCopy(), 6);
        nabu_wireless_log("NABU BT: HCI address matches board=%u response-bytes=%u\n", ok, size);
    }
    if (ok) {
        const uint8_t local_version[] = {1, 1, 0x10, 0};
        ok = transmit(uart, local_version, sizeof(local_version));
        unsigned size = ok ? receive(uart, reply, sizeof(reply)) : 0;
        log_reply("HCI Local Version", reply, size);
        ok = size == 15 && reply[0] == 4 && reply[1] == 0x0e && reply[4] == 1 && reply[5] == 0x10 && reply[6] == 0;
    }
    entry->release();
    nabu_wireless_log("NABU BT: firmware initialization result=%u; system Bluetooth stack not attached\n", ok);
    return ok;
}

void nabu_bluetooth_version_trial()
{
    uint32_t level = 0;
    PE_parse_boot_argn("nabu-wireless", &level, sizeof(level));
    nabu_wireless_log("NABU BT: powered trial level=%u; no discovery or pairing\n", level);
    vm_offset_t rsc = ml_io_map(0x18220000, 0x4000), gcc = ml_io_map(0x00100000, 0x60000);
    vm_offset_t pins = ml_io_map(0x0352b000, 0x4000);
    if (!rsc || !gcc || !pins) return;
    if (!enable_supply(rsc, "ldoa1", 0x40800, 750) ||
        !enable_supply(rsc, "ldoa7", 0x41f00, 1800) ||
        !enable_supply(rsc, "ldoc2", 0x41d00, 1304) ||
        !enable_supply(rsc, "ldoc11", 0x41a00, 3300)) return;
    IOSleep(10);
    if (!serial_clock(gcc)) return;
    vm_offset_t uart = ml_io_map(0x00c8c000, 0x4000);
    if (!uart) return;
    uint32_t firmware = rd(uart + 0x68);
    nabu_wireless_log("NABU BT: UART main-fw=%#x secondary-fw=%#x hw=%#x,%#x status=%#x\n",
        firmware, rd(uart + 0x6c), rd(uart + 0xe24), rd(uart + 0xe28), rd(uart + 0x40));
    if (((firmware >> 8) & 255) != 2) {
        nabu_wireless_log("NABU BT: UART microcode absent or not UART; initialization stops\n"); return;
    }
    // DT active state: qup13 selector1, 2mA, CTS/RX no pull, RTS down, TX up.
    const uint32_t pulls[] = {0, 1, 3, 0};
    for (unsigned i = 0; i < 4; ++i) wr(pins + i * 0x1000, (rd(pins + i * 0x1000) & ~0x3ffu) | 4 | pulls[i]);
    // WCN399x power-off pulse at 2400, then power-on pulse at 115200.
    const uint8_t off = 0xc0, on = 0xfc;
    if (!configure_uart(uart, 96) || !transmit(uart, &off, 1)) return;
    IOSleep(100);
    if (!configure_uart(uart, 2) || !transmit(uart, &on, 1)) return;
    IOSleep(100);
    if (!configure_uart(uart, 2)) return;
    wr(uart + 0x25c, 0); // hardware CTS for HCI
    wr(uart + 0x630, 1u << 27); // continuous receiver
    const uint8_t version[] = {1, 0, 0xfc, 1, 0x19};
    if (!transmit(uart, version, sizeof(version))) return;
    uint8_t reply[256];
    unsigned size = receive(uart, reply, sizeof(reply));
    log_reply("ROM version", reply, size);
    bool version_ok = size >= 21 && reply[0] == 4 && reply[1] == 0x0e && reply[4] == 0 && reply[5] == 0xfc &&
        reply[6] == 0 && reply[7] == 0x19 && reply[8] == 12; // observed version payload length, not status
    if (version_ok) {
        uint32_t product = 0, soc = 0;
        for (unsigned i = 0; i < 4; ++i) { product |= (uint32_t)reply[9 + i] << (8 * i); soc |= (uint32_t)reply[17 + i] << (8 * i); }
        nabu_wireless_log("NABU BT: ROM version response product=%#x patch=%#x rom=%#x soc=%#x\n", product,
            reply[13] | reply[14] << 8, reply[15] | reply[16] << 8, soc);
    }
    nabu_wireless_log("NABU BT: trial complete version-response=%u irq=%#x status=%#x ios=%#x\n",
        version_ok, rd(uart + 0x640), rd(uart + 0x40), rd(uart + 0x908));
    if (version_ok && level == 3) nabu_bluetooth_load_firmware(uart);
    cancel_commands(uart);
}
