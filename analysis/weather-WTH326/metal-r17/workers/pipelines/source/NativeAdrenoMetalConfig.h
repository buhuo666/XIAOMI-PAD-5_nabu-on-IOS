// SPDX-License-Identifier: MIT
#pragma once

// The board build selects the kernel ABI include directory and overrides these
// defaults when its GPU or display interface differs from the A740 stack.
#ifndef NATIVE_ADRENO_SCANOUT_COPY
#define NATIVE_ADRENO_SCANOUT_COPY 1
#endif

#ifndef NATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE
#define NATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE 1
#endif

#ifndef NATIVE_ADRENO_A740_REPLAY
#define NATIVE_ADRENO_A740_REPLAY 1
#endif

#ifndef NATIVE_ADRENO_TURNIP_DEBUG
#define NATIVE_ADRENO_TURNIP_DEBUG "sysmem,nocb"
#endif

#ifndef NATIVE_ADRENO_TURNIP_SMOKE_DEBUG
#define NATIVE_ADRENO_TURNIP_SMOKE_DEBUG "nocb"
#endif
