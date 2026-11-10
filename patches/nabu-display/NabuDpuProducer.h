// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <IOKit/IOTypes.h>
#include <stdint.h>
class IOMemoryDescriptor;

// The GPU installs one static-lifetime table after publishing its scheduler.
// A read lease captures already accepted writers, then prevents later writers
// from issuing until release. Completion alone does not release that lease.
struct NabuDpuProducerOps {
    IOReturn (*acquire)(IOMemoryDescriptor *, void (*ready)(void *, IOReturn), void *, void **);
    IOReturn (*status)(void *, uint32_t *hardwareFence);
    void (*release)(void *);
};
extern "C" IOReturn nabu_dpu_register_producer(const NabuDpuProducerOps *);
