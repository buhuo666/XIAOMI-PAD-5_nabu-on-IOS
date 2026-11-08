// SPDX-License-Identifier: BSD-2-Clause-Patent
// Stable native interface and the scan/power boundary of the Nabu backend.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
extern "C" {
#include <sys/hakios.net.h>
#include <sys/hakios.sta.h>
#include <sys/errno.h>
void hakios_sta_invalidate(int error);
}
#include "NabuWirelessLog.h"

static hakios_net_link link;
static bool published;
static bool backend_address_matches;
static const hakios_sta_ops *backend;
static hakios_sta_ops native_ops;
extern "C" int nabu_ath10k_os_radio_powered();

static bool transmit_unavailable(mbuf_t, size_t)
{
    return false;
}

extern "C" void nabu_wlan_service_publish()
{
    if (published) return;
    IORegistryEntry *node = IORegistryEntry::fromPath("/wlan", gIODTPlane);
    if (!node) return; // The boot chain explicitly selects native service discovery.
    OSData *mac = OSDynamicCast(OSData, node->getProperty("local-mac-address"));
    if (!mac || mac->getLength() != sizeof(link.address)) {
        node->release();
        nabu_wireless_log("NABU WLAN SERVICE: device address unavailable; interface not published\n");
        return;
    }
    memcpy(link.address, mac->getBytesNoCopy(), sizeof(link.address));
    node->release();
    link.name = "Nabu WCN399x ath10k";
    link.unit = 0;
    link.wireless = true;
    link.up = false;
    link.transmit = transmit_unavailable;
    published = hakios_net_attach(&link);
    nabu_wireless_log("NABU WLAN SERVICE: en0 attached=%u link=down; awaiting backend station offer\n", published);
}

static int station_power(bool on)
{
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

extern "C" void nabu_wlan_service_invalidate(int error)
{
    // Fatal retirement is nonblocking; the driver's withdraw drains native calls.
    hakios_sta_invalidate(error);
    if (published) hakios_net_link_state(false);
}

extern "C" void nabu_ath10k_os_net_attach(const unsigned char *address)
{
    backend_address_matches = published && !memcmp(link.address, address, sizeof(link.address));
    nabu_wireless_log("NABU WLAN SERVICE: backend address matches stable en0=%u\n", backend_address_matches);
}

extern "C" void nabu_ath10k_os_station(const hakios_sta_ops *ops)
{
    if (!ops) {
        hakios_sta_attach(nullptr); // Driver worker only: wait before backend memory is freed.
        backend = nullptr;
        if (published) hakios_net_link_state(false);
        nabu_wireless_log("NABU WLAN SERVICE: station withdrawn and native calls drained\n");
        return;
    }
    if (!backend_address_matches || !nabu_ath10k_os_radio_powered()) {
        nabu_wireless_log("NABU WLAN SERVICE: station offer rejected: address=%u firmware-live=%u\n",
            backend_address_matches, nabu_ath10k_os_radio_powered());
        return;
    }
    backend = ops;
    native_ops = *ops;
    native_ops.power = station_power;
    native_ops.scan = station_scan;
    native_ops.join = nullptr; // Data-plane integration is required before association.
    hakios_sta_attach(&native_ops);
    nabu_wireless_log("NABU WLAN SERVICE: native scan/power station present=%u power=%u; association unavailable\n",
        hakios_sta_present(), hakios_sta_powered());
}

extern "C" void nabu_ath10k_os_station_lost(int error)
{
    if (published) hakios_net_link_state(false);
    hakios_sta_lost(error); // An AP loss does not retire the firmware or shared BT resources.
}

extern "C" void nabu_ath10k_os_net_link(int up)
{
    if (published) hakios_net_link_state(false);
    if (up) nabu_wireless_log("NABU WLAN SERVICE: link-up refused: association/data path unavailable\n");
}

extern "C" void nabu_ath10k_os_net_input(const unsigned char *, unsigned long)
{
    // No associated BSD link in this scan/power implementation.
}
