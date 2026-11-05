// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NativeAES.cpp"
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <sys/errno.h>

class NabuAES : public NativeAES {
    OSDeclareDefaultStructors(NabuAES)
public:
    bool isKeySupported(unsigned selector) override;
    IOReturn performAES(void *,void *,task_t,unsigned long long,IOAESIV *,
        IOAESOperation,IOAESKeyData *,IOAESCompletion,void *) override;
    IOReturn performAES(IOMemoryDescriptor *,IOMemoryDescriptor *,unsigned long long,
        IOAESIV *,IOAESOperation,IOAESKeyData *,unsigned long long,unsigned long long,
        IOAESCompletion,void *) override;
};
OSDefineMetaClassAndStructors(NabuAES,NativeAES)

bool NabuAES::isKeySupported(unsigned selector)
{
    bool supported=NativeAES::isKeySupported(selector);
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
    IOReturn result=NativeAES::performAES(input,output,bytes,iv,operation,key,
        inputOffset,outputOffset,callback,refcon);
    if (native_aes_registered) IOLog("NABU AES: descriptor result=0x%x\n",result);
    return result;
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
    // GenericARMPE excludes this boot-state node from ordinary nub creation.
    // AppleImage4's original personality attaches to the defaults platform nub.
    IORegistryEntry *entry=IORegistryEntry::fromPath("/defaults",gIODTPlane);
    IOPlatformDevice *defaults=new IOPlatformDevice;
    if (!entry || !defaults || !defaults->init(entry,gIODTPlane)) return ENXIO;
    entry->release();
    defaults->attach(IOService::getPlatform());
    defaults->registerService();
    defaults->release();
    IOLog("NABU AES: defaults platform device published\n");
    return 0;
}
