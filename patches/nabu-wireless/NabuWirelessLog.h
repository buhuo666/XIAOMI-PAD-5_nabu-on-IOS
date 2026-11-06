// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
void nabu_wireless_log(const char *format, ...) __attribute__((format(printf, 1, 2)));
extern "C" void nabu_bluetooth_version_trial();
extern "C" void nabu_modem_start_trial();
