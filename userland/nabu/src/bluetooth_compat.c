/* 20F66 bluetoothd: omit an optional HCI setting the real controller lacks. */
#include <mach/mach.h>
#include <mach-o/dyld.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <syslog.h>
#include <unistd.h>

static const uint8_t *supported_commands;
static void **active_sequence;
static void (*advance_sequence)(void *);
static void (*original_initialize)(void *);

static void initialize_optional_reporting(void *record) {
    /* Filled from Read Local Supported Commands before this last init step.
     * Descriptor 0x7c: opcode 0x0c5b, supportedCommands[18] & 0x08.
     * The original command builder returns 0x274 before sending when absent.
     */
    if (supported_commands[18] & 0x08) {
        original_initialize(record);
        return;
    }
    fprintf(stderr, "NABU BT COMPAT: skip unsupported optional WriteDefaultErroneousDataReporting; supported[18]=%#x; no HCI command or response synthesized\n", supported_commands[18]);
    syslog(LOG_NOTICE, "NABU BT COMPAT: skip unsupported optional WriteDefaultErroneousDataReporting; supported[18]=%#x", supported_commands[18]);
    /* Advance the original sequence, whose next entry is its NULL terminator.
     * This is not an HCI completion callback and does not alter support bits.
     */
    advance_sequence(*active_sequence);
}

#ifndef NABU_BT_COMPAT_TEST
__attribute__((constructor)) static void install_bluetooth_compatibility(void) {
    /* Exact ordinary-arm64 20F66 image; addresses/ABI in the v99 analysis. */
    intptr_t slide = _dyld_get_image_vmaddr_slide(0);
    void (**slot)(void *) = (void (**)(void *))(slide + 0x1007fbde0ULL);
    supported_commands = (const uint8_t *)(slide + 0x100863928ULL);
    active_sequence = (void **)(slide + 0x10084f588ULL);
    advance_sequence = (void (*)(void *))(slide + 0x1001c204cULL);
    original_initialize = *slot; /* Loaded chained rebase, not the file encoding. */

    vm_address_t region = (vm_address_t)slot;
    vm_size_t region_bytes = 0;
    vm_region_basic_info_data_64_t info;
    mach_msg_type_number_t count = VM_REGION_BASIC_INFO_COUNT_64;
    mach_port_t object = MACH_PORT_NULL;
    kern_return_t result = vm_region_64(mach_task_self(), &region, &region_bytes,
        VM_REGION_BASIC_INFO_64, (vm_region_info_t)&info, &count, &object);
    if (object != MACH_PORT_NULL) mach_port_deallocate(mach_task_self(), object);
    if (result != KERN_SUCCESS) {
        fprintf(stderr, "NABU BT COMPAT: cannot query initializer data-page protection: %d\n", result);
        return;
    }
    vm_size_t page_bytes = (vm_size_t)getpagesize();
    vm_address_t page = (vm_address_t)slot & ~(page_bytes - 1);
    bool readonly = !(info.protection & VM_PROT_WRITE);
    if (readonly) {
        result = vm_protect(mach_task_self(), page, page_bytes, FALSE,
                           info.protection | VM_PROT_WRITE | VM_PROT_COPY);
        if (result != KERN_SUCCESS) {
            fprintf(stderr, "NABU BT COMPAT: cannot make initializer data page private/writable: %d\n", result);
            return;
        }
    }
    *slot = initialize_optional_reporting;
    if (readonly) {
        result = vm_protect(mach_task_self(), page, page_bytes, FALSE, info.protection);
        if (result != KERN_SUCCESS)
            fprintf(stderr, "NABU BT COMPAT: restoring initializer data-page protection failed: %d\n", result);
    }
    fprintf(stderr, "NABU BT COMPAT: installed optional initializer slot24; protection=%#x; controller support read at invocation\n", info.protection);
}
#endif
