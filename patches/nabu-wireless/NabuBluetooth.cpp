// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8150 GENI UART13 / WCN3991-compatible ROM transport.
// The first powered trial sends only power pulses and EDL Get Version.
// Register and protocol definitions: MiCode nabu-r-oss GENI/GCC/RPMh;
// Linux hci_qca/btqca. Board pins/resources were read in device run 76.
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <kern/locks.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <miscfs/devfs/devfs.h>
#include <sys/conf.h>
#include <sys/errno.h>
#include <sys/fcntl.h>
#include <sys/filio.h>
#include <sys/kern_control.h>
#include <sys/socket.h>
#include <sys/proc.h>
#include <sys/systm.h>
#include <sys/termios.h>
#include <sys/ttycom.h>
#include <sys/uio.h>
#include <sys/vnode.h>
#include <pexpert/pexpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <IOKit/IOService.h>
#include <libkern/c++/OSData.h>
#include "NabuWirelessLog.h"
#include "NabuBluetoothTransport.h"
#include "NabuBluetoothControl.h"
#include "NabuBluetoothBootRx.h"

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

static NabuBluetoothBootRx boot_rx;
static unsigned receive(vm_offset_t uart, uint8_t *bytes, unsigned capacity,uint16_t opcode)
{
    boot_rx.begin(opcode);
    unsigned debug_before=boot_rx.debug_frames,bytes_before=boot_rx.debug_bytes;
    for (unsigned elapsed = 0; elapsed < 1000; ++elapsed) {
        uint32_t irq=rd(uart+0x640);
        if(irq&((3u<<24)|(15u<<9))) {
            nabu_wireless_log("NABU BT: boot RX UART error irq=%#x opcode=%#x\n",irq,opcode);
            boot_rx.failed=true;
        }
        uint32_t status = rd(uart + 0x804);
        unsigned words = status & 0x01ffffff;
        for (unsigned word = 0; word < words; ++word) {
            uint32_t data = rd(uart + 0x780);
            unsigned valid = 4;
            if (word + 1 == words && status & 0x80000000) {
                unsigned last = (status >> 28) & 7;
                if (last && last < 4) valid = last;
            }
            for (unsigned i = 0; i < valid; ++i)boot_rx.take(data>>(i*8));
        }
        wr(uart + 0x648, rd(uart + 0x640));
        if(boot_rx.response_bytes||boot_rx.failed)break;
        IOSleep(1);
    }
    if(boot_rx.debug_frames!=debug_before)
        nabu_wireless_log("NABU BT: boot RX drained QCA debug ACL frames=%u payload-bytes=%u opcode=%#x reply-bytes=%u partial-type=%u remaining=%u\n",
            boot_rx.debug_frames-debug_before,boot_rx.debug_bytes-bytes_before,opcode,boot_rx.response_bytes,boot_rx.type,boot_rx.remaining);
    if(boot_rx.failed||boot_rx.response_bytes>capacity) {
        nabu_wireless_log("NABU BT: boot RX framing/capacity failure opcode=%#x type=%u reply-bytes=%u\n",opcode,boot_rx.type,boot_rx.response_bytes);
        return 0;
    }
    memcpy(bytes,boot_rx.response,boot_rx.response_bytes);return boot_rx.response_bytes;
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
            unsigned received = receive(uart, reply, sizeof(reply),0xfc00);
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
    nabu_wireless_log("NABU BT: loading original crbtfw32 at 115200; nvm uses this board address, sleep mask bits cleared\n");
    bool ok = download_tlv(uart, patch, "rampatch", true) && download_tlv(uart, nvm, "nvm", false);
    uint8_t reply[256];
    if (ok) {
        const uint8_t reset[] = {1, 3, 0x0c, 0};
        ok = transmit(uart, reset, sizeof(reset));
        unsigned size = ok ? receive(uart, reply, sizeof(reply),0x0c03) : 0;
        log_reply("HCI Reset", reply, size);
        ok = size == 7 && reply[0] == 4 && reply[1] == 0x0e && reply[2] == 4 &&
             reply[4] == 3 && reply[5] == 0x0c && reply[6] == 0;
    }
    if (ok) {
        const uint8_t read_address[] = {1, 9, 0x10, 0};
        ok = transmit(uart, read_address, sizeof(read_address));
        unsigned size = ok ? receive(uart, reply, sizeof(reply),0x1009) : 0;
        ok = size == 13 && reply[0] == 4 && reply[1] == 0x0e && reply[4] == 9 &&
             reply[5] == 0x10 && reply[6] == 0 && !memcmp(reply + 7, address->getBytesNoCopy(), 6);
        nabu_wireless_log("NABU BT: HCI address matches board=%u response-bytes=%u\n", ok, size);
    }
    if (ok) {
        const uint8_t local_version[] = {1, 1, 0x10, 0};
        ok = transmit(uart, local_version, sizeof(local_version));
        unsigned size = ok ? receive(uart, reply, sizeof(reply),0x1001) : 0;
        log_reply("HCI Local Version", reply, size);
        ok = size == 15 && reply[0] == 4 && reply[1] == 0x0e && reply[4] == 1 && reply[5] == 0x10 && reply[6] == 0;
    }
    entry->release();
    nabu_wireless_log("NABU BT: firmware initialization result=%u; system Bluetooth stack not attached\n", ok);
    return ok;
}

// BEGIN TESTABLE H4 FRAMING
static unsigned stream_h4_header(uint8_t type)
{
    switch (type) { case 1: case 3: return 3; case 2: case 5: return 4; case 4: return 2; default: return 0; }
}
static unsigned stream_h4_payload(uint8_t type, const uint8_t *header)
{
    if (type == 1 || type == 3) return header[2];
    if (type == 4) return header[1];
    unsigned length = header[2] | (unsigned)header[3] << 8;
    return type == 5 ? length & 0x3fff : length;
}
struct StreamH4Rx {
    uint8_t type, header[4];
    unsigned header_bytes, remaining;
    bool boundary() const { return type == 0; }
    // 1=data, 2=WAKE_IND, 3=WAKE_ACK, 4=SLEEP_IND, -1=invalid H4 type.
    int take(uint8_t byte) {
        if (!type) {
            if (byte == 0xfd) return 2;
            if (byte == 0xfc) return 3;
            if (byte == 0xfe) return 4;
            if (!stream_h4_header(byte)) return -1;
            type = byte; header_bytes = remaining = 0; return 1;
        }
        unsigned need = stream_h4_header(type);
        if (header_bytes < need) {
            header[header_bytes++] = byte;
            if (header_bytes == need) {
                remaining = stream_h4_payload(type, header);
                if (!remaining) type = 0;
            }
        } else if (!--remaining) type = 0;
        return 1;
    }
};
struct StreamTxQueue {
    static constexpr unsigned capacity = 131072;
    uint8_t data[capacity];
    unsigned head, count;
    uint8_t at(unsigned offset) const { return data[(head + offset) % capacity]; }
    void append(const uint8_t *bytes, unsigned size) {
        for (unsigned i = 0; i < size; ++i) data[(head + count++) % capacity] = bytes[i];
    }
    unsigned peek(uint8_t *bytes, unsigned size) const {
        if (size > count) size = count;
        for (unsigned i = 0; i < size; ++i) bytes[i] = at(i);
        return size;
    }
    void consume(unsigned size) { head = (head + size) % capacity; count -= size; }
    void clear() { head = count = 0; }
    // Only complete host H4 packets may enter the UART, so IBS cannot split payloads.
    int packet_size() const {
        if (!count) return 0;
        uint8_t type = at(0), header[4];
        unsigned need = stream_h4_header(type);
        if (!need || type == 4) return -1;
        if (count < need + 1) return 0;
        for (unsigned i = 0; i < need; ++i) header[i] = at(i + 1);
        unsigned size = 1 + need + stream_h4_payload(type, header);
        return count >= size ? (int)size : 0;
    }
};
// END TESTABLE H4 FRAMING

