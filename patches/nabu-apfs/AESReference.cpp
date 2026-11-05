// ABI names for the original class. This object is never linked or executed.
#include "OriginalAESABI.h"
OSDefineMetaClassAndStructors(IOCryptoAccelerator,IOService)
OSDefineMetaClassAndStructors(IOAESAccelerator,IOCryptoAccelerator)
bool IOAESAccelerator::start(IOService *) { return false; }
IOWorkLoop *IOAESAccelerator::getWorkLoop() const { return nullptr; }
IOReturn IOAESAccelerator::callPlatformFunction(const OSSymbol *,bool,void *,void *,void *,void *) { return kIOReturnUnsupported; }
const char *IOAESAccelerator::getAlgorithmName() { return "AES"; }
IOReturn IOAESAccelerator::performAES(void *,void *,task_t,unsigned long long,IOAESIV *,IOAESOperation,IOAESKeyData *,IOAESCompletion,void *) { return kIOReturnUnsupported; }
IOReturn IOAESAccelerator::performAES(IOMemoryDescriptor *,IOMemoryDescriptor *,unsigned long long,IOAESIV *,IOAESOperation,IOAESKeyData *,unsigned long long,unsigned long long,IOAESCompletion,void *) { return kIOReturnUnsupported; }
bool IOAESAccelerator::isKeySupported(unsigned) { return false; }
unsigned IOAESAccelerator::getSupportedOptions() { return 0; }
IOReturn IOAESAccelerator::performAESQuantum(IOAESAcceleratorCommand *) { return kIOReturnUnsupported; }
void IOAESAccelerator::completeAESQuantum(IOAESAcceleratorCommand *) {}
IOReturn IOAESAccelerator::performImmediateAES(IOAESAcceleratorCommand *) { return kIOReturnUnsupported; }
void IOAESAccelerator::disableHardwareKey(unsigned) {}
void IOAESAccelerator::createSpecialKeys() {}
IOReturn IOAESAccelerator::_queueLocked(IOAESAcceleratorCommand *) { return kIOReturnUnsupported; }
void IOAESAccelerator::_startCommand() {}
void IOAESAccelerator::_completeAES(IOAESAcceleratorCommand *) {}
