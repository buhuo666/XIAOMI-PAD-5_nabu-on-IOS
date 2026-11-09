// SPDX-License-Identifier: MIT
// C entry points of the frontend/bridge artifact qualified in device run 167.
#pragma once
#import <Foundation/Foundation.h>
#include <stdint.h>

extern "C" {
id native_bridge_metal_open(const char *loader, const char *cache, uint64_t registryID,
                           void (*missing)(const char *, const char *));
void native_bridge_metal_set_problem_observer(void (*report)(const char *, void *), void *context);
const char *nmb_last_error(void);
}

// Probe diagnostics provided by the thin discovery bundle, resolved only after
// MTLCreateSystemDefaultDevice has loaded it through the normal Metal factory.
@protocol NabuMetalFactoryDiagnostics <NSObject>
+ (const char *)nabuMissingSelector;
+ (const char *)nabuLastError;
+ (uint64_t)nabuRegistryID;
+ (NSUInteger)nabuOpenCount;
@end
