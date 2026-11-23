// SPDX-License-Identifier: BSD-2-Clause-Patent
// Native 20F66 AppleARMBacklight registry contract, backed by nabu KTZ8866.
// The selected prelink set does not load Apple's ARM platform/backlight kext.
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <IOKit/IOService.h>
#include <IOKit/IOMessage.h>
#include <libkern/c++/OSBoolean.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <mach/kmod.h>
#include "NabuBrightnessCurve.h"

extern "C" IOReturn nabu_backlight_get_brightness(uint32_t *);
extern "C" IOReturn nabu_backlight_set_brightness(uint16_t);
#ifdef NABU_BACKLIGHT_EXPLICIT_REGISTRATION
extern "C" kmod_info_t g_kernel_kmod_info;
extern "C" void nabu_backlight_class_init(void)
    __asm__("__GLOBAL__sub_I_NabuBacklightService.cpp");
#endif

class AppleARMBacklight : public IOService {
    OSDeclareDefaultStructors(AppleARMBacklight)
    IOLock *lock_ = nullptr;
    uint32_t requested_, cap_, applied_;
    uint16_t level_;
    void publishVerifiedState();
public:
    bool start(IOService *provider) override;
    void free() override;
    IOReturn setProperties(OSObject *properties) override;
    void powerChanged(bool on);
};
OSDefineMetaClassAndStructors(AppleARMBacklight, IOService)
static AppleARMBacklight *backlight;

static void number(OSDictionary *dictionary, const char *key, uint32_t value) {
    OSNumber *n = OSNumber::withNumber(value, 32);
    dictionary->setObject(key, n);
    n->release();
}

void AppleARMBacklight::publishVerifiedState() {
    OSDictionary *parameters = OSDictionary::withCapacity(1);
    OSDictionary *brightness = OSDictionary::withCapacity(3);
    number(brightness, "min", NabuBrightness::kMinNits);
    number(brightness, "max", NabuBrightness::kMaxNits);
    number(brightness, "value", applied_);
    parameters->setObject("brightness", brightness);
    setProperty("IODisplayParameters", parameters);
    setProperty("brightness-nits", applied_, 32);
    setProperty("brightness-nits-cap", cap_, 32);
    setProperty("NabuRequestedNitsQ16", requested_, 32);
    setProperty("NabuBacklightRegisterLevel", level_, 32);
    brightness->release();
    parameters->release();
}

bool AppleARMBacklight::start(IOService *provider) {
    if (!IOService::start(provider)) return false;
    uint32_t raw = 0;
    IOReturn result = nabu_backlight_get_brightness(&raw);
    if (result != kIOReturnSuccess) {
        IOLog("NABU BACKLIGHT SERVICE: initial read failed %#x\n", result);
        return false;
    }
    lock_ = IOLockAlloc();
    if (!lock_) return false;
    level_ = uint16_t(raw);
    requested_ = applied_ = NabuBrightness::nitsFromLevel(level_);
    cap_ = NabuBrightness::kMaxNits;
    setName("AppleARMBacklight");
    setProperty("NabuBacklightBackend", "KTZ8866");
    setProperty("backlight-control", kOSBooleanTrue);
    setProperty("new-backlight-architecture", kOSBooleanTrue);
    // Native LCD calibration values are Q16.16 numbers. This backend exposes
    // nits, not a milliamp control interface; the three legacy current fields
    // are zero. CFNumberGetValue unconditionally reads these keys in 20F66.
    OSDictionary *calibration = OSDictionary::withCapacity(9);
    number(calibration, "current-for-max-backlight", 0);
    number(calibration, "current-for-mid-backlight", 0);
    number(calibration, "hardware-max-current-limit", 0);
    number(calibration, "lMinProduct", NabuBrightness::kMinNits);
    number(calibration, "lMidProduct", 251 * NabuBrightness::kOne);
    number(calibration, "lMaxProduct", NabuBrightness::kMaxNits);
    number(calibration, "lMinPanel", NabuBrightness::kMinNits);
    number(calibration, "lMidPanel", 251 * NabuBrightness::kOne);
    number(calibration, "lMaxPanel", NabuBrightness::kMaxNits);
    setProperty("backlight-calibration-parameters", calibration);
    calibration->release();
    uint32_t curve[] = {NabuBrightness::kMinNits, 251 * NabuBrightness::kOne, NabuBrightness::kMaxNits};
    setProperty("backlight-marketing-table", curve, sizeof(curve));
    uint32_t minimum = NabuBrightness::kMinNits, maximum = NabuBrightness::kMaxNits;
    setProperty("digital-dimming-min-nits", &minimum, sizeof(minimum));
    setProperty("user-accessible-max-nits", &maximum, sizeof(maximum));
    publishVerifiedState();
    registerService();
    IOLog("NABU BACKLIGHT SERVICE: published AppleARMBacklight nits=2..500 initial-q16=%u level=%u\n", applied_, unsigned(level_));
    return true;
}

