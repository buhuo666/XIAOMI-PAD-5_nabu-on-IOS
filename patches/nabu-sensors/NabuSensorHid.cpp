// SPDX-License-Identifier: BSD-2-Clause-Patent
// Physical SSC sample transport for the source-built 8796 kernel. This kernel
// has IOService/IOUserClient/IOSharedDataQueue, but no IOHIDEventService class.
// Conversion and HID event construction therefore belong to a userspace owner.
#include "NabuSensorHid.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOKitKeys.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOSharedDataQueue.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSArray.h>
#include <libkern/c++/OSDictionary.h>
#include <mach/kmod.h>

extern "C" kmod_info_t g_kernel_kmod_info;
extern "C" void nabu_sensor_hid_static_init(void)
    __asm__("__GLOBAL__sub_I_NabuSensorHid.cpp");

class NabuSensorSource;
class NabuSensorUserClient;
static IOLock *sourceLock;
static NabuSensorSource *sources[NabuSensorKindCount];
static NabuSensorControlHandler controlHandler;
static void *controlContext;
static bool classesConstructed;
static IOReturn initializationStatus=kIOReturnNotReady;

class NabuSensorSource : public IOService {
    OSDeclareDefaultStructors(NabuSensorSource)
public:
    NabuSensorStatus status{};
    NabuSensorUserClient *client=nullptr;
    uint64_t nextSequence=0;
    bool describe(const NabuSensorDescription &);
    void enqueue(NabuSensorRecord &);
    IOReturn newUserClient(task_t,void *,UInt32,OSDictionary *,IOUserClient **) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(NabuSensorSource,IOService)

class NabuSensorUserClient : public IOUserClient {
    OSDeclareDefaultStructors(NabuSensorUserClient)
    NabuSensorSource *source=nullptr;
    IOSharedDataQueue *queue=nullptr;
    IOMemoryDescriptor *memory=nullptr;
    mach_port_t notification=MACH_PORT_NULL;
    uint32_t generation=0;
    bool closing=false;
    IOReturn mappingStatus=kIOReturnSuccess;
    void closeQueue();
    static IOReturn getStatus(OSObject *,void *,IOExternalMethodArguments *);
    static IOReturn setControl(OSObject *,void *,IOExternalMethodArguments *);
public:
    bool start(IOService *) APPLE_KEXT_OVERRIDE;
    void free() APPLE_KEXT_OVERRIDE;
    IOReturn clientClose() APPLE_KEXT_OVERRIDE;
    IOReturn clientDied() APPLE_KEXT_OVERRIDE;
    IOReturn registerNotificationPort(mach_port_t,UInt32,io_user_reference_t) APPLE_KEXT_OVERRIDE;
    IOReturn clientMemoryForType(UInt32,IOOptionBits *,IOMemoryDescriptor **) APPLE_KEXT_OVERRIDE;
    IOReturn externalMethod(uint32_t,IOExternalMethodArguments *,IOExternalMethodDispatch *,OSObject *,void *) APPLE_KEXT_OVERRIDE;
    // Called under sourceLock. A retained old client can observe status changes
    // but cannot receive samples belonging to a resumed source generation.
    bool enqueue(const NabuSensorRecord &record) {
        return !closing&&queue&&generation==source->status.generation&&queue->enqueue((void *)&record,sizeof(record));
    }
};
OSDefineMetaClassAndStructors(NabuSensorUserClient,IOUserClient)

bool NabuSensorSource::describe(const NabuSensorDescription &description)
{
    const char *unit[]={"m/s^2","rad/s","uT","lux"};
    OSData *suid=OSData::withBytes(description.physical_suid,sizeof(description.physical_suid));
    if(!suid)return false;
    const bool applied=setProperty("NabuSensorABI",NabuSensorSourceAbi,32)&&
       setProperty("NabuSensorKind",description.kind,32)&&
       setProperty("Product",description.product)&&
       setProperty("Manufacturer",description.manufacturer)&&
       setProperty("NabuPhysicalSUID",suid)&&
       setProperty("NabuSampleUnit",unit[description.kind])&&
       setProperty("Transport","SSC")&&setProperty("Built-In",kOSBooleanTrue)&&
       setProperty("NabuNativeHIDPublished",kOSBooleanFalse);
    suid->release();
    if(!applied)return false;
    if(description.kind==NabuSensorAmbientLight){
        OSDictionary *pair=OSDictionary::withCapacity(2);
        OSArray *pairs=OSArray::withCapacity(1);
        OSNumber *page=OSNumber::withNumber(0xff00,32),*usage=OSNumber::withNumber(4,32);
        const bool als=pair&&pairs&&page&&usage&&pair->setObject("DeviceUsagePage",page)&&
            pair->setObject("DeviceUsage",usage)&&pairs->setObject(pair)&&
            setProperty("DeviceUsagePairs",pairs)&&setProperty("PrimaryUsagePage",0xff00,32)&&
            setProperty("PrimaryUsage",4,32);
        if(usage)usage->release();if(page)page->release();
        if(pairs)pairs->release();if(pair)pair->release();
        if(!als)return false;
    }
    status.description=description;
    return true;
}

void NabuSensorSource::enqueue(NabuSensorRecord &record)
{
    record.sequence=++nextSequence;
    if(!client)return;
    if(client->enqueue(record))++status.enqueued_records;
    else ++status.dropped_records;
}

IOReturn NabuSensorSource::newUserClient(task_t task,void *security,UInt32 type,
    OSDictionary *properties,IOUserClient **handler)
{
    if(type!=NabuSensorSourceOpenType)return kIOReturnUnsupported;
    const IOReturn privilege=IOUserClient::clientHasPrivilege(task,kIOClientPrivilegeAdministrator);
    if(privilege)return privilege;
    NabuSensorUserClient *connection=new NabuSensorUserClient;
    if(!connection)return kIOReturnNoMemory;
    if(!connection->initWithTask(task,security,type,properties)){
        connection->release();return kIOReturnNoResources;
    }
    connection->setProperty(kIOUserClientDefaultLockingKey,kOSBooleanTrue);
    connection->setProperty(kIOUserClientDefaultLockingSetPropertiesKey,kOSBooleanTrue);
    connection->setProperty(kIOUserClientDefaultLockingSingleThreadExternalMethodKey,kOSBooleanTrue);
    if(!connection->attach(this)){
        connection->release();return kIOReturnNoResources;
    }
    if(!connection->start(this)){
        connection->detach(this);connection->release();return kIOReturnBusy;
    }
    *handler=connection;
    return kIOReturnSuccess;
}

bool NabuSensorUserClient::start(IOService *provider)
{
    if(!IOUserClient::start(provider))return false;
    source=OSDynamicCast(NabuSensorSource,provider);
    if(!source)return false;
    queue=IOSharedDataQueue::withCapacity(64*1024);
    if(!queue)return false;
    // Keep this same descriptor for map and unmap. Returning a fresh descriptor
    // makes IOConnectUnmapMemory's identity lookup unable to find the mapping.
    memory=queue->getMemoryDescriptor();
    if(!memory)return false;
    IOLockLock(sourceLock);
    const bool accepted=source->status.active&&!source->client;
    if(accepted){
        generation=source->status.generation;
        source->client=this;
        NabuSensorRecord snapshot=source->status.latest;
        snapshot.flags|=NabuSensorRecordCurrentSnapshot;
        if(enqueue(snapshot))++source->status.enqueued_records;
        else ++source->status.dropped_records;
    }
    IOLockUnlock(sourceLock);
    return accepted;
}

void NabuSensorUserClient::closeQueue()
{
    mach_port_t old=MACH_PORT_NULL;
    IOLockLock(sourceLock);
    closing=true;
    if(source&&source->client==this)source->client=nullptr;
    if(queue)queue->setNotificationPort(MACH_PORT_NULL);
    old=notification;notification=MACH_PORT_NULL;
    IOLockUnlock(sourceLock);
    if(old!=MACH_PORT_NULL)releaseNotificationPort(old);
    // Same mapped-allocation lifetime rule as the GPU's verified dropViews:
    // remove user PTEs before IOSharedDataQueue releases its backing memory.
    if(memory&&!mappingStatus)while(IOMemoryMap *map=removeMappingForDescriptor(memory)){
        mappingStatus=map->unmap();map->release();
        if(mappingStatus)break;
    }
}

IOReturn NabuSensorUserClient::clientClose()
{
    closeQueue();terminate();return mappingStatus;
}
IOReturn NabuSensorUserClient::clientDied(){return clientClose();}
void NabuSensorUserClient::free()
{
    closeQueue();
    if(!mappingStatus){OSSafeReleaseNULL(memory);OSSafeReleaseNULL(queue);}
    else IOLog("NABU SENSOR SOURCE: queue unmap failed=%#x backing retained until reboot\n",mappingStatus);
    IOUserClient::free();
}

IOReturn NabuSensorUserClient::registerNotificationPort(mach_port_t port,UInt32 type,io_user_reference_t refcon)
{
    (void)refcon;
    if(type!=NabuSensorSourceQueueNotification){
        if(port!=MACH_PORT_NULL)releaseNotificationPort(port);
        return kIOReturnUnsupported;
    }
    IOLockLock(sourceLock);
    mach_port_t old=notification;
    const bool accepted=!closing&&queue;
    if(accepted){notification=port;queue->setNotificationPort(port);}
    IOLockUnlock(sourceLock);
    if(accepted){if(old!=MACH_PORT_NULL)releaseNotificationPort(old);return kIOReturnSuccess;}
    if(port!=MACH_PORT_NULL)releaseNotificationPort(port);
    return kIOReturnNotOpen;
}

IOReturn NabuSensorUserClient::clientMemoryForType(UInt32 type,IOOptionBits *options,IOMemoryDescriptor **descriptor)
{
    if(type!=NabuSensorSourceQueueMemory)return kIOReturnUnsupported;
    IOLockLock(sourceLock);
    const bool available=!closing&&memory;
    if(available){*options=0;memory->retain();*descriptor=memory;}
    IOLockUnlock(sourceLock);
    return available?kIOReturnSuccess:kIOReturnNotOpen;
}

IOReturn NabuSensorUserClient::getStatus(OSObject *object,void *,IOExternalMethodArguments *arguments)
{
    NabuSensorUserClient *connection=static_cast<NabuSensorUserClient *>(object);
    IOLockLock(sourceLock);
    const bool available=!connection->closing&&connection->source;
    if(available)memcpy(arguments->structureOutput,&connection->source->status,sizeof(NabuSensorStatus));
    IOLockUnlock(sourceLock);
    return available?kIOReturnSuccess:kIOReturnNotOpen;
}

IOReturn NabuSensorUserClient::setControl(OSObject *object,void *,IOExternalMethodArguments *arguments)
{
    NabuSensorUserClient *connection=static_cast<NabuSensorUserClient *>(object);
    const auto &request=*static_cast<const NabuSensorControlRequest *>(arguments->structureInput);
    if(request.control>NabuSensorBatchIntervalUs||request.reserved)return kIOReturnBadArgument;
    IOLockLock(sourceLock);
    NabuSensorSource *source=connection->source;
    const bool active=!connection->closing&&source&&source->status.active&&
        connection->generation==source->status.generation;
    NabuSensorControlHandler handler=controlHandler;
    void *context=controlContext;
    const uint32_t kind=active?source->status.description.kind:0;
    const uint32_t generation=active?source->status.generation:0;
    IOLockUnlock(sourceLock);
    if(!active)return kIOReturnNotReady;
    if(!handler)return kIOReturnUnsupported;
    const IOReturn result=handler(context,kind,request.control,request.microseconds);
    if(result)return result;
    IOLockLock(sourceLock);
    const bool same=!connection->closing&&source->status.active&&source->status.generation==generation;
    if(same){
        if(request.control==NabuSensorReportIntervalUs)source->status.report_interval_us=request.microseconds;
        else source->status.batch_interval_us=request.microseconds;
    }
    IOLockUnlock(sourceLock);
    return same?kIOReturnSuccess:kIOReturnAborted;
}

IOReturn NabuSensorUserClient::externalMethod(uint32_t selector,IOExternalMethodArguments *arguments,
    IOExternalMethodDispatch *,OSObject *,void *)
{
    static const IOExternalMethodDispatch methods[]={
        {getStatus,0,0,0,sizeof(NabuSensorStatus)},
        {setControl,0,sizeof(NabuSensorControlRequest),0,0},
    };
    if(selector>=sizeof(methods)/sizeof(methods[0]))return kIOReturnUnsupported;
    return IOUserClient::externalMethod(selector,arguments,
        const_cast<IOExternalMethodDispatch *>(&methods[selector]),this,nullptr);
}

extern "C" int32_t nabu_sensor_hid_initialize(void)
{
    if(classesConstructed)return initializationStatus;
    sourceLock=IOLockAlloc();
    if(!sourceLock)return kIOReturnNoMemory;
    void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if(!handle){IOLockFree(sourceLock);sourceLock=nullptr;return kIOReturnNoResources;}
    classesConstructed=true;
    nabu_sensor_hid_static_init();
    initializationStatus=OSMetaClass::postModLoad(handle);
    return initializationStatus;
}

extern "C" void nabu_sensor_hid_set_control_handler(NabuSensorControlHandler handler,void *context)
{
    if(initializationStatus!=kIOReturnSuccess)return;
    IOLockLock(sourceLock);controlHandler=handler;controlContext=context;IOLockUnlock(sourceLock);
}

static bool validSample(const NabuSensorDescription &description,const NabuSensorRecord &sample)
{
    if(description.abi_version!=NabuSensorSourceAbi||description.kind>=NabuSensorKindCount||
       sample.kind!=description.kind||!sample.mach_timestamp||
       !(description.physical_suid[0]|description.physical_suid[1])||
       !description.product[0]||!description.manufacturer[0]||
       !memchr(description.product,0,sizeof(description.product))||
       !memchr(description.manufacturer,0,sizeof(description.manufacturer)))return false;
    if(sample.value_count>4||sample.value_count<(sample.kind==NabuSensorAmbientLight?1u:3u))return false;
    for(unsigned i=0;i<sample.value_count;++i)
        if((sample.value_bits[i]&0x7f800000)==0x7f800000)return false;
    if(sample.kind==NabuSensorAmbientLight&&(sample.value_bits[0]&0x80000000)&&
       (sample.value_bits[0]&0x7fffffff))return false;
    return true;
}

extern "C" int32_t nabu_sensor_hid_submit(const NabuSensorDescription *description,const NabuSensorRecord *input)
{
    if(initializationStatus!=kIOReturnSuccess)return kIOReturnNotReady;
    if(!description||!input||!validSample(*description,*input))return kIOReturnBadArgument;
    IOLockLock(sourceLock);
    NabuSensorSource *source=sources[description->kind];
    bool created=false;
    if(!source){
        source=new NabuSensorSource;
        if(!source||!source->init()||!source->describe(*description)){
            OSSafeReleaseNULL(source);IOLockUnlock(sourceLock);return kIOReturnNoMemory;
        }
        IOService *platform=IOService::getPlatform();
        if(!source->attach(platform)){
            source->release();IOLockUnlock(sourceLock);return kIOReturnNoResources;
        }
        if(!source->start(platform)){
            source->detach(platform);source->release();IOLockUnlock(sourceLock);return kIOReturnNotReady;
        }
        source->setName("NabuSensorSource");
        sources[description->kind]=source;created=true;
    }
    if(source->status.active){
        if(memcmp(description->physical_suid,source->status.description.physical_suid,sizeof(description->physical_suid))||
           input->mach_timestamp<=source->status.latest.mach_timestamp){
            IOLockUnlock(sourceLock);return kIOReturnBadArgument;
        }
    }else{
        if(!created&&!source->describe(*description)){IOLockUnlock(sourceLock);return kIOReturnNoMemory;}
        ++source->status.generation;
        source->status.active=1;source->status.invalidation_reason=0;
        source->setProperty("NabuBackendActive",kOSBooleanTrue);
        source->setProperty("NabuGeneration",source->status.generation,32);
    }
    NabuSensorRecord record=*input;
    record.record_type=NabuSensorRecordSample;record.flags=0;record.reason=0;
    for(unsigned i=record.value_count;i<4;++i)record.value_bits[i]=0;
    source->enqueue(record);source->status.latest=record;++source->status.accepted_samples;
    IOLockUnlock(sourceLock);
    if(created){source->registerService();IOLog("NABU SENSOR SOURCE: kind=%u product=%s first-sample=1 HID=0\n",description->kind,description->product);}
    return kIOReturnSuccess;
}

extern "C" int32_t nabu_sensor_hid_invalidate(uint32_t kind,int32_t reason)
{
    if(initializationStatus!=kIOReturnSuccess)return kIOReturnNotReady;
    if(kind>=NabuSensorKindCount)return kIOReturnBadArgument;
    IOLockLock(sourceLock);
    NabuSensorSource *source=sources[kind];
    if(source){
        source->status.active=0;source->status.invalidation_reason=uint32_t(reason);
        source->setProperty("NabuBackendActive",kOSBooleanFalse);
        source->setProperty("NabuInvalidationReason",uint32_t(reason),32);
        NabuSensorRecord record{};record.kind=kind;record.record_type=NabuSensorRecordInvalidated;record.reason=uint32_t(reason);
        source->enqueue(record);source->status.latest=record;
    }
    IOLockUnlock(sourceLock);
    return source?kIOReturnSuccess:kIOReturnNotFound;
}
