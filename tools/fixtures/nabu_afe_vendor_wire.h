// SPDX-License-Identifier: GPL-2.0-only
// Copyright (c) 2010-2020, The Linux Foundation. All rights reserved.
// Extracted field declarations, comments removed, from MiCode vendor audio
// d41f8e1a6827294af6a61adbe18544518e750166 include/ipc/apr.h and
// include/dsp/apr_audio-v2.h. Kept separate from production byte encoders.
#pragma once
#include <stdint.h>
namespace NabuAfeVendorFixture {
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;
#define __packed __attribute__((packed))
#define AFE_GROUP_DEVICE_NUM_PORTS 8
#define AFE_PORT_MAX_AUDIO_CHAN_CNT 8
// apr_hdr: source line 32
struct apr_hdr {
	uint16_t hdr_field;
	uint16_t pkt_size;
	uint8_t src_svc;
	uint8_t src_domain;
	uint16_t src_port;
	uint8_t dest_svc;
	uint8_t dest_domain;
	uint16_t dest_port;
	uint32_t token;
	uint32_t opcode;
};

// mem_mapping_hdr: source line 36
struct mem_mapping_hdr {
	u32 data_payload_addr_lsw;
	u32 data_payload_addr_msw;
	u32 mem_map_handle;
} __packed;

// param_hdr_v3: source line 96
struct param_hdr_v3 {
	uint32_t module_id;
	uint16_t instance_id;
	uint16_t reserved;
	uint32_t param_id;
	uint32_t param_size;
} __packed;

// afe_clk_set: source line 11340
struct afe_clk_set {
	uint32_t clk_set_minor_version;
	uint32_t clk_id;
	uint32_t clk_freq_in_hz;
	uint16_t clk_attri;
	uint16_t clk_root;
	uint32_t enable;
};

// afe_param_id_group_device_tdm_cfg: source line 11701
struct afe_param_id_group_device_tdm_cfg {
	u32	group_device_cfg_minor_version;
	u16	group_id;
	u16	reserved;
	u16	port_id[AFE_GROUP_DEVICE_NUM_PORTS];
	u32	num_channels;
	u32	sample_rate;
	u32	bit_width;
	u16	nslots_per_frame;
	u16	slot_width;
	u32	slot_mask;
} __packed;

// afe_group_device_enable: source line 11847
struct afe_group_device_enable {
	u16 group_id;
	u16 enable;
} __packed;

// afe_param_id_tdm_cfg: source line 3496
struct afe_param_id_tdm_cfg {
	u32	tdm_cfg_minor_version;
	u32	num_channels;
	u32	sample_rate;
	u32	bit_width;
	u16	data_format;
	u16	sync_mode;
	u16	sync_src;
	u16	nslots_per_frame;
	u16	ctrl_data_out_enable;
	u16	ctrl_invert_sync_pulse;
	u16	ctrl_sync_data_delay;
	u16	slot_width;
	u32	slot_mask;
} __packed;

// afe_param_id_slot_mapping_cfg: source line 3624
struct afe_param_id_slot_mapping_cfg {
	u32	minor_version;
	u16	num_channel;
	u16	bitwidth;
	u32	data_align_type;
	u16	offset[AFE_PORT_MAX_AUDIO_CHAN_CNT];
} __packed;

// afe_param_id_island_cfg_t: source line 4579
struct afe_param_id_island_cfg_t {
	uint32_t	island_cfg_minor_version;
	uint32_t	island_enable;
} __packed;

// afe_svc_cmd_set_param_v2: source line 11589
struct afe_svc_cmd_set_param_v2 {
	struct apr_hdr apr_hdr;
	struct mem_mapping_hdr mem_hdr;
	u32 payload_size;
	u32 param_data[0];
} __packed;

// afe_port_cmd_set_param_v3: source line 1998
struct afe_port_cmd_set_param_v3 {
	struct apr_hdr apr_hdr;
	u16 port_id;
	u16 reserved;
	struct mem_mapping_hdr mem_hdr;
	u32 payload_size;
	u8 param_data[0];
} __packed;

// afe_port_cmd_device_start: source line 4752
struct afe_port_cmd_device_start {
	struct apr_hdr hdr;
	u16                  port_id;
	u16                  reserved;
} __packed;

// afe_port_cmd_device_stop: source line 4769
struct afe_port_cmd_device_stop {
	struct apr_hdr hdr;
	u16                  port_id;
	u16                  reserved;
} __packed;

#undef AFE_PORT_MAX_AUDIO_CHAN_CNT
#undef AFE_GROUP_DEVICE_NUM_PORTS
#undef __packed
} // namespace NabuAfeVendorFixture