static vm_offset_t stream_uart;
static lck_grp_t *stream_group;
static lck_mtx_t *stream_rx_lock, *stream_tx_lock, *stream_read_lock, *stream_write_lock;
static thread_call_t stream_call, stream_tx_call, stream_socket_call;
static NabuBluetoothRx *stream_rx;
static StreamTxQueue *stream_tx;
static StreamH4Rx stream_rx_frame{};
static bool stream_discard_frame;
static struct user_termios stream_termios{};
static unsigned stream_minimum = 1;
static bool stream_opened;
static int stream_rx_error, stream_tx_error;
static uint64_t stream_received, stream_written, stream_overruns;
static kern_ctl_ref stream_ctl_ref;
static uint32_t stream_socket_unit;
static bool stream_socket_closing, stream_socket_enqueuing;
static IOService *stream_service;
enum { StreamTxAsleep, StreamTxWaking, StreamTxAwake };
static unsigned stream_ibs_tx, stream_ibs_pending_acks, stream_ibs_attempts;
static bool stream_ibs_rx_awake;
static uint64_t stream_ibs_deadline, stream_ibs_wakes, stream_ibs_acks, stream_ibs_sleeps;
static bool stream_idle_requested, stream_idle_confirmed, stream_suspending, stream_rx_wake_waiting;
static uint64_t stream_host_sleep_count;
static unsigned stream_command_logs, stream_event_logs;
static unsigned stream_late_command_logs, stream_late_event_logs;
static uint8_t stream_event_code, stream_event_prefix[4];
static unsigned stream_event_payload_seen;
static unsigned stream_debug_acl_frames,stream_debug_acl_bytes;

static void stream_adopt_boot_rx(const NabuBluetoothBootRx &boot)
{
    // A FIFO word may contain the final boot reply and the next frame prefix.
    // That prefix was consumed by the boot reader: drain its remaining frame
    // before delivering complete new packets to the native consumer.
    stream_rx_frame.type=boot.type;stream_rx_frame.header_bytes=boot.header_bytes;
    stream_rx_frame.remaining=boot.remaining;
    memcpy(stream_rx_frame.header,boot.header,sizeof(boot.header));
    stream_discard_frame=boot.type!=0;
}

static bool trace_address_scan(unsigned opcode)
{
    return opcode == 0x0c03 || opcode == 0x2005 || opcode == 0x200b || opcode == 0x200c;
}

static void stream_clear_rx()
{
    stream_rx->clear();
    stream_discard_frame = !stream_rx_frame.boundary();
}

static bool stream_accept_h4_byte(uint8_t byte,uint8_t previous_type,unsigned previous_header,bool discard)
{
    bool acl=previous_type==2||(!previous_type&&byte==2);
    if(acl&&previous_type&&previous_header==3) {
        const uint8_t *header=stream_rx_frame.header;
        if(header[0]==0xdc&&header[1]==0x2e) {
            stream_discard_frame=true;++stream_debug_acl_frames;
            unsigned bytes=header[2]|header[3]<<8;stream_debug_acl_bytes+=bytes;
            if(stream_debug_acl_frames<=4)nabu_wireless_log("NABU BT STREAM: QCA debug ACL frame=%u payload-bytes=%u; not delivered as connection data\n",stream_debug_acl_frames,bytes);
        }
    }
    if(discard||stream_discard_frame||stream_rx_error)return true;
    if(acl) {
        // Hold the five-byte ACL prefix until the diagnostic handle is known.
        if(!previous_type||previous_header<3)return true;
        if(previous_header==3) {
            uint32_t word=0;for(unsigned i=0;i<4;++i)word|=(uint32_t)stream_rx_frame.header[i]<<(i*8);
            return stream_rx->push_word(2,1)&&stream_rx->push_word(word,4);
        }
    }
    return stream_rx->push_word(byte,1);
}

