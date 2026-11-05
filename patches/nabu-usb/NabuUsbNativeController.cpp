// SPDX-License-Identifier: BSD-2-Clause-Patent
// Nabu DWC3 adapter for the supplied 20F66 IOUSBDeviceFamily.
#include "IOUSBDeviceController20F66.h"
#include "NabuUsbNative.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOPlatformExpert.h>
#include <libkern/c++/OSArray.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSString.h>
#include <kern/clock.h>
#include <kern/task.h>
#include <mach/mach_time.h>

namespace {
bool putNumber(OSDictionary *dictionary, const char *key, uint32_t value)
{
    OSNumber *number = OSNumber::withNumber(value, 32);
    if (!number) return false;
    bool result = dictionary->setObject(key, number);
    number->release();
    return result;
}

bool putString(OSDictionary *dictionary, const char *key, const char *value)
{
    OSString *string = OSString::withCString(value);
    if (!string) return false;
    bool result = dictionary->setObject(key, string);
    string->release();
    return result;
}

bool appendString(OSArray *array, const char *value)
{
    OSString *string = OSString::withCString(value);
    if (!string) return false;
    bool result = array->setObject(string);
    string->release();
    return result;
}

OSDictionary *configuration(bool mux)
{
    OSDictionary *result = OSDictionary::withCapacity(4);
    OSArray *interfaces = OSArray::withCapacity(mux ? 2 : 1);
    if (!result || !interfaces) {
        if (result) result->release();
        if (interfaces) interfaces->release();
        return nullptr;
    }
    // MaxPower is the USB descriptor byte, in 2 mA units at USB 2 speed.
    bool ok = appendString(interfaces, "Reserved") &&
        (!mux || appendString(interfaces, "AppleUSBMux")) &&
        result->setObject("Interfaces", interfaces) &&
        putNumber(result, "Attributes", 0x80) &&
        putNumber(result, "MaxPower", 250) &&
        putString(result, "Description", mux ? "AppleUSBMux" : "Reserved");
    interfaces->release();
    if (!ok) { result->release(); return nullptr; }
    return result;
}

OSDictionary *deviceDescription()
{
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    if (!chosen) return nullptr;
    OSData *uuid = OSDynamicCast(OSData, chosen->getProperty("nabu-platform-uuid"));
    char serial[37] = {};
    unsigned used = 0;
    if (uuid) {
        const char *bytes = static_cast<const char *>(uuid->getBytesNoCopy());
        for (unsigned i = 0; i < uuid->getLength() && bytes[i]; ++i) {
            if (bytes[i] == '-') continue;
            if (used == sizeof(serial) - 1) { used = 0; break; }
            serial[used++] = bytes[i];
        }
    }
    if (!used) {
        IOLog("NABU NATIVE USB: missing device-derived nabu-platform-uuid\n");
        chosen->release();
        return nullptr;
    }
    OSDictionary *description = OSDictionary::withCapacity(12);
    OSArray *configurations = OSArray::withCapacity(2);
    OSDictionary *reserved = configuration(false);
    OSDictionary *mux = configuration(true);
    bool ok = description && configurations && reserved && mux;
    if (ok) {
        ok = configurations->setObject(reserved) && configurations->setObject(mux) &&
            description->setObject("ConfigurationDescriptors", configurations) &&
            putNumber(description, "vendorID", 0x05ac) &&
            putNumber(description, "productID", 0x12ab) &&
            putNumber(description, "deviceID", 0x0711) &&
            putNumber(description, "deviceClass", 0) &&
            putNumber(description, "deviceSubClass", 0) &&
            putNumber(description, "deviceProtocol", 0) &&
            putNumber(description, "BcdUSBVersion", 0x0200) &&
            putString(description, "manufacturerString", "Apple Inc.") &&
            putString(description, "productString", "iPad") &&
            putString(description, "serialNumber", serial);
        // The USB serial identifies this board. It is not a fabricated Lockdown
        // UDID. Only an existing native UDID property may populate that key.
        OSString *udid = OSDynamicCast(OSString, chosen->getProperty("uniqueDeviceID"));
        if (udid) ok = ok && description->setObject("uniqueDeviceID", udid);
    }
    if (reserved) reserved->release();
    if (mux) mux->release();
    if (configurations) configurations->release();
    chosen->release();
    if (!ok && description) { description->release(); description = nullptr; }
    return description;
}

unsigned endpointIndex(uint32_t address)
{
    return (address & 15) * 2 + ((address >> 7) & 1);
}

uint32_t endpointAddress(unsigned index)
{
    return (index / 2) | ((index & 1) ? 0x80 : 0);
}
}

