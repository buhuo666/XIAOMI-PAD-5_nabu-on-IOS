// SPDX-License-Identifier: BSD-2-Clause-Patent
// Publish the installed APFS Data window through the original IOStorageFamily.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSString.h>
#include <machine/machine_routines.h>
#include <pexpert/pexpert.h>
#include <sys/errno.h>
#include "NabuDataBlock.h"
#include "NabuStorageApi.h"

class NabuDataBlock : public IOBlockStorageDevice {
    OSDeclareDefaultStructors(NabuDataBlock)
    static constexpr unsigned kWindow = 2;
    static constexpr unsigned kTransferBytes = 128 * 1024;
    IOLock *gate = nullptr;
    uint8_t *memory = nullptr;
    uint8_t *bounce = nullptr;
    uint64_t bytes = 0;

public:
    bool start(IOService *provider) override;
    void free() override;
    IOReturn doAsyncReadWrite(IOMemoryDescriptor *, UInt64, UInt64,
        IOStorageAttributes *, IOStorageCompletion *) override;
    IOReturn doSynchronizeCache() override;
    IOReturn doSynchronize(UInt64, UInt64, IOStorageSynchronizeOptions) override
        { return doSynchronizeCache(); }

    IOReturn doEjectMedia() override { return kIOReturnUnsupported; }
    IOReturn doFormatMedia(UInt64) override { return kIOReturnUnsupported; }
    UInt32 doGetFormatCapacities(UInt64 *, UInt32) const override { return 0; }
    char *getVendorString() override { return const_cast<char *>("Nabu"); }
    char *getProductString() override { return const_cast<char *>("APFS Data"); }
    char *getRevisionString() override { return const_cast<char *>("1.0"); }
    char *getAdditionalDeviceInfoString() override
        { return const_cast<char *>(memory ? "QEMU Data image" : "Installed iPadOS Data window"); }
    IOReturn reportBlockSize(UInt64 *value) override
        { *value = 512; return kIOReturnSuccess; }
    IOReturn reportMaxValidBlock(UInt64 *value) override
        { *value = bytes / 512 - 1; return kIOReturnSuccess; }
    IOReturn reportEjectability(bool *value) override
        { *value = false; return kIOReturnSuccess; }
    IOReturn reportRemovability(bool *value) override
        { *value = false; return kIOReturnSuccess; }
    IOReturn reportWriteProtection(bool *value) override
        { *value = false; return kIOReturnSuccess; }
    IOReturn reportMediaState(bool *present, bool *changed) override {
        *present = true;
        if (changed) *changed = false;
        return kIOReturnSuccess;
    }
    IOReturn getWriteCacheState(bool *value) override
        { *value = false; return kIOReturnSuccess; }
    IOReturn setWriteCacheState(bool enabled) override
        { return enabled ? kIOReturnUnsupported : kIOReturnSuccess; }
};

OSDefineMetaClassAndStructors(NabuDataBlock, IOBlockStorageDevice)

bool NabuDataBlock::start(IOService *provider)
{
    if (!IOBlockStorageDevice::start(provider)) return false;

    // The QEMU loader owns this RAM allocation for the whole boot.
    IORegistryEntry *map = IORegistryEntry::fromPath("/chosen/memory-map", gIODTPlane);
    if (map) {
        OSData *range = OSDynamicCast(OSData, map->getProperty("NabuDataDisk"));
        if (range) {
            uint64_t physical;
            memcpy(&physical, range->getBytesNoCopy(), sizeof(physical));
            memcpy(&bytes, static_cast<const uint8_t *>(range->getBytesNoCopy()) + 8, sizeof(bytes));
            memory = reinterpret_cast<uint8_t *>(ml_static_ptovirt(physical));
        }
        map->release();
    }
    if (!memory) {
        uint32_t enabled = 0;
        PE_parse_boot_argn("nabu-data", &enabled, sizeof(enabled));
        if (enabled != 1) return false;
        if (nabu_storage_prepare()) return false;
        bytes = nabu_storage_size(kWindow);
        if (!bytes) return false;
        bounce = static_cast<uint8_t *>(IOMalloc(kTransferBytes));
        if (!bounce) return false;
    }
    gate = IOLockAlloc();
    if (!gate) return false;

    OSDictionary *protocol = OSDictionary::withCapacity(2);
    OSString *type = OSString::withCString(kIOPropertyPhysicalInterconnectTypeVirtual);
    OSString *location = OSString::withCString(memory ? kIOPropertyInterconnectRAMKey : kIOPropertyInternalKey);
    protocol->setObject(kIOPropertyPhysicalInterconnectTypeKey, type);
    protocol->setObject(kIOPropertyPhysicalInterconnectLocationKey, location);
    setProperty(kIOPropertyProtocolCharacteristicsKey, protocol);
    type->release(); location->release(); protocol->release();
    setName("NabuDataBlock");
    IOLog("NABU DATA BLOCK: %s bytes=%llu logical-block=512\n",
        memory ? "QEMU RAM" : "UFS Data", static_cast<unsigned long long>(bytes));
    registerService();
    return true;
}

IOReturn NabuDataBlock::doAsyncReadWrite(IOMemoryDescriptor *buffer, UInt64 block,
    UInt64 count, IOStorageAttributes *, IOStorageCompletion *completion)
{
    // The published device is only the Data window, never the containing LUN.
    if (block > bytes / 512 || count > bytes / 512 - block) return kIOReturnBadArgument;
    const uint64_t length = count * 512;
    const uint64_t offset = block * 512;
    const bool write = buffer->getDirection() == kIODirectionOut;
    uint64_t done = 0;
    IOReturn status = kIOReturnSuccess;
    IOLockLock(gate);
    if (memory) {
        done = write ? buffer->readBytes(0, memory + offset, length)
                     : buffer->writeBytes(0, memory + offset, length);
    } else {
        while (done < length) {
            const uint64_t take = length - done < kTransferBytes ? length - done : kTransferBytes;
            if (write) {
                if (buffer->readBytes(done, bounce, take) != take ||
                    nabu_storage_write(kWindow, offset + done, bounce, take)) break;
            } else {
                if (nabu_storage_read(kWindow, offset + done, bounce, take) ||
                    buffer->writeBytes(done, bounce, take) != take) break;
            }
            done += take;
        }
    }
    if (done != length) status = kIOReturnIOError;
    IOLockUnlock(gate);
    completion->action(completion->target, completion->parameter, status, done);
    return kIOReturnSuccess;
}

IOReturn NabuDataBlock::doSynchronizeCache()
{
    IOLockLock(gate);
    int error = memory ? 0 : nabu_storage_sync(kWindow);
    IOLockUnlock(gate);
    return error ? kIOReturnIOError : kIOReturnSuccess;
}

void NabuDataBlock::free()
{
    if (bounce) IOFree(bounce, kTransferBytes);
    if (gate) IOLockFree(gate);
    IOBlockStorageDevice::free();
}

extern "C" int nabu_data_block_start(void)
{
    NabuDataBlock *device = new NabuDataBlock;
    if (!device) return ENOMEM;
    if (!device->init(nullptr)) { device->release(); return ENOMEM; }
    IOService *provider = IOService::getServiceRoot();
    if (!device->attach(provider)) { device->release(); return ENXIO; }
    if (!device->start(provider)) {
        device->detach(provider);
        device->release();
        return EIO;
    }
    device->release();
    return 0;
}