// RX ownership transfers here only after the synchronous firmware/HCI sequence.
// Caller holds stream_rx_lock; the poller and explicit flush are the only readers.
static void stream_drain_rx(bool discard)
{
    uint32_t irq = rd(stream_uart + 0x640);
    // GENI FIFO overrun/read errors and UART parity/break indications.
    if (!discard && (irq & ((3u << 24) | (15u << 9)))) {
        stream_rx_error = EIO; stream_clear_rx(); ++stream_overruns;
    }
    uint32_t status = rd(stream_uart + 0x804);
    unsigned words = status & 0x01ffffff;
    for (unsigned word = 0; word < words; ++word) {
        uint32_t data = rd(stream_uart + 0x780);
        unsigned bytes = 4;
        if (word + 1 == words && (status & 0x80000000)) {
            unsigned last = (status >> 28) & 7;
            if (last && last < 4) bytes = last;
        }
        stream_received += bytes;
        for (unsigned i = 0; i < bytes; ++i) {
            uint8_t byte = data >> (i * 8);
            uint8_t previous_type = stream_rx_frame.type;
            unsigned previous_header = stream_rx_frame.header_bytes;
            int kind = stream_rx_frame.take(byte);
            if (kind == 2) {
                ++stream_ibs_wakes; stream_idle_confirmed = false;
                if (stream_suspending) stream_rx_wake_waiting = true;
                else { ++stream_ibs_pending_acks; stream_ibs_rx_awake = true; }
            }
            else if (kind == 3) { if (stream_ibs_tx == StreamTxWaking) stream_ibs_tx = StreamTxAwake; ++stream_ibs_acks; }
            else if (kind == 4) { stream_ibs_rx_awake = false; stream_rx_wake_waiting = false; ++stream_ibs_sleeps; }
            else if (kind < 0) { stream_rx_error = EPROTO; stream_clear_rx(); }
            else if (!stream_accept_h4_byte(byte,previous_type,previous_header,discard)) {
                stream_rx_error = EOVERFLOW; stream_clear_rx(); ++stream_overruns;
            }
            if (kind == 1 && stream_suspending) { stream_ibs_rx_awake = true; stream_idle_confirmed = false; }
            if (kind != 1 || stream_idle_requested) wakeup(&stream_idle_requested);
            if (kind == 1 && previous_type == 4) {
                if (previous_header < 2) {
                    if (stream_rx_frame.header_bytes == 2) { stream_event_code = stream_rx_frame.header[0]; stream_event_payload_seen = 0; }
                } else {
                    if (stream_event_payload_seen < sizeof(stream_event_prefix)) stream_event_prefix[stream_event_payload_seen] = byte;
                    ++stream_event_payload_seen;
                }
                if (stream_rx_frame.boundary() && !stream_rx_error && stream_event_payload_seen >= 4 &&
                    (stream_event_code == 0x0e || stream_event_code == 0x0f)) {
                    unsigned opcode = stream_event_code == 0x0e ? stream_event_prefix[1] | stream_event_prefix[2] << 8 :
                        stream_event_prefix[2] | stream_event_prefix[3] << 8;
                    unsigned status = stream_event_prefix[stream_event_code == 0x0e ? 3 : 0];
                    if (stream_event_logs < 96) {
                        nabu_wireless_log("NABU BT HCI: RX event=%#x opcode=%#x status=%u\n", stream_event_code, opcode, status);
                        ++stream_event_logs;
                    } else if (trace_address_scan(opcode) && stream_late_event_logs < 256) {
                        IOLog("NABU BT HCI LATE: RX event=%#x opcode=%#x status=%u record=%u\n",
                            stream_event_code, opcode, status, ++stream_late_event_logs);
                    }
                }
            }
            if (stream_rx_frame.boundary()) stream_discard_frame = false;
        }
    }
    wr(stream_uart + 0x648, irq);
    if (discard) stream_discard_frame = !stream_rx_frame.boundary();
}

static void stream_tx_work(thread_call_param_t, thread_call_param_t)
{
    // Only this worker emits stream bytes/IBS; the RX poller never waits on this lock.
    lck_mtx_lock(stream_tx_lock);
    for (unsigned action = 0; action < 8; ++action) {
        lck_mtx_lock(stream_rx_lock);
        int packet = stream_tx->packet_size();
        uint8_t control = 0;
        if (stream_suspending) { lck_mtx_unlock(stream_rx_lock); break; }
        if (stream_ibs_pending_acks) control = 0xfc;
        else if (stream_tx_error) { lck_mtx_unlock(stream_rx_lock); break; }
        else if (packet < 0) stream_tx_error = EPROTO;
        else if (stream_ibs_tx == StreamTxAsleep && packet) {
            stream_ibs_tx = StreamTxWaking; stream_ibs_attempts = 0; control = 0xfd;
        } else if (stream_ibs_tx == StreamTxWaking) {
            if (mach_absolute_time() < stream_ibs_deadline) { lck_mtx_unlock(stream_rx_lock); break; }
            if (stream_ibs_attempts == 10) stream_tx_error = ETIMEDOUT;
            else control = 0xfd;
        } else if (!packet) { lck_mtx_unlock(stream_rx_lock); break; }
        if (stream_tx_error && !control) { wakeup(stream_tx); wakeup(stream_rx); lck_mtx_unlock(stream_rx_lock); break; }
        if (control == 0xfd) {
            ++stream_ibs_attempts;
            clock_interval_to_deadline(100, kMillisecondScale, &stream_ibs_deadline);
        }
        bool is_command = !control && packet > 0 && stream_tx->at(0) == 1;
        unsigned command_opcode = is_command ? stream_tx->at(1) | stream_tx->at(2) << 8 : 0;
        bool log_command = is_command && stream_command_logs < 96;
        // A paired host applies the preference after desktop feedback, when the
        // startup quota is already exhausted. Keep a bounded console-only trace
        // for the new daemon's Reset/address/scan commands and real completions.
        bool log_late = is_command && !log_command && trace_address_scan(command_opcode) && stream_late_command_logs < 256;
        // Run106 reached scan enable but received Invalid HCI Command Parameters.
        // Preserve the actual address/scan bytes before consuming the TX queue.
        bool log_parameters = (log_command || log_late) && (command_opcode == 0x2005 || command_opcode == 0x200b || command_opcode == 0x200c);
        unsigned parameter_bytes = log_parameters ? stream_tx->at(3) : 0;
        unsigned captured_parameters = parameter_bytes < 7 ? parameter_bytes : 7;
        char parameter_hex[15]{};
        static const char hex[] = "0123456789abcdef";
        for (unsigned i = 0; i < captured_parameters; ++i) {
            uint8_t byte = stream_tx->at(4 + i);
            parameter_hex[2*i] = hex[byte >> 4]; parameter_hex[2*i+1] = hex[byte & 15];
        }
        lck_mtx_unlock(stream_rx_lock);
        if (control) {
            bool ok = transmit(stream_uart, &control, 1, true);
            lck_mtx_lock(stream_rx_lock);
            if (ok && control == 0xfc) --stream_ibs_pending_acks;
            if (!ok) stream_tx_error = EIO;
            wakeup(stream_tx); wakeup(stream_rx); wakeup(&stream_idle_requested);
            lck_mtx_unlock(stream_rx_lock);
            if (!ok) break;
            continue;
        }
        // A complete H4 frame stays indivisible with respect to IBS control bytes.
        for (unsigned left = (unsigned)packet; left;) {
            uint8_t bytes[256];
            lck_mtx_lock(stream_rx_lock);
            unsigned count = stream_tx->peek(bytes, left < sizeof(bytes) ? left : sizeof(bytes));
            lck_mtx_unlock(stream_rx_lock);
            bool ok = transmit(stream_uart, bytes, count, true);
            lck_mtx_lock(stream_rx_lock);
            if (ok) { stream_tx->consume(count); stream_written += count; left -= count; }
            else stream_tx_error = EIO;
            wakeup(stream_tx); wakeup(stream_rx); wakeup(&stream_idle_requested);
            lck_mtx_unlock(stream_rx_lock);
            if (!ok) break;
        }
        lck_mtx_lock(stream_rx_lock);
        bool sent_command = (log_command || log_late) && !stream_tx_error;
        if (sent_command && log_command) ++stream_command_logs;
        if (sent_command && log_late) ++stream_late_command_logs;
        lck_mtx_unlock(stream_rx_lock);
        if (sent_command && log_command) nabu_wireless_log("NABU BT HCI: TX opcode=%#x bytes=%u\n", command_opcode, (unsigned)packet);
        if (sent_command && log_command && log_parameters)
            nabu_wireless_log("NABU BT HCI PARAM: opcode=%#x parameter-bytes=%u captured=%u raw=%s\n",
                command_opcode, parameter_bytes, captured_parameters, parameter_hex);
        if (sent_command && log_late) {
            IOLog("NABU BT HCI LATE: TX opcode=%#x bytes=%u record=%u\n", command_opcode, (unsigned)packet, stream_late_command_logs);
            if (log_parameters)
                IOLog("NABU BT HCI LATE PARAM: opcode=%#x parameter-bytes=%u captured=%u raw=%s\n",
                    command_opcode, parameter_bytes, captured_parameters, parameter_hex);
        }
    }
    lck_mtx_lock(stream_rx_lock);
    int error = stream_tx_error;
    lck_mtx_unlock(stream_rx_lock);
    if (error) {
        wr(stream_uart + 0x604, 4); wait_bit(stream_uart + 0x40, 1, false, 10000);
        nabu_wireless_log("NABU BT STREAM: TX error=%d\n", error);
    }
    lck_mtx_unlock(stream_tx_lock);
}

