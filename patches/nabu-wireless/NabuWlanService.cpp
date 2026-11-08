// SPDX-License-Identifier: BSD-2-Clause-Patent
// One stable native en0, with serialized association publication and owned TX copies.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include <kern/sched_prim.h>
extern "C" {
#include <sys/hakios.net.h>
#include <sys/hakios.sta.h>
#include <sys/errno.h>
void hakios_sta_invalidate(int error);
bool hakios_sta_join_commit(bool (*commit)(void *), void *context);
int nabu_ath10k_os_radio_powered();
int nabu_ath10k_driver_transmit(const unsigned char *, unsigned long);
int lx_os_thread(const char *, void (*)(void *), void *);
void nabu_wlan_runtime_lost();
}
#include "NabuWirelessLog.h"

static hakios_net_link link;
static bool published, backend_address_matches;
static const hakios_sta_ops *backend;
static hakios_sta_ops native_ops;
static IOLock *gate;
static bool valid, committed, pending_up, tx_started;
static uint64_t connection;
static constexpr unsigned queue_capacity = 256;
struct Frame { size_t length; uint8_t bytes[HAKIOS_NET_FRAME_MAX]; };
static Frame *queue;
static unsigned queue_head, queue_count, tx_active;
static uint64_t tx_accepted, tx_dropped, tx_returned, tx_errors, rx_accepted, rx_dropped;

// gate protects publication and packet admission. Never hold it across backend calls.
static void close_locked()
{
    ++connection;
    pending_up = committed = false;
    tx_dropped += queue_count;
    queue_head = queue_count = 0;
    if (published) hakios_net_link_state(false);
}

static void close_and_drain()
{
    IOLockLock(gate);
    close_locked();
    while (tx_active) IOLockSleep(gate, &tx_active, THREAD_UNINT);
    IOLockUnlock(gate);
}

static void transmit_worker(void *)
{
    Frame frame;
    for (;;) {
        IOLockLock(gate);
        while (!queue_count) IOLockSleep(gate, &queue_count, THREAD_UNINT);
        frame = queue[queue_head];
        queue_head = (queue_head + 1) % queue_capacity;
        --queue_count;
        ++tx_active;
        IOLockUnlock(gate);
        int error = nabu_ath10k_driver_transmit(frame.bytes, frame.length);
        IOLockLock(gate);
        ++tx_returned;
        if (error) ++tx_errors;
        --tx_active;
        IOLockWakeup(gate, &tx_active, false);
        bool report = tx_returned == 1 || (error && tx_errors <= 4);
        IOLockUnlock(gate);
        if (report) nabu_wireless_log("NABU WLAN DATA: backend TX returned=%d; not an air-completion indication\n", error);
    }
}

static bool transmit(mbuf_t packet, size_t length)
{
    IOLockLock(gate);
    if (!valid || !committed || !tx_started || length < 14 ||
        length > HAKIOS_NET_FRAME_MAX || queue_count == queue_capacity) {
        ++tx_dropped;
        IOLockUnlock(gate);
        return false;
    }
    Frame &frame = queue[(queue_head + queue_count) % queue_capacity];
    if (mbuf_copydata(packet, 0, length, frame.bytes)) {
        ++tx_dropped;
        IOLockUnlock(gate);
        return false;
    }
    frame.length = length;
    ++queue_count;
    ++tx_accepted;
    IOLockWakeup(gate, &queue_count, false);
    IOLockUnlock(gate);
    return true; // Queue ownership only; not a claim about over-air delivery.
}

extern "C" void nabu_wlan_service_summary()
{
    if (!gate) return;
    IOLockLock(gate);
    uint64_t accepted=tx_accepted, dropped=tx_dropped, returned=tx_returned,
        errors=tx_errors, received=rx_accepted, rejected=rx_dropped;
    bool up=committed; unsigned waiting=queue_count, active=tx_active;
    IOLockUnlock(gate);
    nabu_wireless_log("NABU WLAN DATA: link=%u TX accepted=%llu dropped=%llu backend-returned=%llu errors=%llu queued=%u active=%u RX handed=%llu dropped=%llu; TX acceptance is not air completion\n",
        up, accepted, dropped, returned, errors, waiting, active, received, rejected);
}

extern "C" void nabu_wlan_service_publish()
{
    if (published) return;
    IORegistryEntry *node = IORegistryEntry::fromPath("/wlan", gIODTPlane);
    if (!node) return;
    OSData *mac = OSDynamicCast(OSData, node->getProperty("local-mac-address"));
    if (!mac || mac->getLength() != sizeof(link.address)) {
        node->release();
        nabu_wireless_log("NABU WLAN SERVICE: device address unavailable; interface not published\n");
        return;
    }
    memcpy(link.address, mac->getBytesNoCopy(), sizeof(link.address));
    node->release();
    if (!gate) gate = IOLockAlloc();
    if (!gate) return;
    if (!queue) queue = static_cast<Frame *>(IOMalloc(sizeof(Frame) * queue_capacity));
    if (!queue) return;
    if (!tx_started) tx_started = lx_os_thread("nabu-wlan-tx", transmit_worker, nullptr) == 0;
    if (!tx_started) return;
    link.name = "Nabu WCN399x ath10k";
    link.unit = 0;
    link.wireless = true;
    link.up = false;
    link.transmit = transmit;
    published = hakios_net_attach(&link);
    nabu_wireless_log("NABU WLAN SERVICE: en0 attached=%u link=down; awaiting backend station offer\n", published);
}