void AppleARMBacklight::free() {
    if (lock_) IOLockFree(lock_);
    IOService::free();
}

IOReturn AppleARMBacklight::setProperties(OSObject *object) {
    OSDictionary *properties = OSDynamicCast(OSDictionary, object);
    if (!properties) return kIOReturnBadArgument;
    OSNumber *nits = OSDynamicCast(OSNumber, properties->getObject("brightness-nits"));
    OSNumber *cap = OSDynamicCast(OSNumber, properties->getObject("brightness-nits-cap"));
    if (!nits && !cap) return IOService::setProperties(object);
    if (nits && int32_t(nits->unsigned32BitValue()) < 0) return kIOReturnBadArgument;
    IOLockLock(lock_);
    uint32_t request = nits ? nits->unsigned32BitValue() : requested_;
    uint32_t limit = cap ? cap->unsigned32BitValue() : cap_;
    if (limit > NabuBrightness::kMaxNits) limit = NabuBrightness::kMaxNits;
    uint32_t applied = NabuBrightness::effectiveNits(request, limit);
    uint16_t level = NabuBrightness::levelFromNits(applied);
    IOReturn result = nabu_backlight_set_brightness(level);
    if (result == kIOReturnSuccess) {
        requested_ = request; cap_ = limit; applied_ = applied; level_ = level;
        publishVerifiedState();
    }
    IOLog("NABU BACKLIGHT SERVICE: nits-q16=%u cap-q16=%u index=%u level=%u result=%#x\n",
          request, limit, NabuBrightness::indexFromNits(applied), unsigned(level), result);
    IOLockUnlock(lock_);
    return result;
}

void AppleARMBacklight::powerChanged(bool on) {
    setProperty("NabuDisplayPower", on ? kOSBooleanTrue : kOSBooleanFalse);
    messageClients(on ? kIOMessageDeviceHasPoweredOn : kIOMessageDeviceWillPowerOff);
}

extern "C" void nabu_backlight_native_start(void) {
    if (backlight) return;
#ifdef NABU_BACKLIGHT_EXPLICIT_REGISTRATION
    static bool classRegistered;
    if (!classRegistered) {
        void *handle = OSMetaClass::preModLoad(g_kernel_kmod_info.name);
        nabu_backlight_class_init();
        OSReturn status = OSMetaClass::postModLoad(handle);
        if (status != kOSReturnSuccess) {
            IOLog("NABU BACKLIGHT SERVICE: class registration failed %#x\n", status);
            return;
        }
        classRegistered = true;
    }
#endif
    AppleARMBacklight *service = new AppleARMBacklight;
    IOService *provider = IOService::getResourceService();
    if (!service) return;
    if (!service->init() || !service->attach(provider)) { service->release(); return; }
    if (service->start(provider)) backlight = service;
    else { service->detach(provider); service->release(); }
}

extern "C" void nabu_backlight_native_power(bool on) {
    if (backlight) backlight->powerChanged(on);
}