static void stream_socket_deliver(thread_call_param_t, thread_call_param_t)
{
    uint8_t data[1024];
    lck_mtx_lock(stream_rx_lock);
    if (!stream_socket_unit || stream_socket_closing || stream_socket_enqueuing || stream_ibs_pending_acks || stream_rx_error || !stream_rx->count) {
        lck_mtx_unlock(stream_rx_lock); return;
    }
    uint32_t unit = stream_socket_unit, generation = stream_rx->generation;
    unsigned bytes = stream_rx->peek(data, sizeof(data));
    stream_socket_enqueuing = true;
    lck_mtx_unlock(stream_rx_lock);
    // ctl_enqueuedata takes socket locks. No driver lock is held across this call.
    int error = ctl_enqueuedata(stream_ctl_ref, unit, data, bytes, 0);
    lck_mtx_lock(stream_rx_lock);
    if (stream_socket_unit == unit && stream_rx->generation == generation) {
        if (!error) stream_rx->consume(bytes);
        else if (error != ENOBUFS && error != ENOMEM) stream_rx_error = error;
    }
    stream_socket_enqueuing = false; wakeup(&stream_socket_enqueuing); wakeup(&stream_idle_requested);
    lck_mtx_unlock(stream_rx_lock);
    if (error && error != ENOBUFS && error != ENOMEM)
        nabu_wireless_log("NABU BT STREAM: socket RX error=%d unit=%u\n", error, unit);
}

static void stream_poll(thread_call_param_t, thread_call_param_t)
{
    lck_mtx_lock(stream_rx_lock);
    unsigned before = stream_rx->count;
    int previous_error = stream_rx_error;
    stream_drain_rx(false);
    // Wake only for new data/errors: waking every poll would restart VTIME forever.
    if (stream_rx->count != before || stream_rx_error != previous_error) wakeup(stream_rx);
    bool tx_needed = !stream_suspending && (stream_ibs_pending_acks ||
        (!stream_tx_error && ((stream_ibs_tx == StreamTxWaking && mach_absolute_time() >= stream_ibs_deadline) ||
         (stream_ibs_tx != StreamTxWaking && stream_tx->packet_size() != 0))));
    bool socket_needed = stream_socket_unit && !stream_socket_closing && !stream_ibs_pending_acks && !stream_rx_error && stream_rx->count;
    lck_mtx_unlock(stream_rx_lock);
    if (tx_needed) thread_call_enter(stream_tx_call);
    if (socket_needed) thread_call_enter(stream_socket_call);
    uint64_t deadline;
    clock_interval_to_deadline(1, kMillisecondScale, &deadline);
    thread_call_enter_delayed(stream_call, deadline);
}

static int stream_acquire(uint32_t unit)
{
    lck_mtx_lock(stream_tx_lock);
    lck_mtx_lock(stream_rx_lock);
    int error = stream_opened ? EBUSY : 0;
    if (!error) {
        stream_opened = true; stream_socket_unit = unit; stream_socket_closing = false;
        stream_idle_requested = stream_idle_confirmed = stream_suspending = false;
        if (stream_rx_wake_waiting) { ++stream_ibs_pending_acks; stream_ibs_rx_awake = true; stream_rx_wake_waiting = false; }
        stream_rx_error = stream_tx_error = 0; stream_clear_rx(); stream_tx->clear();
        if (stream_ibs_tx == StreamTxWaking) stream_ibs_tx = StreamTxAsleep;
        stream_drain_rx(true); stream_minimum = 1;
        stream_termios.c_cc[VMIN] = 1; stream_termios.c_cc[VTIME] = 0;
    }
    lck_mtx_unlock(stream_rx_lock);
    lck_mtx_unlock(stream_tx_lock);
    if (!error) thread_call_enter(stream_tx_call);
    nabu_wireless_log("NABU BT STREAM: open unit=%u result=%d\n", unit, error);
    return error;
}

static int stream_open(dev_t, int, int, struct proc *) { return stream_acquire(0); }

static int stream_release(uint32_t unit)
{
    lck_mtx_lock(stream_tx_lock);
    lck_mtx_lock(stream_rx_lock);
    // connect failure also triggers disconnect; it must not release another owner.
    if (!stream_opened || stream_socket_unit != unit) { lck_mtx_unlock(stream_rx_lock); lck_mtx_unlock(stream_tx_lock); return 0; }
    stream_socket_closing = true;
    while (stream_socket_enqueuing)
        msleep(&stream_socket_enqueuing, stream_rx_lock, PZERO, "nabu-bt-ctl-close", nullptr);
    stream_opened = false; stream_socket_unit = 0;
    stream_clear_rx(); stream_tx->clear(); wakeup(stream_rx); wakeup(stream_tx);
    if (stream_ibs_tx == StreamTxWaking) stream_ibs_tx = StreamTxAsleep;
    uint64_t received = stream_received, overruns = stream_overruns;
    uint64_t written = stream_written;
    uint64_t wakes = stream_ibs_wakes, acks = stream_ibs_acks, sleeps = stream_ibs_sleeps;
    lck_mtx_unlock(stream_rx_lock);
    lck_mtx_unlock(stream_tx_lock);
    nabu_wireless_log("NABU BT STREAM: close rx=%llu tx=%llu overruns=%llu; receiver and supplies retained\n", received, written, overruns);
    nabu_wireless_log("NABU BT STREAM: IBS received wake=%llu ack=%llu sleep=%llu\n", wakes, acks, sleeps);
    return 0;
}