class NabuUsbNativeController : public IOUSBDeviceController {
    OSDeclareDefaultStructors(NabuUsbNativeController)
    struct Pending {
        NativeUSBIORequest *request;
        Pending *next;
        uint64_t deadline;
        bool timedOut;
    };
    struct Endpoint {
        Pending *head = nullptr;
        Pending *tail = nullptr;
        bool submitted = false;
        bool dispatching = false;
        bool aborting = false;
        bool active = false;
    } endpoints[32];
    IOWorkLoop *loop = nullptr;
    bool connected = false;
    bool draining = false;
    bool onBus = false;
    uint16_t appliedAddress = 0;
    IOReturn configurationError = kIOReturnSuccess;
    unsigned submissions = 0;

    IOReturn submitHead(unsigned index);
    void startNext(unsigned index);
    void cancel(unsigned index);
    void cancelAll();
    void traceConfigurations(const char *phase);
    IOUSBDeviceControlRequest *control() const
    {
        // Exact native object field, recovered from the original controller.
        return *reinterpret_cast<IOUSBDeviceControlRequest *const *>(
            reinterpret_cast<const uint8_t *>(this) + 0x1b8);
    }
    static IOReturn finishStart(OSObject *object, void *, void *, void *, void *)
    {
        native_usb_finish_initialization(static_cast<NabuUsbNativeController *>(object));
        return kIOReturnSuccess;
    }
    static IOReturn beginEnumeration(OSObject *object, void *, void *, void *, void *)
    {
        // Creation is an explicit request to enumerate the connected test port.
        // ConnectDone cannot supply this initial intent: it requires RUN_STOP.
        static_cast<NabuUsbNativeController *>(object)->cable(true);
        return kIOReturnSuccess;
    }

public:
    bool start(IOService *provider) override;
    void stop(IOService *provider) override;
    void free() override;
    IOWorkLoop *getWorkLoop() const override { return loop; }
    void abiSlot175PlatformAction(uint32_t) override { (void)goOnBus(false); }
    IOReturn goOnBus(bool activate) override;
    bool abiSlot179CableConnected() override { return connected; }
    void handleStallEndpoint(uint32_t address, bool stall) override
        { nabu_dwc3_stall_endpoint(address, stall); }
    void handleAbortEndpoint(uint32_t address) override { cancel(endpointIndex(address)); }
    IOReturn handleSetAddressPreStatusPhase(uint16_t address) override
    {
        IOReturn status = nabu_dwc3_set_address(address);
        if (!status) appliedAddress = address;
        return status;
    }
    IOReturn abiSlot183SetAddressPostStatusPhase(uint16_t address) override
        { return address == appliedAddress ? kIOReturnSuccess : kIOReturnNotReady; }
    int32_t getConnectionSpeed() override
    {
        int32_t speed = nabu_dwc3_connection_speed();
        // Same provisional full-speed value as stock DWC2 before activation.
        return speed < 0 && connected ? 1 : speed;
    }
    IOReturn provideEndpointIDsForConfiguration(OSArray *, uint8_t *) override;
    void prepareConfiguration(OSArray *) override;
    IOReturn activateEndpoint(uint32_t, uint32_t, uint32_t, uint32_t, uint32_t) override;
    IOReturn deactivateEndpoint(uint32_t address) override;
    IOBufferMemoryDescriptor *abiSlot189AllocateBuffer(uint32_t options, uint64_t length) override
        { return IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task, options, length, 64); }
    bool isEndpointStalled(uint32_t address) override
        { return nabu_dwc3_endpoint_stalled(address); }
    void resetEndpointDataToggle(uint32_t address) override
        { nabu_dwc3_reset_toggle(address); }
    void abiSlot198ScheduleReenumeration() override { abiSlot205GoOffAndOnBus(); }
    IOReturn doRemoteWakeGated() override { return kIOReturnUnsupported; }
    IOReturn ioGated(NativeUSBIORequest *request) override;
    IOReturn abiSlot223Io(uint32_t endpoint, IOMemoryDescriptor *buffer,
        uint64_t length, NativeUSBCompletion *completion, uint64_t reserved, uint32_t timeoutMs) override;

    void poll(void (*callback)());
    void setup(const void *setup8);
    void abortControl();
    void outData(const void *data, uint32_t length)
        { native_usb_control_input_data(control(), data, length); }
    void reset();
    void cable(bool present);
    void complete(void *cookie, IOReturn status, uint32_t remaining);
};

