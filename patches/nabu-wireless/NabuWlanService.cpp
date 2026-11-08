// SPDX-License-Identifier: BSD-2-Clause-Patent
// Publish the Nabu hardware to native services before adding station control.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
extern "C" {
#include <sys/hakios.net.h>
}
#include "NabuWirelessLog.h"

static hakios_net_link link;
static bool published;

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
    nabu_wireless_log("NABU WLAN SERVICE: en0 attached=%u link=down; native station control not yet attached\n", published);
}