static int stream_close(dev_t, int, int, struct proc *) { return stream_release(0); }

static int stream_read(dev_t, struct uio *uio, int ioflag)
{
    if (!uio_resid(uio)) return 0;
    lck_mtx_lock(stream_read_lock);
    lck_mtx_lock(stream_rx_lock);
    int error = 0;
    while (stream_opened && !stream_rx_error && !stream_tx_error) {
        if (stream_ibs_pending_acks) {
            if (ioflag & IO_NDELAY) { error = EWOULDBLOCK; break; }
            error = msleep(stream_rx, stream_rx_lock, PZERO | PCATCH, "nabu-bt-ibs", nullptr);
            if (error) break;
            continue;
        }
        unsigned minimum = stream_minimum;
        if (minimum > (uint64_t)uio_resid(uio)) minimum = (unsigned)uio_resid(uio);
        unsigned timeout_ds = stream_termios.c_cc[VTIME];
        if (stream_rx->count >= minimum && (minimum || !timeout_ds || stream_rx->count)) break;
        if (ioflag & IO_NDELAY) { if (!stream_rx->count) error = EWOULDBLOCK; break; }
        struct timespec timeout{(time_t)(timeout_ds / 10), (long)(timeout_ds % 10) * 100000000};
        struct timespec *wait = timeout_ds && (!minimum || stream_rx->count) ? &timeout : nullptr;
        error = msleep(stream_rx, stream_rx_lock, PZERO | PCATCH, "nabu-bt-rx", wait);
        if (error == EWOULDBLOCK) { error = 0; break; }
        if (error) break;
    }
    if (!stream_opened) error = ENXIO;
    if (stream_rx_error) error = stream_rx_error;
    if (stream_tx_error) error = stream_tx_error;
    unsigned available = stream_rx->count;
    if (available > (uint64_t)uio_resid(uio)) available = (unsigned)uio_resid(uio);
    if (error) available = 0;
    while (available) {
        uint8_t data[1024];
        unsigned bytes = stream_rx->peek(data, available < sizeof(data) ? available : sizeof(data));
        uint32_t generation = stream_rx->generation;
        user_ssize_t before = uio_resid(uio);
        lck_mtx_unlock(stream_rx_lock);
        error = uiomove((caddr_t)data, bytes, uio);
        lck_mtx_lock(stream_rx_lock);
        unsigned moved = (unsigned)(before - uio_resid(uio));
        // A concurrent flush invalidates the old reservation, never the new bytes.
        if (generation != stream_rx->generation) break;
        stream_rx->consume(moved); available -= moved;
        if (error || !moved) break;
    }
    lck_mtx_unlock(stream_rx_lock);
    lck_mtx_unlock(stream_read_lock);
    return error;
}

// Called with the producer lock. The worker consumes without taking that lock.
static int stream_wait_space(unsigned bytes, bool nonblocking)
{
    if (bytes > StreamTxQueue::capacity) return EMSGSIZE;
    lck_mtx_lock(stream_rx_lock);
    int error = 0;
    while (stream_opened && !stream_rx_error && !stream_tx_error && !stream_idle_requested && !stream_suspending && StreamTxQueue::capacity - stream_tx->count < bytes) {
        if (nonblocking) { error = EWOULDBLOCK; break; }
        error = msleep(stream_tx, stream_rx_lock, PZERO | PCATCH, "nabu-bt-tx", nullptr);
        if (error) break;
    }
    if (!stream_opened) error = ENOTCONN;
    if (stream_rx_error) error = stream_rx_error;
    if (stream_tx_error) error = stream_tx_error;
    if (stream_idle_requested || stream_suspending) error = EBUSY;
    lck_mtx_unlock(stream_rx_lock);
    return error;
}

static int stream_write(dev_t, struct uio *uio, int ioflag)
{
    lck_mtx_lock(stream_write_lock);
    int error = 0;
    while (uio_resid(uio)) {
        uint8_t data[256];
        unsigned bytes = uio_resid(uio) < (user_ssize_t)sizeof(data) ? (unsigned)uio_resid(uio) : sizeof(data);
        error = stream_wait_space(bytes, ioflag & IO_NDELAY);
        if (error) break;
        error = uiomove((caddr_t)data, bytes, uio);
        if (error) break;
        lck_mtx_lock(stream_rx_lock); stream_tx->append(data, bytes); lck_mtx_unlock(stream_rx_lock);
        thread_call_enter(stream_tx_call);
    }
    lck_mtx_unlock(stream_write_lock);
    return error;
}

static int stream_set_termios(const struct user_termios &settings, bool flush)
{
    // This candidate exposes the exact 115200/8N1 mode already used by the board.
    // Changing the controller's baud rate also needs its vendor HCI transaction.
    if (settings.c_ospeed != 115200 || (settings.c_ispeed && settings.c_ispeed != 115200) ||
        (settings.c_cflag & CSIZE) != CS8 || !(settings.c_cflag & CREAD) ||
        (settings.c_cflag & (PARENB | CSTOPB | CDTR_IFLOW | CDSR_OFLOW | CCAR_OFLOW))) return EINVAL;
    if ((settings.c_iflag & (ISTRIP | INLCR | IGNCR | ICRNL | IXON | IXOFF | IXANY | PARMRK)) ||
        (settings.c_oflag & OPOST) || (settings.c_lflag & (ECHO | ECHONL | ICANON | ISIG | IEXTEN))) return ENOTSUP;
    wr(stream_uart + 0x25c, (settings.c_cflag & CCTS_OFLOW) ? 0 : 2);
    wr(stream_uart + 0x2ac, (settings.c_cflag & CRTS_IFLOW) ? 0 : 0x80000001u);
    lck_mtx_lock(stream_rx_lock);
    stream_termios = settings; stream_termios.c_ispeed = 115200;
    stream_minimum = settings.c_cc[VMIN];
    if (flush) { stream_clear_rx(); stream_rx_error = 0; stream_drain_rx(true); }
    wakeup(stream_rx);
    lck_mtx_unlock(stream_rx_lock);
    return 0;
}

