// SPDX-License-Identifier: GPL-2.0-only
// Generated from MiCode audio-kernel d41f8e1a6827294af6a61adbe18544518e750166.
// Original register tables Copyright (c)2016-2018, The Linux Foundation.
// WCD934x1.1 on Nabu: ADC1 -> DEC6 -> codec port6 -> shared channel134.
#pragma once
#include <stdint.h>
namespace NabuTavilData {
enum Kind : uint8_t { Update, Word, Read, Interface, Connect, Define, Reconfigure, Remove, Disconnect };
struct Op {uint16_t reg;uint32_t value;uint16_t delay;uint8_t mask;Kind kind;};
static constexpr Op Initialize[]={
    {0x0003,0x1,0,0x03,Update}, // WCD934X_CODEC_RPM_CLK_MCLK_CFG
    {0x0629,0x75,0,0xff,Update}, // WCD934X_BIAS_VBG_FINE_ADJ
    {0x5022,0x7c,0,0xff,Update}, // WCD934X_CODEC_CPR_SVS_CX_VDD
    {0x5023,0x58,0,0xff,Update}, // WCD934X_CODEC_CPR_SVS2_CX_VDD
    {0x0b53,0x1,0,0x01,Update}, // WCD934X_CDC_RX0_RX_PATH_DSMDEM_CTL
    {0x0b67,0x1,0,0x01,Update}, // WCD934X_CDC_RX1_RX_PATH_DSMDEM_CTL
    {0x0b7b,0x1,0,0x01,Update}, // WCD934X_CDC_RX2_RX_PATH_DSMDEM_CTL
    {0x0b8f,0x1,0,0x01,Update}, // WCD934X_CDC_RX3_RX_PATH_DSMDEM_CTL
    {0x0ba3,0x1,0,0x01,Update}, // WCD934X_CDC_RX4_RX_PATH_DSMDEM_CTL
    {0x0bdf,0x1,0,0x01,Update}, // WCD934X_CDC_RX7_RX_PATH_DSMDEM_CTL
    {0x0bf3,0x1,0,0x01,Update}, // WCD934X_CDC_RX8_RX_PATH_DSMDEM_CTL
    {0x0b40,0x18,0,0x1e,Update}, // WCD934X_CDC_COMPANDER8_CTL7
    {0x0b38,0x18,0,0x1e,Update}, // WCD934X_CDC_COMPANDER7_CTL7
    {0x0b49,0x0,0,0x08,Update}, // WCD934X_CDC_RX0_RX_PATH_SEC0
    {0x0c03,0x0,0,0x03,Update}, // WCD934X_CDC_CLSH_DECAY_CTRL
    {0x066c,0x1,0,0x07,Update}, // WCD934X_MICB1_TEST_CTL_2
    {0x0c1b,0x12,0,0x3f,Update}, // WCD934X_CDC_BOOST0_BOOST_CFG1
    {0x0c1c,0x8,0,0x1c,Update}, // WCD934X_CDC_BOOST0_BOOST_CFG2
    {0x0c23,0x12,0,0x3f,Update}, // WCD934X_CDC_BOOST1_BOOST_CFG1
    {0x0c24,0x8,0,0x1c,Update}, // WCD934X_CDC_BOOST1_BOOST_CFG2
    {0x0213,0x9,0,0x1f,Update}, // WCD934X_CPE_SS_CPARMAD_BUFRDY_INT_PERIOD
    {0x0a33,0x0,0,0x01,Update}, // WCD934X_CDC_TX0_TX_PATH_CFG1
    {0x0a43,0x0,0,0x01,Update}, // WCD934X_CDC_TX1_TX_PATH_CFG1
    {0x0a53,0x0,0,0x01,Update}, // WCD934X_CDC_TX2_TX_PATH_CFG1
    {0x0a63,0x0,0,0x01,Update}, // WCD934X_CDC_TX3_TX_PATH_CFG1
    {0x0a73,0x0,0,0x01,Update}, // WCD934X_CDC_TX4_TX_PATH_CFG1
    {0x0a83,0x0,0,0x01,Update}, // WCD934X_CDC_TX5_TX_PATH_CFG1
    {0x0a93,0x0,0,0x01,Update}, // WCD934X_CDC_TX6_TX_PATH_CFG1
    {0x0aa3,0x0,0,0x01,Update}, // WCD934X_CDC_TX7_TX_PATH_CFG1
    {0x0ab3,0x0,0,0x01,Update}, // WCD934X_CDC_TX8_TX_PATH_CFG1
    {0x06b6,0x2,0,0x0f,Update}, // WCD934X_RX_OCP_CTL
    {0x06ce,0x3a,0,0xff,Update}, // WCD934X_HPH_OCP_CTL
    {0x06d4,0x1,0,0x01,Update}, // WCD934X_HPH_L_TEST
    {0x06d7,0x1,0,0x01,Update}, // WCD934X_HPH_R_TEST
    {0x0111,0x20,0,0xff,Update}, // WCD934X_CPE_FLL_CONFIG_CTL_2
    {0x0721,0x0,0,0x0c,Update}, // WCD934X_MBHC_NEW_CTL_2
    {0x0003,0x4,0,0x04,Update}, // WCD934X_CODEC_RPM_CLK_MCLK_CFG
    {0x0601,0x80,0,0x80,Update}, // WCD934X_ANA_BIAS
    {0x0601,0x40,1,0x40,Update}, // WCD934X_ANA_BIAS
    {0x0601,0x0,0,0x60,Update}, // WCD934X_ANA_BIAS
    {0x0711,0x80,0,0x80,Update}, // WCD934X_CLK_SYS_MCLK_PRG
    {0x0711,0x10,0,0x30,Update}, // WCD934X_CLK_SYS_MCLK_PRG
    {0x0711,0x0,0,0x02,Update}, // WCD934X_CLK_SYS_MCLK_PRG
    {0x0711,0x1,0,0x01,Update}, // WCD934X_CLK_SYS_MCLK_PRG
    {0x0711,0x0,0,0x02,Update}, // WCD934X_CLK_SYS_MCLK_PRG
    {0x0d42,0x1,0,0x01,Update}, // WCD934X_CDC_CLK_RST_CTRL_FS_CNT_CONTROL
    {0x0d41,0x1,0,0x01,Update}, // WCD934X_CDC_CLK_RST_CTRL_MCLK_CONTROL
    {0x0002,0x0,1,0x03,Update}, // WCD934X_CODEC_RPM_CLK_GATE
    {0x0025,0x10,0,0x1e,Update}, // WCD934X_CHIP_TIER_CTRL_EFUSE_CTL
    {0x0025,0x1,5,0x01,Update}, // WCD934X_CHIP_TIER_CTRL_EFUSE_CTL
    {0x0603,0x80,1,0x80,Update}, // WCD934X_ANA_RCO
    {0x0606,0x2,1,0x02,Update}, // WCD934X_ANA_BUCK_CTL
    {0x0606,0x1,1,0x01,Update}, // WCD934X_ANA_BUCK_CTL
    {0x0606,0x4,1,0x04,Update}, // WCD934X_ANA_BUCK_CTL
    {0x0039,0x1,0,0x01,Read}, // WCD934X_CHIP_TIER_CTRL_EFUSE_STATUS
    {0x5027,0x2c,0,0xff,Update}, // WCD934X_CODEC_CPR_SVS2_MIN_CX_VDD
    {0x0002,0x0,0,0x10,Update}, // WCD934X_CODEC_RPM_CLK_GATE
    {0x5001,0x820,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x94,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0xfc0,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x48,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0xf000,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x44,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0xbb80,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0xc0000178,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x0,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x160,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x10854522,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x60,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x10854509,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x64,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x108544dd,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x68,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x108544ad,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x6c,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x77e,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x70,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x7da,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x74,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x0,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x78,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x0,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x7c,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x42029,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x80,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x4002002a,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x90,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x5001,0x4002002b,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_DATA_0
    {0x5005,0x90,0,0xff,Word}, // WCD934X_CODEC_CPR_WR_ADDR_0
    {0x0c0a,0x0,0,0x0f,Update}, // WCD934X_CDC_CLSH_K2_MSB
    {0x0c0b,0x60,0,0xff,Update}, // WCD934X_CDC_CLSH_K2_LSB
    {0x021b,0x0,0,0x80,Update}, // WCD934X_CPE_SS_DMIC_CFG
    {0x0c1a,0x58,0,0x7c,Update}, // WCD934X_CDC_BOOST0_BOOST_CTL
    {0x0c22,0x58,0,0x7c,Update}, // WCD934X_CDC_BOOST1_BOOST_CTL
    {0x0bcf,0x8,0,0x08,Update}, // WCD934X_CDC_RX7_RX_PATH_CFG1
    {0x0be3,0x8,0,0x08,Update}, // WCD934X_CDC_RX8_RX_PATH_CFG1
    {0x0d82,0x2,0,0x02,Update}, // WCD934X_CDC_TOP_TOP_CFG1
    {0x0d82,0x1,0,0x01,Update}, // WCD934X_CDC_TOP_TOP_CFG1
    {0x0ac3,0x1,0,0x01,Update}, // WCD934X_CDC_TX9_SPKR_PROT_PATH_CFG0
    {0x0ac7,0x1,0,0x01,Update}, // WCD934X_CDC_TX10_SPKR_PROT_PATH_CFG0
    {0x0acb,0x1,0,0x01,Update}, // WCD934X_CDC_TX11_SPKR_PROT_PATH_CFG0
    {0x0acf,0x1,0,0x01,Update}, // WCD934X_CDC_TX12_SPKR_PROT_PATH_CFG0
    {0x006c,0x1,0,0x01,Update}, // WCD934X_DATA_HUB_SB_TX11_INP_CFG
    {0x0d42,0x1,0,0x01,Update}, // WCD934X_CDC_CLK_RST_CTRL_FS_CNT_CONTROL
    {0x0b34,0x80,0,0x80,Update}, // WCD934X_CDC_COMPANDER7_CTL3
    {0x0b3c,0x80,0,0x80,Update}, // WCD934X_CDC_COMPANDER8_CTL3
    {0x0b38,0x1,0,0x01,Update}, // WCD934X_CDC_COMPANDER7_CTL7
    {0x0b40,0x1,0,0x01,Update}, // WCD934X_CDC_COMPANDER8_CTL7
    {0x0002,0x0,0,0x08,Update}, // WCD934X_CODEC_RPM_CLK_GATE
    {0x8019,0xa,0,0xff,Update}, // WCD934X_TLMM_DMIC3_CLK_PINCFG
    {0x801a,0xa,0,0xff,Update}, // WCD934X_TLMM_DMIC3_DATA_PINCFG
    {0x0214,0x0,0,0x60,Update}, // WCD934X_CPE_SS_SVA_CFG
    {0x021c,0x10,0,0x10,Update}, // WCD934X_CPE_SS_CPAR_CFG
    {0x066b,0xfa,0,0xff,Update}, // WCD934X_MICB1_TEST_CTL_1
    {0x066e,0xfa,0,0xff,Update}, // WCD934X_MICB2_TEST_CTL_1
    {0x0671,0xfa,0,0xff,Update}, // WCD934X_MICB3_TEST_CTL_1
    {0x0674,0xfa,0,0xff,Update}, // WCD934X_MICB4_TEST_CTL_1
    {0x0b08,0x6,0,0x1e,Update}, // WCD934X_CDC_COMPANDER1_CTL7
    {0x0b10,0x6,0,0x1e,Update}, // WCD934X_CDC_COMPANDER2_CTL7
    {0x0733,0x84,0,0xff,Update}, // WCD934X_HPH_NEW_INT_RDAC_HD2_CTL_L
    {0x0736,0x84,0,0xff,Update}, // WCD934X_HPH_NEW_INT_RDAC_HD2_CTL_R
    {0x0b85,0xf4,0,0xfc,Update}, // WCD934X_CDC_RX3_RX_PATH_SEC0
    {0x0b99,0xf4,0,0xfc,Update}, // WCD934X_CDC_RX4_RX_PATH_SEC0
    {0x0712,0x20,0,0x60,Update}, // WCD934X_CLK_SYS_MCLK2_PRG1
    {0x0622,0x10,0,0x3f,Update}, // WCD934X_ANA_MICB1
    {0x0623,0x23,0,0x3f,Update}, // WCD934X_ANA_MICB2
    {0x0625,0x10,0,0x3f,Update}, // WCD934X_ANA_MICB3
    {0x0626,0x10,0,0x3f,Update}, // WCD934X_ANA_MICB4
};
static constexpr Op Start[]={
    {0x0d3b,0x20,0,0x30,Update}, // WCD934X_CDC_IF_ROUTER_TX_MUX_CFG1
    {0x0d22,0x4,0,0x0c,Update}, // WCD934X_CDC_TX_INP_MUX_ADC_MUX2_CFG1
    {0x0d28,0x1,0,0x07,Update}, // WCD934X_CDC_TX_INP_MUX_ADC_MUX6_CFG0
    {0x0a92,0x0,0,0x01,Update}, // WCD934X_CDC_TX6_TX_PATH_CFG0
    {0x0a91,0x4,0,0x0f,Update}, // WCD934X_CDC_TX6_TX_PATH_CTL
    {0x060e,0x28,0,0x7f,Update}, // WCD934X_ANA_AMIC1
    {0x0a94,0x0,0,0xff,Update}, // WCD934X_CDC_TX6_TX_VOL_CTL
    {0x0625,0x50,1,0xff,Update}, // WCD934X_ANA_MICB3
    {0x060f,0x40,0,0x40,Update}, // WCD934X_ANA_AMIC2
    {0x060e,0x80,0,0x80,Update}, // WCD934X_ANA_AMIC1
    {0x0a92,0x0,0,0x06,Update}, // WCD934X_CDC_TX6_TX_PATH_CFG0
    {0x0a91,0x10,0,0x10,Update}, // WCD934X_CDC_TX6_TX_PATH_CTL
    {0x0a91,0x20,0,0x20,Update}, // WCD934X_CDC_TX6_TX_PATH_CTL
    {0x0a92,0x40,0,0x60,Update}, // WCD934X_CDC_TX6_TX_PATH_CFG0
    {0x0a99,0x2,1,0x02,Update}, // WCD934X_CDC_TX6_TX_PATH_SEC2
    {0x0a99,0x0,40,0x02,Update}, // WCD934X_CDC_TX6_TX_PATH_SEC2
    {0x0a91,0x0,260,0x10,Update}, // WCD934X_CDC_TX6_TX_PATH_CTL
    {0x060f,0x0,0,0x40,Update}, // WCD934X_ANA_AMIC2
    {0x0a92,0x0,0,0x60,Update}, // WCD934X_CDC_TX6_TX_PATH_CFG0
    {0x0a99,0x2,1,0x02,Update}, // WCD934X_CDC_TX6_TX_PATH_SEC2
    {0x0a99,0x0,0,0x02,Update}, // WCD934X_CDC_TX6_TX_PATH_SEC2
    {0x01f6,0x2,0,0xff,Interface},
    {0x0118,0x40,0,0xff,Interface},
    {0x0119,0x0,0,0xff,Interface},
    {0x0056,0x5,0,0xff,Interface},
    {0x0000,0x0,0,0xff,Connect},
    {0x0000,0x0,0,0xff,Define},
    {0x0000,0x0,0,0xff,Reconfigure},
};
static constexpr Op Stop[]={
    {0x0000,0x0,0,0xff,Remove},
    {0x0000,0x0,0,0xff,Reconfigure},
    {0x0000,0x0,0,0xff,Disconnect},
    {0x0056,0x0,0,0xff,Interface},
    {0x0a91,0x10,0,0x10,Update}, // WCD934X_CDC_TX6_TX_PATH_CTL
    {0x0a91,0x0,0,0x20,Update}, // WCD934X_CDC_TX6_TX_PATH_CTL
    {0x060e,0x0,0,0x80,Update}, // WCD934X_ANA_AMIC1
    {0x060f,0x0,0,0x40,Update}, // WCD934X_ANA_AMIC2
    {0x0625,0x0,0,0xc0,Update}, // WCD934X_ANA_MICB3
    {0x0d3b,0x0,0,0x30,Update}, // WCD934X_CDC_IF_ROUTER_TX_MUX_CFG1
};
} // namespace NabuTavilData
