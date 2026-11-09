/* SPDX-License-Identifier: MIT */
#include "NabuGpuAcceleratorABI.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOUserClient.h>

extern "C" IOReturn native_adreno_new_user_client(IOService *,task_t,void *,UInt32,
    OSDictionary *,IOUserClient **,unsigned);

/* Metal discovers this service through the existing source-kernel base. The
 * userland bundle admits the test process and supplies the Metal device. */
class AGXAccelerator : public IOAcceleratorES {
    OSDeclareDefaultStructors(AGXAccelerator)
public:
    IOReturn newUserClient(task_t owningTask,void *securityID,UInt32 type,
        OSDictionary *properties,IOUserClient **handler) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(AGXAccelerator,IOAcceleratorES)

IOReturn AGXAccelerator::newUserClient(task_t owningTask,void *securityID,UInt32 type,
    OSDictionary *properties,IOUserClient **handler)
{
    /* The existing transport accepts 0x4147 and rejects stock IOGPU type 1. */
    return native_adreno_new_user_client(this,owningTask,securityID,type,properties,handler,0);
}

/* Both class initializers run in native_adreno_initialize_classes before this
 * function is called. The running NativeAdreno service owns the provider. */
extern "C" IOReturn native_adreno_accelerator_publish(IOService *provider,uint32_t chipId)
{
    static AGXAccelerator *accelerator=nullptr;
    if(!provider || accelerator) {
        return kIOReturnBadArgument;
    }
    AGXAccelerator *service=new AGXAccelerator;
    if(!service || !service->init()) {
        OSSafeReleaseNULL(service);
        return kIOReturnNoMemory;
    }
    service->setName("AGXAccelerator");
    if(!service->setProperty("MetalPluginName","NativeAdrenoMetal") ||
       !service->setProperty("MetalPluginClassName","NativeAdrenoMetalDevice")) {
        service->release();
        return kIOReturnNoMemory;
    }
    if(!service->attach(provider)) {
        service->release();
        return kIOReturnNoResources;
    }
    if(!service->start(provider)) {
        service->detach(provider);
        service->release();
        return kIOReturnNotReady;
    }
    accelerator=service;
    service->registerService();
    IOLog("NativeAdrenoA6xx: system Metal accelerator published chip=%08x plugin=NativeAdrenoMetal\n",chipId);
    return kIOReturnSuccess;
}
