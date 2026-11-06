// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <mach/kmod.h>
#include "NabuDataBlock.h"

extern "C" {
int nabu_aes_start(void);
#ifdef NABU_POWER_SERVICE
void nabu_power_start(void);
#endif
#ifdef NABU_USB_SERVICE
void nabu_usb_cdc_log_start(void);
#endif
#ifdef NABU_WIRELESS_SERVICE
void nabu_wireless_start(void);
#endif
static kern_return_t nabu_data_module_start(kmod_info_t *, void *)
{
    if (nabu_aes_start()) return KERN_FAILURE;
    if (nabu_data_block_start()) return KERN_FAILURE;
#ifdef NABU_POWER_SERVICE
    nabu_power_start();
#endif
#ifdef NABU_USB_SERVICE
    nabu_usb_cdc_log_start();
#endif
#ifdef NABU_WIRELESS_SERVICE
    nabu_wireless_start();
#endif
    return KERN_SUCCESS;
}

static kern_return_t nabu_data_module_stop(kmod_info_t *, void *)
{
    return KERN_FAILURE;
}

KMOD_EXPLICIT_DECL(org.nabu.driver.DataBlock, "1.0.0",
    nabu_data_module_start, nabu_data_module_stop)
}
