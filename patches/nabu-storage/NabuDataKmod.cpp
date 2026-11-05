// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <mach/kmod.h>
#include "NabuDataBlock.h"

extern "C" {
static kern_return_t nabu_data_module_start(kmod_info_t *, void *)
{
    return nabu_data_block_start() ? KERN_FAILURE : KERN_SUCCESS;
}

static kern_return_t nabu_data_module_stop(kmod_info_t *, void *)
{
    return KERN_FAILURE;
}

KMOD_EXPLICIT_DECL(org.nabu.driver.DataBlock, "1.0.0",
    nabu_data_module_start, nabu_data_module_stop)
}
