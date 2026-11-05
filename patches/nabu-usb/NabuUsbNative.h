// DWC3 transport and the stock 20F66 USB device family share one workloop gate.
#pragma once
#if !defined(NABU_USB_HOST_TEST)
#include <IOKit/IOReturn.h>
#endif
#include <stdint.h>
class IOMemoryDescriptor;
extern "C" {
int nabu_power_usb_present();
bool nabu_dwc3_set_active(bool active);
IOReturn nabu_dwc3_activate_endpoint(uint32_t address, uint32_t type,
    uint32_t maxPacket, uint32_t interval);
IOReturn nabu_dwc3_deactivate_endpoint(uint32_t address);
void nabu_dwc3_abort_endpoint(uint32_t address);
void nabu_dwc3_stall_endpoint(uint32_t address, bool stalled);
bool nabu_dwc3_endpoint_stalled(uint32_t address);
IOReturn nabu_dwc3_set_address(uint16_t address);
IOReturn nabu_dwc3_submit(uint32_t address, IOMemoryDescriptor *buffer,
    uint32_t length, void *cookie);
int nabu_dwc3_connection_speed();
void nabu_dwc3_reset_toggle(uint32_t address);

bool nabu_native_usb_create_controller();
void nabu_native_usb_poll(void (*poll)());
void nabu_native_usb_setup(const void *setup8);
void nabu_native_usb_out_data(const void *data, uint32_t length);
void nabu_native_usb_bus_reset();
void nabu_native_usb_abort_control();
void nabu_native_usb_connected();
void nabu_native_usb_disconnected();
void nabu_native_usb_transfer_done(void *cookie, IOReturn status, uint32_t remaining);
}
