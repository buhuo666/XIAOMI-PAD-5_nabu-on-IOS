// SPDX-License-Identifier: MIT
#pragma once
#include <errno.h>
#include <stdint.h>
#include <unistd.h>

// BSD179 is kdebug_trace64 in the project's 8796 syscalls.master. Bypass the
// libSystem kdebug wrapper's disabled-tracing shortcut. The kernel records
// these exact project codes only inside an explicitly started trace window.
static inline void nabu_ca_trace_marker(uint32_t event, uint64_t identity,
                                        uint64_t a, uint64_t b, uint64_t c) {
    const int saved = errno;
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    (void)syscall(179, (uint64_t)(0x31ca8000u | (event << 2)), identity, a, b, c);
#pragma clang diagnostic pop
    errno = saved;
}
