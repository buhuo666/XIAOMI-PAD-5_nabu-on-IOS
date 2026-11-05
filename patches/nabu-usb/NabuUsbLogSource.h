// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef NABU_USB_LOG_SOURCE_H
#define NABU_USB_LOG_SOURCE_H
#include <stdint.h>
extern "C" const char *nabu_log_capture_data(void);
extern "C" uint32_t nabu_log_capture_length(void);
struct NabuUsbLogSnapshot { uint64_t end; };
static inline bool nabuUsbLogSnapshot(NabuUsbLogSnapshot *snapshot)
{
    snapshot->end = nabu_log_capture_length();
    return true;
}
static inline bool nabuUsbLogCopy(uint64_t at, unsigned size, uint8_t *out)
{
    const uint32_t published = nabu_log_capture_length();
    if (at > published || size > published - at) return false;
    const char *data = nabu_log_capture_data();
    for (unsigned i = 0; i < size; ++i) out[i] = (uint8_t)data[at+i];
    return true;
}
#endif
