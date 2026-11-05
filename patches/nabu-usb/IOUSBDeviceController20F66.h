// Recovered from the supplied iPad7,11 iPadOS 16.5 / 20F66 arm64 kernel.
// Frozen ABI scaffold. Parent validated the original class-size assertions by compilation.
// EP0/helper additions still require the parent build. Bind reference-vtable slots to
// controller-abi.json; abiSlot names are analyst aliases, not Apple symbols.
// Non-pure slots without recovered signatures must only be inherited, not called
// from newly compiled C++. All runtime targets must be translated through the
// prelink module extents; original kernel virtual addresses are not runtime addresses.
#pragma once
#include <IOKit/IOService.h>
#include <stdint.h>
class OSArray;
class IOBufferMemoryDescriptor;
class IOMemoryDescriptor;
class IODMACommand;
class IOUSBDeviceControlRequest;
class IOUSBDeviceInterface;
class IOUSBDevicePipe;

struct NativeUSBCompletion {
    void *target;
    void (*action)(void *target, void *parameter, IOReturn status, uint32_t bytesTransferred);
    void *parameter;
};
struct NativeUSBIORequest {
    uint32_t endpoint;               // +0x00, USB address including bit 7
    uint32_t reserved04;
    IOMemoryDescriptor *buffer;      // +0x08, retained by family
    IODMACommand *dmaCommand;        // +0x10, hardware-owned while mapped
    uint64_t opaque18[2];            // +0x18, not yet assigned semantic names
    IOReturn status;                // +0x28
    uint32_t options;               // +0x2c
    uint8_t isIsochronous;          // +0x30
    uint8_t retainRequest;          // +0x31, complete helper skips release/free
    uint8_t reserved32[6];
    uint64_t opaque38;
    uint64_t lengthOrFrameCount;     // +0x40
    uint64_t transferredOrFrameList; // +0x48, actual bytes transferred (low 32 bits)
    NativeUSBCompletion completion; // +0x50
};
static_assert(sizeof(NativeUSBIORequest) == 0x68, "20F66 request ABI");
static_assert(sizeof(NativeUSBCompletion) == 0x18, "20F66 completion ABI");