OSDefineMetaClassAndStructors(NabuUsbNativeController, IOUSBDeviceController)
static NabuUsbNativeController *nativeController;

bool NabuUsbNativeController::start(IOService *provider)
{
    loop = IOWorkLoop::workLoop();
    if (!loop || !IOUSBDeviceController::start(provider)) return false;
    OSDictionary *description = deviceDescription();
    if (!description) { IOUSBDeviceController::stop(provider); return false; }
    setName("NabuUsbNativeController");
    // finish_initialization creates this explicit two-configuration description.
    // A stock standardBringup configurator would supply its one-config default.
    setProperty("ConfigurationType", "nabuNative");
    setProperty("DeviceDescription", description);
    setProperty("NabuUSBIdentitySource", "IODeviceTree:/chosen/nabu-platform-uuid");
    description->release();
    loop->runAction(finishStart, this);
    OSArray *configurations = *reinterpret_cast<OSArray **>(
        reinterpret_cast<uint8_t *>(this) + 0x158);
    if (!control() || !configurations || configurations->getCount() != 2) {
        IOLog("NABU NATIVE USB: native device creation incomplete\n");
        IOUSBDeviceController::stop(provider);
        return false;
    }
    loop->runAction(beginEnumeration, this);
    IOLog("NABU NATIVE USB: controller ready, config 1 Reserved, config 2 Reserved+AppleUSBMux; board-derived USB identity\n");
    return true;
}

void NabuUsbNativeController::stop(IOService *provider)
{
    (void)goOnBus(false);
    IOUSBDeviceController::stop(provider);
}

void NabuUsbNativeController::free()
{
    IOWorkLoop *ownedLoop = loop;
    IOUSBDeviceController::free();
    if (ownedLoop) ownedLoop->release();
}

IOReturn NabuUsbNativeController::goOnBus(bool activate)
{
    IOLog("NABU NATIVE USB: goOnBus activate=%u was=%u\n",activate,onBus);
    if (activate) traceConfigurations("goOnBus");
    if (!activate) {
        draining = true;
        cancelAll();
    }
    bool ok = nabu_dwc3_set_active(activate);
    if (ok) {
        onBus = activate;
        endpoints[0].active = endpoints[1].active = activate;
    }
    if (activate && ok) draining = false;
    return ok ? kIOReturnSuccess : kIOReturnIOError;
}

void NabuUsbNativeController::traceConfigurations(const char *phase)
{
    const auto *state = reinterpret_cast<const uint8_t *>(this);
    auto *all = *reinterpret_cast<OSArray *const *>(state + 0x158);
    auto *advertised = *reinterpret_cast<OSArray *const *>(state + 0x160);
    IOLog("NABU NATIVE USB: configurations phase=%s all=%u advertised=%u speed=%d\n",
          phase, all ? all->getCount() : 0, advertised ? advertised->getCount() : 0,
          getConnectionSpeed());
    if (!all) return;
    for (unsigned i = 0; i < all->getCount(); ++i) {
        const auto *configuration = reinterpret_cast<const uint8_t *>(all->getObject(i));
        IOLog("NABU NATIVE USB: configuration index=%u extended=%u locked=%u\n",
              i, configuration[0x31], configuration[0x32]);
    }
}

