// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <IOKit/IOTypes.h>
#include "NabuDpuVBlank.h"
class IOService;
class OSObject;

namespace NabuDpuDisplay {
struct Binding;
struct Listener {
    Listener *next;
    void *cookie;
    void (*notify)(void *, const NabuDpuVBlank::Sample &);
};
bool requested();
Binding *start();
// One native SwapEnd, including the observed all-layers-clear transaction.
// Success accepts the protected frame into the queue. Displayed/retired are
// reported separately by wait() after real hardware events. No pixel copies.
IOReturn present(Binding *, const uint8_t *swap, size_t bytes);
IOReturn wait(Binding *, uint32_t id, uint32_t flags, uint64_t timeoutMs);
// Register/unregister outside the client's notification lock. Unregister waits
// for any executing notification, so its embedded listener can then be freed.
void subscribe(Binding *, Listener *);
void unsubscribe(Binding *, Listener *);
bool snapshot(Binding *, NabuDpuVBlank::Sample *);
// Timestamp is the original master IRQ time. Status is the native async-send result.
void traceNativeVblank(uint64_t sequence, uint64_t timestamp, IOReturn status);
// Post-desktop diagnostics keep fDpu unset and the GOP presenter selected.
// Publication allocates only software state; MMIO begins on a paired request.
bool diagnosticsRequested();
void publishDiagnostics(IOService *, const volatile uint8_t *gop, uint64_t bytes);
IOReturn diagnosticRequest(OSObject *, bool desktopStarted);
// Wrap the presenter's complete show/settle operations, including row helpers.
void diagnosticDrawBegin();
void diagnosticDrawEnd();
}
extern "C" void nabu_dpu_power_changed(bool on);
