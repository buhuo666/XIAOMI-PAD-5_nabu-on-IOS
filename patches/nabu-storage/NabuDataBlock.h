// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once

#ifdef __cplusplus
extern "C" {
#endif
// Call after the original IOStorageFamily has registered its classes.
int nabu_data_block_start(void);
#ifdef __cplusplus
}
#endif