// Shared by cdev ioctl and native control-socket options; caller holds TX lock.
static int stream_control(u_long command, caddr_t data)
{
    int error = 0;
    switch (command) {
    case TIOCGETA_64:
        lck_mtx_lock(stream_rx_lock); memcpy(data, &stream_termios, sizeof(stream_termios)); lck_mtx_unlock(stream_rx_lock); break;
    case TIOCSETA_64: case TIOCSETAW_64: case TIOCSETAF_64:
        error = stream_set_termios(*(const struct user_termios *)data, command == TIOCSETAF_64); break;
    case 0x80085402: // IOSSIOSPEED, 64-bit speed_t
        if (*(const uint64_t *)data != 115200) error = EINVAL;
        break;
    case 0x80085408: { // Original AppleOnboardSerial minimum read size
        uint64_t minimum = *(const uint64_t *)data;
        if (minimum > NabuBluetoothRx::capacity) { error = EINVAL; break; }
        lck_mtx_lock(stream_rx_lock); stream_minimum = (unsigned)minimum; wakeup(stream_rx); lck_mtx_unlock(stream_rx_lock); break;
    }
    case TIOCFLUSH: {
        int direction = *(int *)data;
        if (direction & ~(FREAD | FWRITE)) { error = EINVAL; break; }
        if (!direction || (direction & FREAD)) {
            lck_mtx_lock(stream_rx_lock); stream_clear_rx(); stream_rx_error = 0; stream_drain_rx(true); lck_mtx_unlock(stream_rx_lock);
        }
        if (!direction || (direction & FWRITE)) {
            lck_mtx_lock(stream_rx_lock); stream_tx->clear(); wakeup(stream_tx); lck_mtx_unlock(stream_rx_lock);
        }
        break;
    }
    case FIONREAD:
        lck_mtx_lock(stream_rx_lock); *(int *)data = stream_rx->count; lck_mtx_unlock(stream_rx_lock); break;
    case FIONBIO: break; // The VFS passes IO_NDELAY to read.
    case FIOASYNC: if (*(int *)data) error = ENOTSUP; break;
    case TIOCOUTQ:
        lck_mtx_lock(stream_rx_lock); *(int *)data = stream_tx->count; lck_mtx_unlock(stream_rx_lock); break;
    case TIOCEXCL: case TIOCNXCL: break; // Original UART accepts both; this transport has one owner.
    default: error = ENOTTY; break;
    }
    return error;
}

static int stream_ioctl(dev_t, u_long command, caddr_t data, int, struct proc *)
{
    if (command == TIOCSETAW_64 || command == TIOCSETAF_64) {
        lck_mtx_lock(stream_rx_lock);
        int error = 0;
        while (stream_opened && stream_tx->count && !stream_tx_error) {
            error = msleep(stream_tx, stream_rx_lock, PZERO | PCATCH, "nabu-bt-drain", nullptr);
            if (error) break;
        }
        if (stream_tx_error) error = stream_tx_error;
        if (!stream_opened) error = ENOTCONN;
        lck_mtx_unlock(stream_rx_lock);
        if (error) return error;
    }
    lck_mtx_lock(stream_tx_lock);
    int error = stream_control(command, data);
    lck_mtx_unlock(stream_tx_lock);
    nabu_wireless_log("NABU BT STREAM: ioctl=%#lx result=%d\n", command, error);
    return error;
}

// Caller holds the state/RX lock. One absolute deadline covers every wakeup.
static int stream_idle_wait(uint64_t deadline)
{
    uint64_t now = mach_absolute_time(), ns;
    if (now >= deadline) return ETIMEDOUT;
    absolutetime_to_nanoseconds(deadline - now, &ns);
    struct timespec timeout{(time_t)(ns / 1000000000), (long)(ns % 1000000000)};
    int error = msleep(&stream_idle_requested, stream_rx_lock, PZERO | PCATCH, "nabu-bt-idle", &timeout);
    return error == EWOULDBLOCK ? ETIMEDOUT : error;
}

static bool stream_idle_drained()
{
    return !stream_tx->count && !stream_ibs_pending_acks && !stream_socket_enqueuing &&
        !stream_rx->count && stream_rx_frame.boundary();
}

static int stream_enter_idle()
{
    // A lifecycle client must already own the transport, after stack shutdown.
    // Do not interrupt a producer halfway through copying an H4 fragment.
    if (!IOLockTryLock((IOLock *)stream_write_lock)) return EBUSY;
    lck_mtx_lock(stream_rx_lock);
    int error = !stream_opened ? ENOTCONN : stream_idle_requested ? EBUSY : 0;
    if (!error) { stream_idle_requested = true; stream_idle_confirmed = false; }
    lck_mtx_unlock(stream_rx_lock);
    lck_mtx_unlock(stream_write_lock);
    if (error) return error;
    uint64_t deadline;
    clock_interval_to_deadline(NABU_BT_IDLE_DEADLINE_MS, kMillisecondScale, &deadline);
    thread_call_enter(stream_tx_call); thread_call_enter(stream_socket_call);
    bool sent_sleep = false;
    while (!error && !sent_sleep) {
        lck_mtx_lock(stream_rx_lock);
        if (!stream_opened) error = ENOTCONN;
        else if (stream_rx_error) error = stream_rx_error;
        else if (stream_tx_error) error = stream_tx_error;
        bool drained = stream_idle_drained();
        if (!error && !drained) error = stream_idle_wait(deadline);
        lck_mtx_unlock(stream_rx_lock);
        if (error) break;
        if (!drained) continue;
        // Never wait indefinitely behind a long H4 frame holding the TX lock.
        if (!IOLockTryLock((IOLock *)stream_tx_lock)) {
            if (mach_absolute_time() >= deadline) error = ETIMEDOUT;
            else IOSleep(1);
            continue;
        }
        lck_mtx_lock(stream_rx_lock);
        drained = stream_idle_drained();
        if (drained) stream_suspending = true;
        lck_mtx_unlock(stream_rx_lock);
        if (drained) {
            uint64_t send_limit;
            // Existing transmit has <=60ms FIFO/completion waits, plus 10ms abort.
            clock_interval_to_deadline(70, kMillisecondScale, &send_limit);
            if (send_limit > deadline) error = ETIMEDOUT;
            else {
                const uint8_t sleep = 0xfe;
                sent_sleep = transmit(stream_uart, &sleep, 1, true);
                lck_mtx_lock(stream_rx_lock);
                if (sent_sleep) { stream_ibs_tx = StreamTxAsleep; ++stream_host_sleep_count; }
                else { stream_tx_error = EIO; error = EIO; }
                lck_mtx_unlock(stream_rx_lock);
                if (!sent_sleep) { wr(stream_uart + 0x604, 4); wait_bit(stream_uart + 0x40, 1, false, 10000); }
            }
        }
        lck_mtx_unlock(stream_tx_lock);
    }
    lck_mtx_lock(stream_rx_lock);
    while (!error) {
        stream_drain_rx(false);
        if (!stream_opened) error = ENOTCONN;
        else if (stream_rx_error) error = stream_rx_error;
        else if (stream_tx_error) error = stream_tx_error;
        else if (mach_absolute_time() >= deadline) error = ETIMEDOUT;
        else if (sent_sleep && stream_idle_drained() && !stream_ibs_rx_awake && stream_ibs_sleeps && !stream_rx_wake_waiting) {
            stream_idle_confirmed = true; break;
        }
        if (!error) error = stream_idle_wait(deadline);
    }
    stream_idle_requested = false;
    if (error) {
        stream_idle_confirmed = stream_suspending = false;
        if (stream_rx_wake_waiting) { ++stream_ibs_pending_acks; stream_ibs_rx_awake = true; stream_rx_wake_waiting = false; }
    }
    uint64_t host_sleeps = stream_host_sleep_count, peer_sleeps = stream_ibs_sleeps;
    bool rx_awake = stream_ibs_rx_awake;
    wakeup(stream_tx); wakeup(stream_rx);
    lck_mtx_unlock(stream_rx_lock);
    if (error) thread_call_enter(stream_tx_call);
    nabu_wireless_log("NABU BT IDLE: result=%d FE-sent=%u host-sleeps=%llu peer-sleeps=%llu rx-awake=%u; shared supplies retained\n",
        error, sent_sleep, host_sleeps, peer_sleeps, rx_awake);
    return error;
}

