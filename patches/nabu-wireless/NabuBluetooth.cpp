// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8150 GENI UART13 / WCN3991-compatible ROM transport.
// The first powered trial sends only power pulses and EDL Get Version.
// Register and protocol definitions: MiCode nabu-r-oss GENI/GCC/RPMh;
// Linux hci_qca/btqca. Board pins/resources were read in device run 76.
#include <IOKit/IOLib.h>
#include <kern/locks.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <miscfs/devfs/devfs.h>
#include <sys/conf.h>
#include <sys/errno.h>
#include <sys/fcntl.h>
#include <sys/filio.h>
#include <sys/proc.h>
#include <sys/systm.h>
#include <sys/termios.h>
#include <sys/ttycom.h>
#include <sys/uio.h>
#include <sys/vnode.h>
#include <pexpert/pexpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include "NabuWirelessLog.h"
#include "NabuBluetoothTransport.h"

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

static vm_offset_t stream_uart;
static lck_grp_t *stream_group;
static lck_mtx_t *stream_rx_lock, *stream_tx_lock, *stream_read_lock;
static thread_call_t stream_call;
static NabuBluetoothRx *stream_rx;
static struct user_termios stream_termios{};
static unsigned stream_minimum = 1;
static bool stream_opened;
static int stream_rx_error;
static uint64_t stream_received, stream_written, stream_overruns;

// RX ownership transfers here only after the synchronous firmware/HCI sequence.
// Caller holds stream_rx_lock; the poller and explicit flush are the only readers.
static void stream_drain_rx(bool discard)
{
    uint32_t irq = rd(stream_uart + 0x640);
    // GENI FIFO overrun/read errors and UART parity/break indications.
    if (!discard && (irq & ((3u << 24) | (15u << 9)))) {
        stream_rx_error = EIO; stream_rx->clear(); ++stream_overruns;
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
        if (!discard && !stream_rx_error && !stream_rx->push_word(data, bytes)) {
            stream_rx_error = EOVERFLOW; stream_rx->clear(); ++stream_overruns;
        }
    }
    wr(stream_uart + 0x648, irq);
}

static void stream_poll(thread_call_param_t, thread_call_param_t)
{
    lck_mtx_lock(stream_rx_lock);
    unsigned before = stream_rx->count;
    int previous_error = stream_rx_error;
    stream_drain_rx(false);
    // Wake only for new data/errors: waking every poll would restart VTIME forever.
    if (stream_rx->count != before || stream_rx_error != previous_error) wakeup(stream_rx);
    lck_mtx_unlock(stream_rx_lock);
    uint64_t deadline;
    clock_interval_to_deadline(1, kMillisecondScale, &deadline);
    thread_call_enter_delayed(stream_call, deadline);
}

static int stream_open(dev_t, int, int, struct proc *)
{
    lck_mtx_lock(stream_tx_lock);
    lck_mtx_lock(stream_rx_lock);
    int error = stream_opened ? EBUSY : 0;
    if (!error) {
        stream_opened = true; stream_rx_error = 0; stream_rx->clear();
        stream_drain_rx(true); stream_minimum = 1;
        stream_termios.c_cc[VMIN] = 1; stream_termios.c_cc[VTIME] = 0;
    }
    lck_mtx_unlock(stream_rx_lock);
    lck_mtx_unlock(stream_tx_lock);
    nabu_wireless_log("NABU BT STREAM: open result=%d\n", error);
    return error;
}

static int stream_close(dev_t, int, int, struct proc *)
{
    lck_mtx_lock(stream_rx_lock);
    stream_opened = false; stream_rx->clear(); wakeup(stream_rx);
    uint64_t received = stream_received, overruns = stream_overruns;
    lck_mtx_unlock(stream_rx_lock);
    lck_mtx_lock(stream_tx_lock);
    uint64_t written = stream_written;
    lck_mtx_unlock(stream_tx_lock);
    nabu_wireless_log("NABU BT STREAM: close rx=%llu tx=%llu overruns=%llu; receiver and supplies retained\n", received, written, overruns);
    return 0;
}