IOReturn NabuUsbNativeController::provideEndpointIDsForConfiguration(OSArray *interfaces,
    uint8_t *ids)
{
    unsigned inBase = 1, outBase = 1, output = 0;
    for (unsigned i = 0; i < interfaces->getCount(); ++i) {
        auto *interface = reinterpret_cast<IOUSBDeviceInterface *>(interfaces->getObject(i));
        int32_t alternatives = native_usb_interface_alternate_count(interface);
        unsigned maxIn = 0, maxOut = 0;
        for (int32_t alternate = 0; alternate < alternatives; ++alternate) {
            unsigned inUsed = 0, outUsed = 0;
            int32_t count = native_usb_interface_pipe_count(interface, alternate);
            for (int32_t pipeIndex = 0; pipeIndex < count; ++pipeIndex) {
                IOUSBDevicePipe *pipe = native_usb_interface_get_pipe(interface, pipeIndex, alternate);
                uint32_t direction = native_usb_pipe_direction(pipe);
                unsigned number;
                if (direction == 1) number = inBase + inUsed++;
                else if (direction == 0) number = outBase + outUsed++;
                else return kIOReturnUnsupported;
                if (number > 15) return kIOReturnNoResources;
                ids[output++] = number | (direction == 1 ? 0x80 : 0);
            }
            if (inUsed > maxIn) maxIn = inUsed;
            if (outUsed > maxOut) maxOut = outUsed;
        }
        inBase += maxIn;
        outBase += maxOut;
    }
    return kIOReturnSuccess;
}

void NabuUsbNativeController::prepareConfiguration(OSArray *)
{
    configurationError = kIOReturnSuccess;
    bool previous = draining;
    draining = true;
    for (unsigned i = 2; i < 32; ++i) {
        if (!endpoints[i].active) continue;
        IOReturn result = deactivateEndpoint(endpointAddress(i));
        if (result) configurationError = result;
    }
    draining = previous;
    if (configurationError)
        IOLog("NABU NATIVE USB: previous endpoint release failed %#x\n", configurationError);
}

IOReturn NabuUsbNativeController::activateEndpoint(uint32_t address, uint32_t type,
    uint32_t maxPacket, uint32_t interval, uint32_t properties)
{
    IOLog("NABU NATIVE USB: activate ep=%x type=%u packet=%u interval=%u properties=%x\n",
        address,type,maxPacket,interval,properties);
    if (configurationError) return configurationError;
    if ((address & ~0x8fU) || type == 1 || properties) return kIOReturnUnsupported;
    IOReturn status = nabu_dwc3_activate_endpoint(address, type, maxPacket, interval);
    if (!status) endpoints[endpointIndex(address)].active = true;
    return status;
}

IOReturn NabuUsbNativeController::deactivateEndpoint(uint32_t address)
{
    unsigned index = endpointIndex(address);
    cancel(index);
    IOReturn status = nabu_dwc3_deactivate_endpoint(address);
    if (!status) endpoints[index].active = false;
    return status;
}

IOReturn NabuUsbNativeController::submitHead(unsigned index)
{
    Endpoint &endpoint = endpoints[index];
    Pending *pending = endpoint.head;
    uint32_t timeout = pending->request->options; // Native +0x2c is milliseconds.
    if (!timeout && (pending->request->endpoint & 0x80)) timeout = 5000;
    pending->deadline = 0;
    if (timeout) clock_interval_to_deadline(timeout, NSEC_PER_MSEC, &pending->deadline);
    endpoint.submitted = true;
    IOReturn result = nabu_dwc3_submit(pending->request->endpoint,
        pending->request->buffer, static_cast<uint32_t>(pending->request->lengthOrFrameCount), pending);
    if (result) endpoint.submitted = false;
    return result;
}

IOReturn NabuUsbNativeController::abiSlot223Io(uint32_t endpoint, IOMemoryDescriptor *buffer,
    uint64_t length, NativeUSBCompletion *completion, uint64_t reserved, uint32_t timeoutMs)
{
    if (!(endpoint & 15) || submissions < 16)
        IOLog("NABU NATIVE USB: native io ep=%x length=%llu bufferLength=%llu direction=%u completion=%u timeout=%u\n",
            endpoint,length,buffer ? buffer->getLength() : 0,
            buffer ? static_cast<unsigned>(buffer->getDirection()) : 0,
            completion && completion->action,timeoutMs);
    IOReturn result = IOUSBDeviceController::abiSlot223Io(endpoint,buffer,length,completion,reserved,timeoutMs);
    if (result) IOLog("NABU NATIVE USB: native io rejected ep=%x status=%x\n",endpoint,result);
    return result;
}