static errno_t stream_ctl_connect(kern_ctl_ref, struct sockaddr_ctl *address, void **unitinfo)
{
    int error = stream_acquire(address->sc_unit);
    if (!error) *unitinfo = stream_rx;
    return error;
}

static errno_t stream_ctl_disconnect(kern_ctl_ref, uint32_t unit, void *unitinfo)
{
    return unitinfo == stream_rx ? stream_release(unit) : 0;
}

static bool stream_ctl_owner(uint32_t unit, void *unitinfo)
{
    lck_mtx_lock(stream_rx_lock);
    bool own = unitinfo == stream_rx && stream_opened && unit && stream_socket_unit == unit && !stream_socket_closing;
    lck_mtx_unlock(stream_rx_lock);
    return own;
}

static errno_t stream_ctl_send(kern_ctl_ref, uint32_t unit, void *unitinfo, mbuf_t packet, int flags)
{
    int error = 0;
    if (!stream_ctl_owner(unit, unitinfo)) error = ENOTCONN;
    else if (flags & MSG_OOB) error = EOPNOTSUPP;
    unsigned total = 0;
    for (mbuf_t part = packet; !error && part; part = mbuf_next(part)) {
        size_t bytes = mbuf_len(part);
        if (bytes > StreamTxQueue::capacity - total) error = EMSGSIZE;
        else total += (unsigned)bytes;
    }
    if (!error) {
        lck_mtx_lock(stream_write_lock);
        // The KPI passes PRUS flags, not the socket's O_NONBLOCK state. Report
        // pressure rather than blocking this callback on a private queue.
        error = stream_wait_space(total, true);
        // Socket uio was already consumed before this callback. EWOULDBLOCK can
        // be converted to a successful partial write by the VFS, losing data.
        if (error == EWOULDBLOCK) error = ENOBUFS;
        if (!error) {
            lck_mtx_lock(stream_rx_lock);
            for (mbuf_t part = packet; part; part = mbuf_next(part))
                stream_tx->append((const uint8_t *)mbuf_data(part), (unsigned)mbuf_len(part));
            lck_mtx_unlock(stream_rx_lock);
            thread_call_enter(stream_tx_call);
        }
        lck_mtx_unlock(stream_write_lock);
    }
    // kern_control transfers ownership on both success and error.
    mbuf_freem(packet);
    return error;
}

static errno_t stream_ctl_setopt(kern_ctl_ref, uint32_t unit, void *unitinfo, int option, void *data, size_t length)
{
    if (!stream_ctl_owner(unit, unitinfo)) return ENOTCONN;
    if (option == NABU_BT_OPT_IBS_IDLE) {
        if (length != sizeof(uint32_t) || !data || *(const uint32_t *)data != NABU_BT_CONTROL_VERSION) return EINVAL;
        return stream_enter_idle();
    }
    u_long command = (uint32_t)option;
    if (command != TIOCSETA_64 && command != 0x80085402 && command != TIOCEXCL && command != TIOCNXCL) return ENOTTY;
    if (length != IOCPARM_LEN(command) || (length && !data)) return EINVAL;
    if (command == TIOCSETA_64) {
        const struct user_termios *settings = (const struct user_termios *)data;
        // SOCK_STREAM already implements this observed raw read mode. Other tty
        // VMIN/VTIME policies would require a separate socket buffering contract.
        if (settings->c_cc[VMIN] != 1 || settings->c_cc[VTIME] != 0) return ENOTSUP;
    }
    return stream_ioctl(0, command, (caddr_t)data, 0, nullptr);
}

static errno_t stream_ctl_getopt(kern_ctl_ref, uint32_t unit, void *unitinfo, int option, void *data, size_t *length)
{
    if (!stream_ctl_owner(unit, unitinfo)) return ENOTCONN;
    if (option == NABU_BT_OPT_IBS_STATE) {
        if (!data) { *length = sizeof(NabuBluetoothIbsState); return 0; }
        if (*length < sizeof(NabuBluetoothIbsState)) return EMSGSIZE;
        lck_mtx_lock(stream_rx_lock);
        NabuBluetoothIbsState state{NABU_BT_CONTROL_VERSION,
            (stream_idle_confirmed ? NABU_BT_IDLE_CONFIRMED : 0u) | (stream_idle_requested ? NABU_BT_IDLE_IN_PROGRESS : 0u),
            stream_ibs_tx, (uint32_t)stream_ibs_rx_awake, stream_host_sleep_count, stream_ibs_sleeps};
        lck_mtx_unlock(stream_rx_lock);
        memcpy(data, &state, sizeof(state)); *length = sizeof(state); return 0;
    }
    u_long command = (uint32_t)option;
    if (command != TIOCGETA_64 && command != TIOCOUTQ) return ENOTTY;
    size_t required = IOCPARM_LEN(command);
    if (!data) { *length = required; return 0; }
    // XNU checks returned length even on error, so do not increase a short buffer.
    if (*length < required) return EMSGSIZE;
    int error = stream_ioctl(0, command, (caddr_t)data, 0, nullptr);
    if (!error) *length = required;
    return error;
}

