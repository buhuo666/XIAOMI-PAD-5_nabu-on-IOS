/* 20F66 bluetoothd: temporary host initialization compatibility for QCA. */
#ifndef NABU_BT_COMPAT_TEST
#include <mach/mach.h>
#include <mach-o/dyld.h>
#endif
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <syslog.h>
#include <unistd.h>

static const uint8_t *supported_commands;
static void **active_sequence;
static void (*advance_sequence)(void *);
static void (*original_initialize)(void *);
static void (*original_periodic_initialize)(void *);

enum {
    HostStandardAdvertising,
    HostExtendedAdvertising,
    HostExtendedScanning,
    HostExtendedScanHci,
    HostPeriodicAdvertiser,
    HostPeriodicSynchronizer,
    HostEnhancedConnections,
    HostChoiceCount
};
static const uint8_t *host_choices[HostChoiceCount];

static void initialize_periodic_list_size(void *record) {
    /* initCoreStack sets these host policy bytes before the HCI sequence.
     * Read them now: they are not controller features or supported commands.
     * Enhanced Connections independently selects 2043 rather than 200d.
     * The real QCA rejected legacy 200b after successful 204a in run103.
     * This omits an unused initialization query, not all future vendor work.
     */
    uint8_t choices[HostChoiceCount];
    bool legacy = true;
    for (unsigned i = 0; i < HostChoiceCount; ++i) {
        choices[i] = *host_choices[i];
        if (choices[i]) legacy = false;
    }
    if (!legacy) {
        original_periodic_initialize(record);
        return;
    }
    fprintf(stderr, "NABU BT COMPAT: skip unused ReadPeriodicAdvertiserListSize for legacy host; standard-adv=%u extended-adv=%u extended-scan=%u extended-scan-hci=%u periodic-adv=%u periodic-sync=%u enhanced-connections=%u; no HCI command or response synthesized\n",
            choices[HostStandardAdvertising], choices[HostExtendedAdvertising],
            choices[HostExtendedScanning], choices[HostExtendedScanHci],
            choices[HostPeriodicAdvertiser], choices[HostPeriodicSynchronizer],
            choices[HostEnhancedConnections]);
    syslog(LOG_NOTICE, "NABU BT COMPAT: skip unused ReadPeriodicAdvertiserListSize for legacy host; all seven host choices disabled");
    /* Same sequence-table argument used by the original no-query branch. */
    advance_sequence(*active_sequence);
}

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
    /* On this iOS dyld, inserted libraries precede the executable (run100).
     * Select the exact executable as the existing FairPlay observer does.
     */
    uint32_t index, images = _dyld_image_count();
    for (index = 0; index < images; ++index) {
        const char *name = _dyld_get_image_name(index);
        if (name && !strcmp(name, "/usr/sbin/bluetoothd")) break;
    }
    if (index == images) {
        fprintf(stderr, "NABU BT COMPAT: executable /usr/sbin/bluetoothd not found\n");
        return;
    }
    /* Exact ordinary-arm64 20F66 image; addresses/ABI in the v99 analysis. */
    intptr_t slide = _dyld_get_image_vmaddr_slide(index);
    void (**slot)(void *) = (void (**)(void *))(slide + 0x1007fbde0ULL);
    void (**periodic_slot)(void *) = (void (**)(void *))(slide + 0x1007fbdb0ULL);
    supported_commands = (const uint8_t *)(slide + 0x100863928ULL);
    active_sequence = (void **)(slide + 0x10084f588ULL);
    advance_sequence = (void (*)(void *))(slide + 0x1001c204cULL);
    original_initialize = *slot; /* Loaded chained rebase, not the file encoding. */
    original_periodic_initialize = *periodic_slot;
    host_choices[HostStandardAdvertising] = (const uint8_t *)(slide + 0x100854aa9ULL);
    host_choices[HostExtendedAdvertising] = (const uint8_t *)(slide + 0x100854ae8ULL);
    host_choices[HostExtendedScanning] = (const uint8_t *)(slide + 0x10085a636ULL);
    host_choices[HostExtendedScanHci] = (const uint8_t *)(slide + 0x10085a635ULL);
    host_choices[HostPeriodicAdvertiser] = (const uint8_t *)(slide + 0x100854af0ULL);
    host_choices[HostPeriodicSynchronizer] = (const uint8_t *)(slide + 0x10084b798ULL);
    host_choices[HostEnhancedConnections] = (const uint8_t *)(slide + 0x100855919ULL);
    fprintf(stderr, "NABU BT COMPAT: image-index=%u slide=%#lx slot-original=%p expected=%p\n",
            index, (unsigned long)slide, (void *)original_initialize, (void *)(slide + 0x10010b970ULL));
    fprintf(stderr, "NABU BT COMPAT: slot18-original=%p expected=%p\n",
            (void *)original_periodic_initialize, (void *)(slide + 0x10010b3bcULL));
    if ((uintptr_t)original_initialize != (uintptr_t)(slide + 0x10010b970ULL) ||
        (uintptr_t)original_periodic_initialize != (uintptr_t)(slide + 0x10010b3bcULL)) {
        fprintf(stderr, "NABU BT COMPAT: initializer slots do not point to the known originals; no write\n");
        return;
    }

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
    /* These two slots are 48 bytes apart on the same 20F66 const data page. */
    *periodic_slot = initialize_periodic_list_size;
    *slot = initialize_optional_reporting;
    if (readonly) {
        result = vm_protect(mach_task_self(), page, page_bytes, FALSE, info.protection);
        if (result != KERN_SUCCESS)
            fprintf(stderr, "NABU BT COMPAT: restoring initializer data-page protection failed: %d\n", result);
    }
    fprintf(stderr, "NABU BT COMPAT: installed optional initializer slot24; protection=%#x readback=%p handler=%p; controller support read at invocation\n",
            info.protection, (void *)*slot, (void *)initialize_optional_reporting);
    fprintf(stderr, "NABU BT COMPAT: installed legacy host policy initializer slot18; protection=%#x readback=%p handler=%p; host policy read at invocation\n",
            info.protection, (void *)*periodic_slot, (void *)initialize_periodic_list_size);
}
#endif