IOReturn NabuUsbNativeController::ioGated(NativeUSBIORequest *request)
{
    if (submissions++ < 16)
        IOLog("NABU NATIVE USB: submit ep=%x length=%llu timeout=%u iso=%u draining=%u onBus=%u active=%u\n",
            request->endpoint,request->lengthOrFrameCount,request->options,request->isIsochronous,
            draining,onBus,endpoints[endpointIndex(request->endpoint)].active);
    if (draining || !onBus) return kIOReturnNotReady;
    if (request->isIsochronous) return kIOReturnUnsupported;
    if ((request->endpoint & ~0x8fU) || request->lengthOrFrameCount > UINT32_MAX)
        return kIOReturnBadArgument;
    Endpoint &endpoint = endpoints[endpointIndex(request->endpoint)];
    if (!endpoint.active || endpoint.aborting) return kIOReturnNotReady;
    Pending *pending = static_cast<Pending *>(IOMalloc(sizeof(Pending)));
    if (!pending) return kIOReturnNoMemory;
    *pending = {request, nullptr, 0, false};
    bool wasEmpty = !endpoint.head;
    if (endpoint.tail) endpoint.tail->next = pending;
    else endpoint.head = pending;
    endpoint.tail = pending;
    if (!wasEmpty || endpoint.dispatching) return kIOReturnSuccess;
    IOReturn result = submitHead(endpointIndex(request->endpoint));
    if (result) {
        IOLog("NABU NATIVE USB: submit rejected ep=%x status=%x\n",request->endpoint,result);
        endpoint.head = endpoint.tail = nullptr;
        IOFree(pending, sizeof(Pending));
    }
    return result;
}

void NabuUsbNativeController::startNext(unsigned index)
{
    Endpoint &endpoint = endpoints[index];
    if (draining || endpoint.aborting || endpoint.dispatching || endpoint.submitted) return;
    endpoint.dispatching = true;
    while (endpoint.head && !endpoint.submitted && !draining && !endpoint.aborting) {
        IOReturn result = submitHead(index);
        if (!result) break;
        Pending *failed = endpoint.head;
        NativeUSBIORequest *request = failed->request;
        endpoint.head = failed->next;
        if (!endpoint.head) endpoint.tail = nullptr;
        IOFree(failed, sizeof(Pending));
        request->status = result;
        request->transferredOrFrameList = 0;
        native_usb_complete_io(this, request);
    }
    endpoint.dispatching = false;
}

void NabuUsbNativeController::complete(void *cookie, IOReturn status, uint32_t remaining)
{
    Pending *pending = static_cast<Pending *>(cookie);
    NativeUSBIORequest *request = pending->request;
    unsigned index = endpointIndex(request->endpoint);
    Endpoint &endpoint = endpoints[index];
    endpoint.head = pending->next;
    if (!endpoint.head) endpoint.tail = nullptr;
    endpoint.submitted = false;
    if (pending->timedOut) status = kIOReturnTimeout;
    IOFree(pending, sizeof(Pending));
    request->status = status;
    // The DWC3 transport reports unreceived bytes; DeviceFamily's completion
    // consumes actual bytes transferred (dataStageWriteCompletion adds them).
    request->transferredOrFrameList = request->lengthOrFrameCount - remaining;
    native_usb_complete_io(this, request);
    startNext(index);
}

void NabuUsbNativeController::cancel(unsigned index)
{
    Endpoint &endpoint = endpoints[index];
    bool wasAborting = endpoint.aborting;
    endpoint.aborting = true;
    if (endpoint.submitted) nabu_dwc3_abort_endpoint(endpointAddress(index));
    while (endpoint.head) {
        Pending *pending = endpoint.head;
        NativeUSBIORequest *request = pending->request;
        endpoint.head = pending->next;
        if (!endpoint.head) endpoint.tail = nullptr;
        IOFree(pending, sizeof(Pending));
        request->status = kIOReturnAborted;
        request->transferredOrFrameList = 0;
        native_usb_complete_io(this, request);
    }
    endpoint.aborting = wasAborting;
}