static void stream_publish_identity()
{
    IORegistryEntry *entry = IORegistryEntry::fromPath("/nabu-bluetooth", gIODTPlane);
    OSData *hci = entry ? OSDynamicCast(OSData, entry->getProperty("address-hci")) : nullptr;
    if (!hci || hci->getLength() != 6) { if (entry) entry->release(); return; }
    uint8_t address[6];
    const uint8_t *source = (const uint8_t *)hci->getBytesNoCopy();
    for (unsigned i = 0; i < 6; ++i) address[i] = source[5 - i];
    entry->release();
    IOService *service = new IOService;
    if (!service || !service->init()) { if (service) service->release(); return; }
    service->setName("bluetooth");
    service->setProperty("local-mac-address", address, sizeof(address));
    // IORegistryEntry::copyProperty checks the entry itself before plane traversal.
    // This is the same property/plane/recursive lookup used by bluetoothd.
    OSObject *object = service->copyProperty("local-mac-address", gIODTPlane, kIORegistryIterateRecursively);
    OSData *observed = OSDynamicCast(OSData, object);
    bool matches = observed && observed->getLength() == 6 && !memcmp(observed->getBytesNoCopy(), address, 6);
    if (object) object->release();
    if (!matches || !service->attach(IOService::getServiceRoot())) { service->release(); return; }
    stream_service = service;
    service->registerService();
    nabu_wireless_log("NABU BT STREAM: bluetooth IOService published; local-mac-address lookup matched board\n");
}

static const struct cdevsw stream_cdevsw = {
    .d_open = stream_open, .d_close = stream_close, .d_read = stream_read, .d_write = stream_write,
    .d_ioctl = stream_ioctl, .d_stop = eno_stop, .d_reset = eno_reset, .d_select = eno_select,
    .d_mmap = eno_mmap, .d_strategy = eno_strat, .d_type = 0
};

static bool stream_start(vm_offset_t uart)
{
    stream_group = lck_grp_alloc_init("nabu-bluetooth", LCK_GRP_ATTR_NULL);
    if (!stream_group) return false;
    stream_rx_lock = lck_mtx_alloc_init(stream_group, LCK_ATTR_NULL);
    stream_tx_lock = lck_mtx_alloc_init(stream_group, LCK_ATTR_NULL);
    stream_read_lock = lck_mtx_alloc_init(stream_group, LCK_ATTR_NULL);
    stream_write_lock = lck_mtx_alloc_init(stream_group, LCK_ATTR_NULL);
    stream_call = thread_call_allocate_with_priority(stream_poll, nullptr, THREAD_CALL_PRIORITY_KERNEL_HIGH);
    stream_tx_call = thread_call_allocate_with_options(stream_tx_work, nullptr, THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE);
    stream_socket_call = thread_call_allocate_with_options(stream_socket_deliver, nullptr, THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE);
    if (!stream_rx_lock || !stream_tx_lock || !stream_read_lock || !stream_write_lock || !stream_call || !stream_tx_call || !stream_socket_call) return false;
    stream_rx = (NabuBluetoothRx *)IOMalloc(sizeof(*stream_rx));
    if (!stream_rx) return false;
    bzero(stream_rx, sizeof(*stream_rx));
    stream_tx = (StreamTxQueue *)IOMalloc(sizeof(*stream_tx));
    if (!stream_tx) return false;
    bzero(stream_tx, sizeof(*stream_tx));
    stream_uart = uart;
    stream_adopt_boot_rx(boot_rx);
    stream_termios.c_cflag = CS8 | CREAD | CLOCAL | CRTSCTS;
    stream_termios.c_ispeed = stream_termios.c_ospeed = 115200;
    stream_termios.c_cc[VMIN] = 1;
    int major = cdevsw_add(-1, &stream_cdevsw);
    if (major < 0) return false;
    if (!devfs_make_node(makedev(major, 0), DEVFS_CHAR, UID_ROOT, GID_WHEEL, 0666, "uart.bluetooth")) {
        cdevsw_remove(major, &stream_cdevsw); return false;
    }
    struct kern_ctl_reg registration{};
    strlcpy(registration.ctl_name, "com.apple.uart.bluetooth", sizeof(registration.ctl_name));
    // The original bluetoothd and diagnostic run as mobile, not root.
    registration.ctl_flags = CTL_FLAG_REG_SOCK_STREAM;
    registration.ctl_sendsize = registration.ctl_recvsize = 65536;
    registration.ctl_connect = stream_ctl_connect; registration.ctl_disconnect = stream_ctl_disconnect;
    registration.ctl_send = stream_ctl_send; registration.ctl_setopt = stream_ctl_setopt; registration.ctl_getopt = stream_ctl_getopt;
    int control_error = ctl_register(&registration, &stream_ctl_ref);
    nabu_wireless_log("NABU BT STREAM: control=com.apple.uart.bluetooth register=%d id=%u\n", control_error, registration.ctl_id);
    thread_call_enter(stream_call);
    stream_publish_identity();
    nabu_wireless_log("NABU BT STREAM: /dev/uart.bluetooth major=%d ready; baud=115200 rx-poll=1ms capacity=%u\n", major, NabuBluetoothRx::capacity);
    nabu_wireless_log("NABU BT STREAM: IBS packet-boundary adapter enabled; TX remains awake after handshake\n");
    return true;
}

bool nabu_wireless_power_on()
{
    vm_offset_t rsc = ml_io_map(0x18220000, 0x4000);
    if (!rsc) return false;
    if (!enable_supply(rsc, "ldoa1", 0x40800, 752) ||
        !enable_supply(rsc, "ldoa7", 0x41f00, 1800) ||
        !enable_supply(rsc, "ldoc2", 0x41d00, 1304) ||
        !enable_supply(rsc, "ldoc11", 0x41a00, 3312)) return false;
    IOSleep(10);
    nabu_wireless_log("NABU WIRELESS: shared supplies ready; no BT pulse or firmware sent\n");
    return true;
}

void nabu_bluetooth_version_trial()
{
    uint32_t level = 0;
    PE_parse_boot_argn("nabu-wireless", &level, sizeof(level));
    nabu_wireless_log("NABU BT: powered trial level=%u; no discovery or pairing\n", level);
    vm_offset_t gcc = ml_io_map(0x00100000, 0x60000);
    vm_offset_t pins = ml_io_map(0x0352b000, 0x4000);
    if (!gcc || !pins) return;
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
    unsigned size = receive(uart, reply, sizeof(reply),0xfc00);
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
    bool initialized = version_ok && level >= 3 && nabu_bluetooth_load_firmware(uart);
    uint32_t persistent = 0;
    PE_parse_boot_argn("nabu-bt-transport", &persistent, sizeof(persistent));
    if (initialized && persistent && stream_start(uart)) return;
    cancel_commands(uart);
}
