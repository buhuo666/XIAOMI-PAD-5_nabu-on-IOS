// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NativeAES.cpp"
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <libkern/OSDebug.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
#include <sys/errno.h>

extern "C" void nabu_log_finish(void);

class NabuAES : public NativeAES {
    OSDeclareDefaultStructors(NabuAES)
    unsigned char nonceKey[16];
    unsigned uidTraceCount = 0;
public:
    bool start(IOService *) override;
    bool isKeySupported(unsigned selector) override;
    IOReturn performAES(void *,void *,task_t,unsigned long long,IOAESIV *,
        IOAESOperation,IOAESKeyData *,IOAESCompletion,void *) override;
    IOReturn performAES(IOMemoryDescriptor *,IOMemoryDescriptor *,unsigned long long,
        IOAESIV *,IOAESOperation,IOAESKeyData *,unsigned long long,unsigned long long,
        IOAESCompletion,void *) override;
};
OSDefineMetaClassAndStructors(NabuAES,NativeAES)

bool NabuAES::start(IOService *provider)
{
    IORegistryEntry *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
    OSData *key=chosen ? OSDynamicCast(OSData,chosen->getProperty("nabu-image4-nonce-key")) : nullptr;
    if (!key || key->getLength()!=sizeof(nonceKey)) {
        IOLog("NABU AES: missing persistent 16-byte software nonce key\n");
        if (chosen) chosen->release();
        return false;
    }
    memcpy(nonceKey,key->getBytesNoCopy(),sizeof(nonceKey));
    chosen->release();
    if (!NativeAES::start(provider)) return false;
    setProperty("NabuImage4SoftwareNonceKey",true);
    IOLog("NABU AES: persistent software nonce selector=2212 ready\n");
    return true;
}

bool NabuAES::isKeySupported(unsigned selector)
{
    bool supported=selector==2212 || NativeAES::isKeySupported(selector);
    if (native_aes_registered)
        IOLog("NABU AES: key selector=%u supported=%u\n",selector,supported);
    return supported;
}

IOReturn NabuAES::performAES(void *input,void *output,task_t task,unsigned long long bytes,
    IOAESIV *iv,IOAESOperation operation,IOAESKeyData *key,IOAESCompletion callback,void *refcon)
{
    if (native_aes_registered)
        IOLog("NABU AES: raw bytes=%llu operation=%u selector=%u bits=%u\n",
            bytes,operation,key ? key->selector : ~0U,key ? key->bits : 0);
    IOReturn result=NativeAES::performAES(input,output,task,bytes,iv,operation,key,callback,refcon);
    if (native_aes_registered) IOLog("NABU AES: raw result=0x%x\n",result);
    return result;
}

IOReturn NabuAES::performAES(IOMemoryDescriptor *input,IOMemoryDescriptor *output,
    unsigned long long bytes,IOAESIV *iv,IOAESOperation operation,IOAESKeyData *key,
    unsigned long long inputOffset,unsigned long long outputOffset,IOAESCompletion callback,void *refcon)
{
    if (native_aes_registered)
        IOLog("NABU AES: descriptor bytes=%llu operation=%u selector=%u bits=%u\n",
            bytes,operation,key ? key->selector : ~0U,key ? key->bits : 0);
    if (key && key->selector==2201 &&
        __atomic_fetch_add(&uidTraceCount,1,__ATOMIC_RELAXED)<2) {
        void *frames[20];
        unsigned count=OSBacktrace(frames,20);
        IOLog("NABU AES UID: frames=%u inputLength=%llu outputLength=%llu inputOffset=%llu outputOffset=%llu inPlace=%u callback=%u\n",
            count,input ? input->getLength() : 0,output ? output->getLength() : 0,
            inputOffset,outputOffset,input==output,callback!=nullptr);
        for (unsigned i=0;i<count;++i)
            IOLog("NABU AES UID: frame=%u address=%#llx\n",i,(unsigned long long)(uintptr_t)frames[i]);
    }
    // 20F66 Image4 encrypts a nonce seed with selector 2212, AES-128 and a
    // zero IV. Supply this port's persistent software key to the real CBC path.
    IOAESKeyData software={};
    IOAESKeyData *effective=key;
    if (key && key->selector==2212 && key->bits==128) {
        software=*key;
        memcpy(software.bytes,nonceKey,sizeof(nonceKey));
        software.selector=0;
        effective=&software;
    }
    IOReturn result=NativeAES::performAES(input,output,bytes,iv,operation,effective,
        inputOffset,outputOffset,callback,refcon);
    cc_clear(sizeof(software),&software);
    if (native_aes_registered) {
        IOLog("NABU AES: descriptor result=0x%x\n",result);
        // Only the measured Image4 nonce failure requires terminal capture.
        // FairPlay also submits unsupported hardware selectors; those must
        // return their real error without sealing all subsequent runtime logs.
        if (result==kIOReturnUnsupported && key && key->selector==2212) nabu_log_finish();
    }
    return result;
}

static void nabu_publish_defaults(thread_call_param_t,thread_call_param_t)
{
    // GenericARMPE excludes this boot-state node from ordinary nub creation.
    // AppleImage4's original personality attaches to the defaults platform nub.
    IORegistryEntry *entry=IORegistryEntry::fromPath("/defaults",gIODTPlane);
    IOPlatformDevice *defaults=new IOPlatformDevice;
    if (!entry || !defaults || !defaults->init(entry,gIODTPlane)) {
        IOLog("NABU AES: defaults platform device initialization failed\n");
        return;
    }
    entry->release();
    defaults->attach(IOService::getPlatform());
    defaults->registerService();
    defaults->release();
    IOLog("NABU AES: defaults platform device published\n");
}

extern "C" int nabu_aes_start(void)
{
    NabuAES *device=new NabuAES;
    if (!device || !device->init(nullptr)) return ENOMEM;
    IOService *root=IOService::getServiceRoot();
    if (!device->attach(root) || !device->start(root)) {
        IOLog("NABU AES: start failed kat=%u interface=%u\n",
            native_aes_kat_status,native_aes_interface_status);
        device->release();
        return EIO;
    }
    IOLog("NABU AES: software provider registered kat=%u interface=%u\n",
        native_aes_kat_status,native_aes_interface_status);
    device->release();
    thread_call_t publish=thread_call_allocate_with_priority(nabu_publish_defaults,nullptr,
        THREAD_CALL_PRIORITY_KERNEL);
    uint64_t deadline;
    clock_interval_to_deadline(5,NSEC_PER_SEC,&deadline);
    thread_call_enter_delayed(publish,deadline);
    IOLog("NABU AES: defaults publication scheduled after 5 seconds\n");
    return 0;
}
