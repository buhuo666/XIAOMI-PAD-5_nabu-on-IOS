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
    char wanted[37] = "168f804b-0cb5-4167-a239-c71953e36966";
    PE_parse_boot_argn("nabu-data-uuid", wanted, sizeof(wanted));
    OSDictionary *matching = IOService::serviceMatching("IOMedia");
    if (!matching) return ENOMEM;
    OSIterator *media = IOService::getMatchingServices(matching);
    matching->release();
    if (!media) return ENXIO;

    int error = ENXIO;
    while (OSObject *object = media->getNextObject()) {
        IOService *volume = OSDynamicCast(IOService, object);
        OSString *uuid = OSDynamicCast(OSString, volume->getProperty("UUID"));
        if (!uuid || strcasecmp(uuid->getCStringNoCopy(), wanted)) continue;
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
