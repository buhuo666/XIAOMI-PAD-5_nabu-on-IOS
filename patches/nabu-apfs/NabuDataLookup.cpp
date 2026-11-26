// SPDX-License-Identifier: BSD-2-Clause-Patent
// Locate the volume published by APFS without importing IOStorage class symbols.
#include <IOKit/IOService.h>
#include <IOKit/IOBSD.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSIterator.h>
#include <libkern/c++/OSString.h>
#include <libkern/libkern.h>
#include <pexpert/pexpert.h>
#include <sys/errno.h>

extern "C" int nabu_data_device_path(char *out, unsigned size)
{
    char wanted[37] = {};
    bool explicitUUID = PE_parse_boot_argn("nabu-data-uuid", wanted, sizeof(wanted));
    OSDictionary *matching = IOService::serviceMatching("IOMedia");
    if (!matching) return ENOMEM;
    OSIterator *media = IOService::getMatchingServices(matching);
    matching->release();
    if (!media) return ENXIO;

    int error = ENXIO;
    while (OSObject *object = media->getNextObject()) {
        IOService *volume = OSDynamicCast(IOService, object);
        if (!volume || !volume->metaCast("AppleAPFSVolume")) continue;
        OSString *uuid = OSDynamicCast(OSString, volume->getProperty("UUID"));
        if (!uuid || (explicitUUID && strcasecmp(uuid->getCStringNoCopy(), wanted))) continue;
        // Find the APFS volume belonging to the actual Data block device. Its
        // filesystem UUID is created by the installer, not fixed in this kernel.
        bool dataDevice = false;
        for (IORegistryEntry *parent = volume->getParentEntry(gIOServicePlane);
             parent; parent = parent->getParentEntry(gIOServicePlane)) {
            if (parent->metaCast("NabuDataBlock")) { dataDevice = true; break; }
        }
        if (!dataDevice) continue;
        OSString *name = OSDynamicCast(OSString, volume->getProperty(kIOBSDNameKey));
        if (name) {
            int length = snprintf(out, size, "/dev/%s", name->getCStringNoCopy());
            error = length >= (int)size ? ENAMETOOLONG : 0;
        }
        break;
    }
    media->release();
    return error;
}
