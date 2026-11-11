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
// Diagnostic control: reproduce the halted read-only checks without touching
// any context, route or translation register. Release the unused pool afterward.
IOReturn auditInactiveAfterQuiesce(Binding *, const NabuDpuScanout::Io &,
                                 const NabuDpuScanout::State &, uint32_t *sctlr);
void discardPrepared(Binding *);
// Requires the core's Quiesced state AND hardware HALT request/ACK for XIN0/4.
// Revalidates observed topology, inactive non-VIG sources and every CTL WB/CWB
// output. Route mask covers 0x800,0x820,0xc00,0xc20; offline rotator SID0x1040
// is separate. No shared-CB-only assumption of idle is made.
IOReturn activateAfterQuiesce(Binding *, const NabuDpuScanout::Io &, const NabuDpuScanout::State &);
// GOP-only transition from inherited M=0 bypass to identical physical pages.
// Pre-stage translation registers with M=0, then enable the completed context.
// Never writes DPU/VBIF or changes the scanout address; unrelated routes stay fixed.
IOReturn activateIdentityLive(Binding *, const NabuDpuScanout::Io &, const NabuDpuScanout::State &);
// A read-only qualification refusal leaves poisoned()==false and no context
// mutation; the root may resume its own halt lease. A poisoned failure retains it.
IOReturn mapDescriptor(Binding *, IOMemoryDescriptor *, uint64_t offset, uint64_t bytes,
                      NabuDpuPageTable::Mapping *);
IOReturn accept(Binding *, const NabuDpuPageTable::Mapping &, unsigned *retired);
// Only after the root verifies the flip back to permanent GOP with Scan::poll.
// Retires this mapping; releaseRetired still owns TLBI and descriptor release.
IOReturn acceptGop(Binding *, const NabuDpuPageTable::Mapping &);
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
bool programmingAttempted(Binding *);
// Cumulative wall-clock microseconds from activation entry, stored while halted
// and read only after resume. These include scheduling; they are not bus latency.
struct ActivationTiming {
    uint64_t halt, sources, inherited, encoded, disabled, registers;
    uint64_t disabledReadback, tlbi, enabled, enabledReadback, routes;
};
struct ActiveSnapshot {
    uint64_t tablePhysical, ttbr0, ttbr1, far;
    uint32_t asid, sctlr, cbar, cba2r, tcr, tcr2, mair0, mair1;
    uint32_t fsr, globalFsr, fsynr0, streamSyndrome, tlbStatus, identityPages;
    uint32_t actlr, inheritedActlr;
    bool active, contextMatches, routesUnchanged, gopIdentity, poisoned;
    ActivationTiming timing;
};
// Read back the active domain and every GOP identity leaf. No register or
// table writes; even a poisoned active domain reports its actual fault state
// and remains failed. The display serializes this with mapper/IRQ fault accesses.
IOReturn snapshotActive(Binding *, ActiveSnapshot *);
// Descriptor prepare/retain persists until successful release+TLBI. Table pool,
// MMIO map and uncertain descriptors remain boot-owned; no implicit teardown.
}
