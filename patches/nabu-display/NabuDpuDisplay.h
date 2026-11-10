// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <IOKit/IOTypes.h>
#include "NabuDpuVBlank.h"

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
}
extern "C" void nabu_dpu_power_changed(bool on);
