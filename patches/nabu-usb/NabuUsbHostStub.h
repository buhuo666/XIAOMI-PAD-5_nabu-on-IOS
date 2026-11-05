// SPDX-License-Identifier: BSD-2-Clause-Patent
#ifndef NABU_USB_HOST_STUB_H
#define NABU_USB_HOST_STUB_H
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
typedef void *thread_t;
typedef int wait_result_t;
#define THREAD_NULL nullptr
#define KERN_SUCCESS 0
void IOLog(const char *, ...);
void IOSleep(unsigned);
int PE_parse_boot_argn(const char *, void *, int);
int kernel_thread_start(void (*)(void *, wait_result_t), void *, thread_t *);
void thread_deallocate(thread_t);
thread_t current_thread(void);
int thread_terminate(thread_t);
#endif
