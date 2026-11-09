// SPDX-License-Identifier: BSD-2-Clause-Patent
// GPIO-only cover input; independent of SLPI and the PMIC button transport.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include "NabuHall.h"

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" kern_return_t thread_terminate(thread_t);

static void hall_thread(void *, wait_result_t)
{
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    vm_offset_t gpio = ml_io_map(NABU_HALL_GPIO_PA, 0x1000);
    if (!chosen || !gpio) {
        IOLog("NABU HALL: GPIO9 mapping or chosen entry unavailable\n");
        if (chosen) chosen->release();
        thread_terminate(current_thread());
        return;
    }
    volatile uint32_t *regs = (volatile uint32_t *)gpio;
    uint32_t before = regs[0];
    regs[0] = nabu_hall_input_config(before);
    __asm__ volatile("dsb sy" ::: "memory");
    IOLog("NABU HALL: GPIO9 NORTH pa=%#llx config=%#x->%#x poll=%ums active-low\n",
          NABU_HALL_GPIO_PA, before, regs[0], NABU_HALL_POLL_MS);
    struct NabuHallState state = {};
    unsigned changes = 0;
    for (;;) {
        uint32_t raw = regs[1];
        if (nabu_hall_sample(&state, raw)) {
            bool published = chosen->setProperty(NABU_HALL_PROPERTY, state.closed);
            IOLog("NABU HALL: state=%s raw=%#x sequence=%u published=%u\n",
                  state.closed ? "closed" : "open", raw, ++changes, published);
            if (!published) state.ready = false;
        }
        IOSleep(NABU_HALL_POLL_MS);
    }
}

extern "C" void nabu_hall_start(void)
{
    uint32_t enabled = 0;
    if (!PE_parse_boot_argn("nabu-hall", &enabled, sizeof(enabled)) || enabled != 1) return;
    thread_t thread;
    kern_return_t status = kernel_thread_start(hall_thread, NULL, &thread);
    if (status == KERN_SUCCESS) thread_deallocate(thread);
    else IOLog("NABU HALL: worker start failed=%d\n", status);
}