static int stream_read(dev_t, struct uio *uio, int ioflag)
{
    if (!uio_resid(uio)) return 0;
    lck_mtx_lock(stream_read_lock);
    lck_mtx_lock(stream_rx_lock);
    int error = 0;
    while (stream_opened && !stream_rx_error) {
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

static int stream_write(dev_t, struct uio *uio, int)
{
    lck_mtx_lock(stream_tx_lock);
    int error = 0;
    while (uio_resid(uio)) {
        uint8_t data[256];
        unsigned bytes = uio_resid(uio) < (user_ssize_t)sizeof(data) ? (unsigned)uio_resid(uio) : sizeof(data);
        error = uiomove((caddr_t)data, bytes, uio);
        if (error) break;
        if (!transmit(stream_uart, data, bytes, true)) {
            wr(stream_uart + 0x604, 4);
            wait_bit(stream_uart + 0x40, 1, false, 10000);
            error = EIO; break;
        }
        stream_written += bytes;
    }
    lck_mtx_unlock(stream_tx_lock);
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
    if (flush) { stream_rx->clear(); stream_rx_error = 0; stream_drain_rx(true); }
    wakeup(stream_rx);
    lck_mtx_unlock(stream_rx_lock);
    return 0;
}

static int stream_ioctl(dev_t, u_long command, caddr_t data, int, struct proc *)
{
    int error = 0;
    lck_mtx_lock(stream_tx_lock);
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
            lck_mtx_lock(stream_rx_lock); stream_rx->clear(); stream_rx_error = 0; stream_drain_rx(true); lck_mtx_unlock(stream_rx_lock);
        }
        // TX is synchronous and this lock has waited for the previous write.
        break;
    }
    case FIONREAD:
        lck_mtx_lock(stream_rx_lock); *(int *)data = stream_rx->count; lck_mtx_unlock(stream_rx_lock); break;
    case FIONBIO: break; // The VFS passes IO_NDELAY to read.
    case FIOASYNC: if (*(int *)data) error = ENOTSUP; break;
    case TIOCOUTQ: *(int *)data = 0; break;
    case TIOCEXCL: case TIOCNXCL: break; // Original UART accepts both; this transport has one owner.
    default: error = ENOTTY; break;
    }
    lck_mtx_unlock(stream_tx_lock);
    nabu_wireless_log("NABU BT STREAM: ioctl=%#lx result=%d\n", command, error);
    return error;
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
    stream_call = thread_call_allocate_with_priority(stream_poll, nullptr, THREAD_CALL_PRIORITY_KERNEL_HIGH);
    if (!stream_rx_lock || !stream_tx_lock || !stream_read_lock || !stream_call) return false;
    stream_rx = (NabuBluetoothRx *)IOMalloc(sizeof(*stream_rx));
    if (!stream_rx) return false;
    bzero(stream_rx, sizeof(*stream_rx));
    stream_uart = uart;
    stream_termios.c_cflag = CS8 | CREAD | CLOCAL | CRTSCTS;
    stream_termios.c_ispeed = stream_termios.c_ospeed = 115200;
    stream_termios.c_cc[VMIN] = 1;
    int major = cdevsw_add(-1, &stream_cdevsw);
    if (major < 0) return false;
    if (!devfs_make_node(makedev(major, 0), DEVFS_CHAR, UID_ROOT, GID_WHEEL, 0666, "uart.bluetooth")) {
        cdevsw_remove(major, &stream_cdevsw); return false;
    }
    thread_call_enter(stream_call);
    nabu_wireless_log("NABU BT STREAM: /dev/uart.bluetooth major=%d ready; baud=115200 rx-poll=1ms capacity=%u\n", major, NabuBluetoothRx::capacity);
    return true;
}

void nabu_bluetooth_version_trial()
{
    uint32_t level = 0;
    PE_parse_boot_argn("nabu-wireless", &level, sizeof(level));
    nabu_wireless_log("NABU BT: powered trial level=%u; no discovery or pairing\n", level);
    vm_offset_t rsc = ml_io_map(0x18220000, 0x4000), gcc = ml_io_map(0x00100000, 0x60000);
    vm_offset_t pins = ml_io_map(0x0352b000, 0x4000);
    if (!rsc || !gcc || !pins) return;
    if (!enable_supply(rsc, "ldoa1", 0x40800, 752) ||
        !enable_supply(rsc, "ldoa7", 0x41f00, 1800) ||
        !enable_supply(rsc, "ldoc2", 0x41d00, 1304) ||
        !enable_supply(rsc, "ldoc11", 0x41a00, 3312)) return;
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
    bool initialized = version_ok && level >= 3 && nabu_bluetooth_load_firmware(uart);
    uint32_t persistent = 0;
    PE_parse_boot_argn("nabu-bt-transport", &persistent, sizeof(persistent));
    if (initialized && persistent && stream_start(uart)) return;
    cancel_commands(uart);
}