void NabuUsbNativeController::cancelAll()
{
    for (unsigned i = 0; i < 32; ++i) cancel(i);
}

void NabuUsbNativeController::poll(void (*callback)())
{
    callback();
    uint64_t now = mach_absolute_time();
    for (unsigned i = 0; i < 32; ++i) {
        Endpoint &endpoint = endpoints[i];
        Pending *pending = endpoint.head;
        if (!endpoint.submitted || !pending->deadline || now < pending->deadline) continue;
        endpoint.aborting = true;
        pending->timedOut = true;
        nabu_dwc3_abort_endpoint(endpointAddress(i));
        endpoint.aborting = false;
        startNext(i);
    }
}

void NabuUsbNativeController::setup(const void *setup8)
{
    const auto *bytes = static_cast<const uint8_t *>(setup8);
    if (bytes[0] == 0x80 && bytes[1] == 6 && bytes[3] == 2)
        traceConfigurations("getConfigDescriptor");
    native_usb_control_input_setup(control(), setup8);
    IOReturn result = native_usb_control_process_setup(control());
    if (result) {
        IOLog("NABU NATIVE USB: setup processing returned %#x\n", result);
        nabu_dwc3_stall_endpoint(0, true);
    }
}

void NabuUsbNativeController::abortControl()
{
    bool previous = draining;
    draining = true;
    cancel(0);
    cancel(1);
    native_usb_control_reset(control());
    draining = previous;
}

void NabuUsbNativeController::reset()
{
    draining = true;
    cancelAll();
    for (unsigned i = 2; i < 32; ++i) endpoints[i].active = false;
    configurationError = kIOReturnSuccess;
    native_usb_control_reset(control());
    IOUSBDeviceController::handleUSBReset();
    draining = false;
}

void NabuUsbNativeController::cable(bool present)
{
    if (connected == present) return;
    connected = present;
    if (present) handleUSBCableConnect();
    else {
        draining = true;
        cancelAll();
        handleUSBCableDisconnect();
    }
}

extern "C" bool nabu_native_usb_create_controller()
{
    if (nativeController) return true;
    auto *controller = new NabuUsbNativeController;
    if (!controller) return false;
    if (!controller->init(static_cast<OSDictionary *>(nullptr))) {
        controller->release(); return false;
    }
    IOService *provider = IOService::getPlatform();
    if (!controller->attach(provider)) { controller->release(); return false; }
    nativeController = controller;
    if (!controller->start(provider)) {
        nativeController = nullptr;
        controller->detach(provider);
        controller->release();
        return false;
    }
    return true;
}

static IOReturn runPoll(OSObject *object, void *callback, void *, void *, void *)
{
    static_cast<NabuUsbNativeController *>(object)->poll(reinterpret_cast<void (*)()>(callback));
    return kIOReturnSuccess;
}

extern "C" void nabu_native_usb_poll(void (*callback)())
{
    if (nativeController)
        nativeController->getWorkLoop()->runAction(runPoll, nativeController,
            reinterpret_cast<void *>(callback));
}
// These entry points are dispatched by the DWC3 poll callback while runPoll owns
// the workloop gate, including nested completions from abort_endpoint.
extern "C" void nabu_native_usb_setup(const void *setup8)
    { nativeController->setup(setup8); }
extern "C" void nabu_native_usb_out_data(const void *data, uint32_t length)
    { nativeController->outData(data, length); }
extern "C" void nabu_native_usb_bus_reset()
    { nativeController->reset(); }
extern "C" void nabu_native_usb_abort_control()
    { nativeController->abortControl(); }
extern "C" void nabu_native_usb_connected()
    { nativeController->cable(true); }
extern "C" void nabu_native_usb_disconnected()
    { nativeController->cable(false); }
extern "C" void nabu_native_usb_transfer_done(void *cookie, IOReturn status, uint32_t remaining)
    { nativeController->complete(cookie, status, remaining); }