class IOUSBDeviceController : public IOService {
    OSDeclareAbstractStructors(IOUSBDeviceController)
public:
    bool start(IOService *provider) override;
    void stop(IOService *provider) override;
    void free() override;
    IOReturn setProperties(OSObject *properties) override;
    IOReturn callPlatformFunction(const OSSymbol *functionName, bool waitForFunction,
        void *param1, void *param2, void *param3, void *param4) override;
    virtual void abiSlot168(); // 168: 0x540; inherit only, signature not recovered
    virtual void abiSlot169(); // 169: 0x548; inherit only, signature not recovered
    virtual void abiSlot170(); // 170: 0x550; inherit only, signature not recovered
    virtual void abiSlot171(); // 171: 0x558; inherit only, signature not recovered
    virtual void abiSlot172(); // 172: 0x560; inherit only, signature not recovered
    virtual void abiSlot173(); // 173: 0x568; inherit only, signature not recovered
    virtual void abiSlot174(); // 174: 0x570; inherit only, signature not recovered
    virtual void abiSlot175PlatformAction(uint32_t action) = 0; // 175: 0x578
    virtual void abiSlot176(); // 176: 0x580; inherit only, signature not recovered
    virtual IOReturn goOnBus(bool activate) = 0; // 177: 0x588
    virtual void abiSlot178(); // 178: 0x590; inherit only, signature not recovered
    virtual bool abiSlot179AccessoryResistorSwap() = 0; // 179: 0x598
    virtual void handleStallEndpoint(uint32_t endpoint, bool stall) = 0; // 180: 0x5a0
    virtual void handleAbortEndpoint(uint32_t endpoint) = 0; // 181: 0x5a8
    virtual IOReturn handleSetAddressPreStatusPhase(uint16_t address) = 0; // 182: 0x5b0
    virtual IOReturn abiSlot183SetAddressPostStatusPhase(uint16_t address) = 0; // 183: 0x5b8
    virtual int32_t getConnectionSpeed() = 0; // 184: 0x5c0
    virtual IOReturn provideEndpointIDsForConfiguration(OSArray *interfaces, uint8_t *endpointIDs) = 0; // 185: 0x5c8
    virtual void prepareConfiguration(OSArray *interfaces) = 0; // 186: 0x5d0
    virtual IOReturn activateEndpoint(uint32_t endpoint, uint32_t type, uint32_t maxPacketSize, uint32_t interval, uint32_t pipeProperties) = 0; // 187: 0x5d8
    virtual IOReturn deactivateEndpoint(uint32_t endpoint) = 0; // 188: 0x5e0
    virtual IOBufferMemoryDescriptor * abiSlot189AllocateBuffer(uint32_t options, uint64_t length) = 0; // 189: 0x5e8
    virtual void abiSlot190(); // 190: 0x5f0; inherit only, signature not recovered
    virtual void abiSlot191(); // 191: 0x5f8; inherit only, signature not recovered
    virtual bool isEndpointStalled(uint32_t endpoint) = 0; // 192: 0x600
    virtual void resetEndpointDataToggle(uint32_t endpoint) = 0; // 193: 0x608
    virtual void abiSlot194(); // 194: 0x610; inherit only, signature not recovered
    virtual void handleUSBSuspend(); // 195: 0x618
    virtual void handleUSBReset(); // 196: 0x620
    virtual void handleUSBResume(); // 197: 0x628
    virtual void abiSlot198ScheduleReenumeration() = 0; // 198: 0x630
    virtual void abiSlot199(); // 199: 0x638; inherit only, signature not recovered
    virtual void abiSlot200(); // 200: 0x640; inherit only, signature not recovered
    virtual IOReturn doRemoteWakeGated() = 0; // 201: 0x648
    virtual void abiSlot202(); // 202: 0x650; inherit only, signature not recovered
    virtual void handleUSBCableConnect(); // 203: 0x658
    virtual void handleUSBCableDisconnect(); // 204: 0x660
    virtual void abiSlot205GoOffAndOnBus(); // 205: 0x668
    virtual void abiSlot206(); // 206: 0x670; inherit only, signature not recovered
    virtual void abiSlot207(); // 207: 0x678; inherit only, signature not recovered
    virtual void abiSlot208(); // 208: 0x680; inherit only, signature not recovered
    virtual void abiSlot209(); // 209: 0x688; inherit only, signature not recovered
    virtual void abiSlot210(); // 210: 0x690; inherit only, signature not recovered
    virtual void abiSlot211(); // 211: 0x698; inherit only, signature not recovered
    virtual void abiSlot212(); // 212: 0x6a0; inherit only, signature not recovered
    virtual void abiSlot213(); // 213: 0x6a8; inherit only, signature not recovered
    virtual void abiSlot214(); // 214: 0x6b0; inherit only, signature not recovered
    virtual void abiSlot215(); // 215: 0x6b8; inherit only, signature not recovered
    virtual void abiSlot216(); // 216: 0x6c0; inherit only, signature not recovered
    virtual void abiSlot217(); // 217: 0x6c8; inherit only, signature not recovered
    virtual void abiSlot218(); // 218: 0x6d0; inherit only, signature not recovered
    virtual void abiSlot219(); // 219: 0x6d8; inherit only, signature not recovered
    virtual void abiSlot220(); // 220: 0x6e0; inherit only, signature not recovered
    virtual IOUSBDeviceControlRequest * abiSlot221CreateControlRequest(); // 221: 0x6e8
    virtual void abiSlot222(); // 222: 0x6f0; inherit only, signature not recovered
    virtual IOReturn abiSlot223Io(uint32_t endpoint, IOMemoryDescriptor *buffer,
        uint64_t length, NativeUSBCompletion *completion, uint64_t reserved, uint32_t timeoutMs);
    virtual void abiSlot224(); // 224: 0x700; inherit only, signature not recovered
    virtual IOReturn ioGated(NativeUSBIORequest *request) = 0; // 225: 0x708
    virtual NativeUSBIORequest * abiSlot226AllocateIORequest(); // 226: 0x710
    virtual void abiSlot227FreeIORequest(NativeUSBIORequest *request); // 227: 0x718
    virtual void abiSlot228(); // 228: 0x720; inherit only, signature not recovered
    virtual void abiSlot229(); // 229: 0x728; inherit only, signature not recovered
    virtual void abiSlot230(); // 230: 0x730; inherit only, signature not recovered
    virtual void abiSlot231(); // 231: 0x738; inherit only, signature not recovered
private:
    uint8_t nativeState[0x170];
};
static_assert(sizeof(IOService) == 0x88, "20F66 IOService base ABI");
static_assert(sizeof(IOUSBDeviceController) == 0x1f8, "20F66 controller ABI");

// Synthetic C symbols for non-virtual stock helpers; resolver binds these names.
extern "C" {
void native_usb_finish_initialization(IOUSBDeviceController *controller);
IOReturn native_usb_create_device(IOUSBDeviceController *controller, OSDictionary *description);
void native_usb_complete_io(IOUSBDeviceController *controller, NativeUSBIORequest *request);
void native_usb_control_input_setup(IOUSBDeviceControlRequest *control, const void *setup8);
IOReturn native_usb_control_process_setup(IOUSBDeviceControlRequest *control);
void native_usb_control_input_data(IOUSBDeviceControlRequest *control, const void *data, uint32_t length);
void native_usb_control_reset(IOUSBDeviceControlRequest *control);
int32_t native_usb_interface_alternate_count(IOUSBDeviceInterface *interface);
int32_t native_usb_interface_pipe_count(IOUSBDeviceInterface *interface, uint8_t alternate);
IOUSBDevicePipe *native_usb_interface_get_pipe(IOUSBDeviceInterface *interface, int32_t pipeIndex, uint8_t alternate);
uint32_t native_usb_pipe_direction(IOUSBDevicePipe *pipe); // 0=OUT, 1=IN
}
