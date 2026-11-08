// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuWlanDma.h"
#include "NabuWlanFault.h"
#ifdef KERNEL
// Single serialized WLAN worker only. WLAN mission mode remains OFF until this
// succeeds; no constructor or existing boot flow calls these entry points.
extern "C" bool nabu_wlan_dma_attach_native(NabuWlanDma *owner);
extern "C" uint32_t nabu_wlan_dma_faults_native(NabuWlanDma *owner,
    NabuWlanFault::Record *context,NabuWlanFault::Record *global);
// Caller holds the shared SMMU configuration mutex; context ownership is exclusive.
extern "C" bool nabu_smmu_fault_install(NabuWlanFault *,unsigned,const ArmSmmu4KIo *,unsigned sid);
extern "C" void nabu_smmu_fault_remove(NabuWlanFault *);
#endif
