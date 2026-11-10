// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <IOKit/IOTypes.h>
#include "NabuDpuScanoutCore.h"
#include "NabuDpuPageTable.h"
class IOMemoryDescriptor;

namespace NabuDpuMapper {
struct Binding;
// All calls are serialized by the root display binding, including IRQ-worker
// fault checks. prepare runs BEFORE halt: allocation, fixed table publication,
// complete route snapshot and ASID selection; no SMMU register writes.
Binding *prepare(int *error);
IOReturn preflightSources(Binding *, const NabuDpuScanout::Io &);
// Requires the core's Quiesced state AND hardware HALT request/ACK for XIN0/4.
// Revalidates observed topology, inactive non-VIG sources and every CTL WB/CWB
// output. Route mask covers 0x800,0x820,0xc00,0xc20; offline rotator SID0x1040
// is separate. No shared-CB-only assumption of idle is made.
IOReturn activateAfterQuiesce(Binding *, const NabuDpuScanout::Io &, const NabuDpuScanout::State &);
// A read-only qualification refusal leaves poisoned()==false and no context
// mutation; the root may resume its own halt lease. A poisoned failure retains it.
IOReturn mapDescriptor(Binding *, IOMemoryDescriptor *, uint64_t offset, uint64_t bytes,
                      NabuDpuPageTable::Mapping *);
IOReturn accept(Binding *, const NabuDpuPageTable::Mapping &, unsigned *retired);
IOReturn releaseRetired(Binding *, unsigned slot, uint64_t token);
// Only after the root determines no DPU submit was attempted for this generation.
IOReturn discardUnsubmitted(Binding *, const NabuDpuPageTable::Mapping &);
// Check before submit, in acceptance polling, and on every idle vblank. CFIE is
// explicitly OFF, CFRE ON; no fault-IRQ handler is presumed or synthesized.
// Any real global/CB2 fault poisons the binding and prevents page/slot release.
IOReturn checkFault(Binding *);
// IRQ-worker variant: only loads CB2 FSR; no state mutation, locking, logging or
// waiting. The root publishes Binding only after activation and owns failure state.
IOReturn readFault(Binding *);
bool poisoned(Binding *);
// Descriptor prepare/retain persists until successful release+TLBI. Table pool,
// MMIO map and uncertain descriptors remain boot-owned; no implicit teardown.
}
