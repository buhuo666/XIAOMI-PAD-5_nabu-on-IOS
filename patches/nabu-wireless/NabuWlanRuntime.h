// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
extern "C" bool nabu_wlan_runtime_prepare();
extern "C" bool nabu_wlan_runtime_resources_ready();
extern "C" bool nabu_wlan_runtime_start();
extern "C" bool nabu_wlan_runtime_failed();
extern "C" void nabu_wlan_runtime_poll();
extern "C" void nabu_wlan_runtime_lost();
extern "C" void nabu_wlan_runtime_stop(); // Only after confirmed PAS shutdown.
extern "C" void nabu_wlan_runtime_summary();
#ifdef NABU_ATH10K_SERVICE
extern "C" bool nabu_wlan_runtime_quiesced(); // Worker/IRQ teardown before PAS and DMA release.
#endif
