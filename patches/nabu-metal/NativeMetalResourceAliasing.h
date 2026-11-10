/* SPDX-License-Identifier: MIT */
/* Resource aliasing uses the runtime's heap accounting, not frontend flags. */
#ifndef NABU_METAL_RESOURCE_ALIASING_H
#define NABU_METAL_RESOURCE_ALIASING_H
#include <stdbool.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef struct NmbBuffer NmbBuffer;
typedef struct NmbTexture NmbTexture;
bool nmb_buffer_make_aliasable(const NmbBuffer *buffer);
bool nmb_buffer_is_aliasable(const NmbBuffer *buffer);
bool nmb_texture_make_aliasable(const NmbTexture *texture);
bool nmb_texture_is_aliasable(const NmbTexture *texture);
#ifdef __cplusplus
}
#endif
#endif
