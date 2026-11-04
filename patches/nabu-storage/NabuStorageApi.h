// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
int nabu_storage_prepare(void);
int nabu_storage_read(unsigned window, uint64_t offset, void *out, uint64_t bytes);
uint64_t nabu_storage_size(unsigned window);
void nabu_storage_append_report(void);
void nabu_storage_finish(const char *result) __attribute__((noreturn));
int nabu_root_device(char *name, unsigned name_bytes, int *device, uint32_t *flags);
void nabu_root_probe_mounted(void);
uint32_t nabu_userland_status(void);
#ifdef __cplusplus
}
#endif
