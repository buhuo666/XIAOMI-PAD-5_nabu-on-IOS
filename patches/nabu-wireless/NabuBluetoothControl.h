// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

// Nabu-owned lifecycle options on com.apple.uart.bluetooth (SYSPROTO_CONTROL).
// IBS_IDLE takes exactly uint32_t version=1. Its synchronous 2000ms deadline
// covers draining, FE transmission and observing the controller's RX-side idle.
// Success is IBS transport quiescence, not regulator removal or deep power collapse.
#define NABU_BT_CONTROL_VERSION       1u
#define NABU_BT_OPT_IBS_IDLE           0x4e420001
#define NABU_BT_OPT_IBS_STATE          0x4e420002
#define NABU_BT_IDLE_DEADLINE_MS       2000u
#define NABU_BT_IDLE_CONFIRMED         1u
#define NABU_BT_IDLE_IN_PROGRESS       2u

typedef struct NabuBluetoothIbsState {
    uint32_t version;
    uint32_t flags;
    uint32_t tx_state; // 0=asleep, 1=waking, 2=awake
    uint32_t rx_awake;
    uint64_t host_sleep_count;
    uint64_t controller_sleep_count;
} NabuBluetoothIbsState;