static int station_power(bool on)
{
    if (!on) close_and_drain();
    int error = backend->power(on);
    nabu_wireless_log("NABU WLAN CONTROL: power request=%u returned=%d\n", on, error);
    return error;
}

static int station_scan(const hakios_sta_scan *what)
{
    nabu_wireless_log("NABU WLAN CONTROL: native scan begin channels=%u passive=%u dwell=%u\n",
        what->frequency_count, what->passive, what->dwell_ms);
    int error = backend->scan(what);
    nabu_wireless_log("NABU WLAN CONTROL: native scan returned=%d\n", error);
    return error;
}

struct JoinCommit { uint64_t connection; const hakios_sta_ops *backend; };
static bool commit_join(void *context)
{
    auto *join = static_cast<JoinCommit *>(context);
    IOLockLock(gate);
    bool accept = valid && pending_up && connection == join->connection && backend == join->backend;
    if (accept) {
        committed = true;
        pending_up = false;
        hakios_net_link_state(true);
    }
    IOLockUnlock(gate);
    return accept;
}

static int station_join(const hakios_sta_join *what)
{
    close_and_drain();
    if (what->security != HAKIOS_STA_WPA2_PSK) return EOPNOTSUPP;
    IOLockLock(gate);
    JoinCommit join = {connection, backend};
    bool live = valid;
    IOLockUnlock(gate);
    if (!live) return ENXIO;
    int error = join.backend->join(what);
    struct hakios_sta_state state = {};
    join.backend->state(&state);
    if (!error && (state.phase != HAKIOS_STA_JOINED || !hakios_sta_join_commit(commit_join, &join))) {
        close_and_drain();
        // Firmware fatal teardown belongs to the runtime worker, which drains this call.
        if (nabu_ath10k_os_radio_powered()) join.backend->leave();
        error = ECANCELED;
    }
    if (error) close_and_drain();
    nabu_wireless_log("NABU WLAN CONTROL: native join returned=%d backend-phase=%u; credentials omitted\n", error, state.phase);
    return error;
}

static int station_leave()
{
    close_and_drain();
    int error = backend->leave();
    nabu_wlan_service_summary();
    return error;
}

extern "C" void nabu_wlan_service_invalidate(int error)
{
    // Never wait for native calls or TX in the GLINK/firmware failure path.
    hakios_sta_invalidate(error);
    if (!gate) return;
    IOLockLock(gate);
    valid = false;
    close_locked();
    IOLockUnlock(gate);
}

extern "C" void nabu_ath10k_os_net_attach(const unsigned char *address)
{
    backend_address_matches = published && !memcmp(link.address, address, sizeof(link.address));
    nabu_wireless_log("NABU WLAN SERVICE: backend address matches stable en0=%u\n", backend_address_matches);
}

extern "C" void nabu_ath10k_os_station(const hakios_sta_ops *ops)
{
    if (!ops) {
        nabu_wlan_service_invalidate(ENXIO);
        hakios_sta_attach(nullptr); // Driver worker: drain native readers before freeing the backend.
        if (gate) close_and_drain();
        backend = nullptr;
        nabu_wlan_service_summary();
        nabu_wireless_log("NABU WLAN SERVICE: station withdrawn and native calls/TX drained\n");
        return;
    }
    if (!backend_address_matches || !nabu_ath10k_os_radio_powered()) {
        nabu_wireless_log("NABU WLAN SERVICE: station offer rejected: address=%u firmware-live=%u\n",
            backend_address_matches, nabu_ath10k_os_radio_powered());
        return;
    }
    IOLockLock(gate);
    backend = ops;
    valid = true;
    close_locked();
    IOLockUnlock(gate);
    native_ops = *ops;
    native_ops.power = station_power;
    native_ops.scan = station_scan;
    native_ops.join = station_join;
    native_ops.leave = station_leave;
    hakios_sta_attach(&native_ops);
    nabu_wireless_log("NABU WLAN SERVICE: native station present=%u power=%u; WPA2-PSK/CCMP association and data path offered\n",
        hakios_sta_present(), hakios_sta_powered());
}

extern "C" void nabu_ath10k_os_station_lost(int error)
{
    hakios_sta_lost(error); // Publication lock precedes the adapter gate, including ordinary AP loss.
    if (!gate) return;
    IOLockLock(gate);
    close_locked();
    IOLockUnlock(gate);
    nabu_wireless_log("NABU WLAN CONTROL: association lost error=%d; backend and power retained\n", error);
}

extern "C" void nabu_ath10k_os_station_fatal(int error)
{
    nabu_wireless_log("NABU WLAN CONTROL: backend firmware recovery requested error=%d\n", error);
    nabu_wlan_runtime_lost(); // Asynchronous stop; the driver recovery callback must return first.
}

extern "C" void nabu_ath10k_os_net_link(int up)
{
    if (!gate) return;
    IOLockLock(gate);
    if (up) pending_up = valid;
    else if (pending_up || committed) close_locked();
    IOLockUnlock(gate);
}

extern "C" void nabu_ath10k_os_net_input(const unsigned char *frame, unsigned long length)
{
    if (!gate) return;
    IOLockLock(gate);
    if (valid && committed) {
        // ifnet_input enqueues the copied packet; it does not synchronously run BSD output.
        hakios_net_input(frame, length);
        ++rx_accepted;
    } else ++rx_dropped;
    IOLockUnlock(gate);
}
