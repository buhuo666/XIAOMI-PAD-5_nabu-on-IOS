// SPDX-License-Identifier: BSD-2-Clause-Patent
/* nabu PM8150 keys -> the existing /dev/hakios-touch input queue.
 * Board addresses: Android FDT captured from this nabu on 2026-11-05.
 * Register definitions: MiCode nabu-r-oss qpnp-power-on.c,
 * spmi-pmic-arb.c and pinctrl-spmi-gpio.c. No PMIC configuration writes.
 */
#ifndef NABU_BUTTONS_HOST_TEST
#include <kern/clock.h>
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/hakios.input.h>
#include <sys/systm.h>
#endif

extern vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern kern_return_t thread_terminate(thread_t);

#define ARB_CORE_PHYS       0x0c440000UL
#define ARB_CNFG_PHYS       0x0c40a000UL
#define ARB_OBSERVER_PHYS   0x0e600000UL
#define ARB_MAP(n)          (0x900 + 4 * (n))
#define ARB_OWNER(n)        (0x700 + 4 * (n))
#define ARB_CHANNELS        512
#define POLL_MS             16
#define READ_TIMEOUT_NS     2000000ULL

static vm_offset_t arb_core, arb_cnfg, arb_observer;
static int pon_channel, gpio_channel;
static unsigned failed_reads, sent_events;

static uint32_t
mmio_read(vm_offset_t address)
{
    return *(volatile uint32_t *)address;
}

static void
mmio_write(vm_offset_t address, uint32_t value)
{
    *(volatile uint32_t *)address = value;
#ifndef NABU_BUTTONS_HOST_TEST
    __asm__ volatile("dsb sy" ::: "memory");
#endif
}

/* v5 can map a peripheral more than once. Prefer an EE0-owned channel. */
static int
find_channel(uint16_t peripheral)
{
    int selected = -1;
    for (unsigned i = 0; i < ARB_CHANNELS; i++) {
        uint32_t entry = mmio_read(arb_core + ARB_MAP(i));
        if (entry && ((entry >> 8) & 0xfff) == peripheral &&
            (selected < 0 || (mmio_read(arb_cnfg + ARB_OWNER(i)) & 7) == 0)) {
            selected = (int)i;
        }
    }
    return selected;
}

/* One-byte extended register read through EE0's observer channel.
 * The only MMIO write issues a READ command; no PMIC data is written.
 */
static bool
read_status(int channel_index, uint8_t *value)
{
    vm_offset_t channel = arb_observer + 0x80UL * (unsigned)channel_index;
    uint64_t interval;
    nanoseconds_to_absolutetime(READ_TIMEOUT_NS, &interval);
    hakios_spmi_lock();
    uint64_t start = mach_absolute_time();
    mmio_write(channel, (1u << 27) | (0x10u << 4));
    uint32_t status;
    do {
        status = mmio_read(channel + 0x08);
    } while (!(status & 1) && mach_absolute_time() - start < interval);
    bool ok = (status & 0xf) == 1;
    if (ok) {
        *value = (uint8_t)mmio_read(channel + 0x18);
    }
    hakios_spmi_unlock();
    if (!ok && ++failed_reads <= 3) {
        printf("NABU BUTTONS: observer channel %d status=%#x\n", channel_index, status);
    }
    return ok;
}

static struct button {
    const char *name;
    uint32_t code;
    bool ready, previous, down;
} buttons[] = {
    { .name = "power", .code = HAKIOS_BUTTON_LOCK },
    { .name = "volume-up", .code = HAKIOS_BUTTON_VOLUME_UP },
    { .name = "volume-down", .code = HAKIOS_BUTTON_VOLUME_DOWN },
};

static void
sample_button(unsigned index, bool pressed)
{
    struct button *button = &buttons[index];
    bool steady = button->previous == pressed;
    button->previous = pressed;
    /* Ignore a key still held from the bootloader until it is released. */
    if (!button->ready) {
        button->ready = !pressed;
        return;
    }
    if (steady && button->down != pressed) {
        button->down = pressed;
        hakios_touch_post(pressed ? HAKIOS_BUTTON_DOWN : HAKIOS_BUTTON_UP,
                          button->code, 0, 0);
        sent_events++;
        printf("NABU BUTTONS: %s %s\n", button->name, pressed ? "down" : "up");
    }
}

static void
poll_buttons(void)
{
    uint8_t status;
    /* PM8150 PON@0800: KPDPWR bit0, RESIN bit1. Both are pressed-high. */
    if (read_status(pon_channel, &status)) {
        sample_button(0, (status & 1) != 0);
        sample_button(2, (status & 2) != 0);
    }
    /* PM8150 GPIO6@c500: RT status bit0 is the pin level, active-low. */
    if (read_status(gpio_channel, &status)) {
        sample_button(1, (status & 1) == 0);
    }
}

static void
buttons_thread(void *argument, wait_result_t result)
{
    (void)argument;
    (void)result;
    arb_core = ml_io_map(ARB_CORE_PHYS, 0x1100);
    arb_cnfg = ml_io_map(ARB_CNFG_PHYS, 0x1000);
    arb_observer = ml_io_map(ARB_OBSERVER_PHYS, 0x10000);
    if (!arb_core || !arb_cnfg || !arb_observer) {
        printf("NABU BUTTONS: PMIC arbiter mapping failed\n");
        goto out;
    }
    uint32_t version = mmio_read(arb_core);
    if (version < 0x50000000u || version >= 0x70000000u) {
        printf("NABU BUTTONS: unsupported PMIC arbiter version=%#x\n", version);
        goto out;
    }
    pon_channel = find_channel(0x008);
    gpio_channel = find_channel(0x0c5);
    printf("NABU BUTTONS: arbiter=%#x EE0 PON=%d GPIO6=%d\n",
           version, pon_channel, gpio_channel);
    if (pon_channel < 0 || gpio_channel < 0) {
        goto out;
    }
    printf("NABU BUTTONS: polling PM8150 power and volume keys every %u ms\n", POLL_MS);
    for (unsigned tick = 1;; tick++) {
        poll_buttons();
        if (tick % (60000 / POLL_MS) == 0) {
            printf("NABU BUTTONS: events=%u failed-reads=%u\n", sent_events, failed_reads);
        }
        delay_for_interval(POLL_MS, NSEC_PER_MSEC);
    }
out:
    thread_terminate(current_thread());
}

void
nabu_buttons_init(void)
{
    uint32_t enabled = 0;
    thread_t thread;
    if (PE_parse_boot_argn("nabu-buttons", &enabled, sizeof(enabled)) && enabled == 1) {
        kern_return_t status = kernel_thread_start(buttons_thread, NULL, &thread);
        if (status == KERN_SUCCESS) {
            thread_deallocate(thread);
        } else {
            printf("NABU BUTTONS: worker start failed=%d\n", status);
        }
    }
}
