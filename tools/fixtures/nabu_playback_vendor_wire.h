// SPDX-License-Identifier: GPL-2.0-only
// Copyright (c) 2012-2020, The Linux Foundation. All rights reserved.
// Original field declarations from MiCode vendor audio
// d41f8e1a6827294af6a61adbe18544518e750166/include/dsp/apr_audio-v2.h.
// Comments removed; scalar types and the separately extracted APR header supplied.
#pragma once
#include "nabu_afe_vendor_wire.h"
namespace NabuPlaybackVendorFixture {
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;
using NabuAfeVendorFixture::apr_hdr;
#define __packed __attribute__((packed))
// source line 165
struct adm_session_map_node_v5 {
	u16                  session_id;
	u16                  num_copps;
} __packed;

// source line 183
struct adm_cmd_matrix_map_routings_v5 {
	struct apr_hdr	hdr;
	u32                  matrix_id;
	u32                  num_sessions;
} __packed;

// source line 297
struct adm_cmd_device_open_v5 {
	struct apr_hdr		hdr;
	u16                  flags;
	u16                  mode_of_operation;
	u16                  endpoint_id_1;
	u16                  endpoint_id_2;
	u32                  topology_id;
	u16                  dev_num_channel;
	u16                  bit_width;
	u32                  sample_rate;
	u8                   dev_channel_mapping[8];
} __packed;

// source line 727
struct adm_cmd_rsp_device_open_v5 {
	u32                  status;
	u16                  copp_id;
	u16                  reserved;
} __packed;

// source line 7443
struct asm_stream_cmd_open_write_v3 {
	struct apr_hdr			hdr;
	uint32_t                    mode_flags;
	uint16_t                    sink_endpointype;
	uint16_t                    bits_per_sample;
	uint32_t                    postprocopo_id;
	uint32_t                    dec_fmt_id;
} __packed;

// source line 5512
struct asm_data_cmd_media_fmt_update_v2 {
u32                    fmt_blk_size;
}  __packed;

// source line 5577
struct asm_multi_channel_pcm_fmt_blk_v2 {
	struct apr_hdr hdr;
	struct asm_data_cmd_media_fmt_update_v2 fmt_blk;
	u16  num_channels;
	u16  bits_per_sample;
	u32  sample_rate;
	u16  is_signed;
	u16  reserved;
	u8   channel_mapping[8];
} __packed;

// source line 7243
struct asm_session_cmd_run_v2 {
	struct apr_hdr hdr;
	u32                  flags;
	u32                  time_lsw;
	u32                  time_msw;
} __packed;

// source line 6811
struct asm_data_cmd_write_v2 {
	struct apr_hdr hdr;
	u32                  buf_addr_lsw;
	u32                  buf_addr_msw;
	u32                  mem_map_handle;
	u32                  buf_size;
	u32                  seq_id;
	u32                  timestamp_lsw;
	u32                  timestamp_msw;
	u32                  flags;
} __packed;

// source line 6948
struct asm_data_event_write_done_v2 {
	u32                  buf_addr_lsw;
	u32                  buf_addr_msw;
	u32                  mem_map_handle;
	u32                  status;
} __packed;

#undef __packed
} // namespace NabuPlaybackVendorFixture
