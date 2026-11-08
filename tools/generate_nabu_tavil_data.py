#!/usr/bin/env python3
"""Extract pinned original WCD934x setup tables and compose Nabu main-mic steps."""
import argparse
import re
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--registers',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();s=a.source.read_text();header=a.registers.read_text()
    names={k:int(v,16) for k,v in re.findall(r'^#define\s+(WCD934X_\w+)\s+(0x[0-9a-fA-F]+)\b',header,re.M)}
    out=['// SPDX-License-Identifier: GPL-2.0-only',
         '// Generated from MiCode audio-kernel d41f8e1a6827294af6a61adbe18544518e750166.',
         '// Original register tables Copyright (c)2016-2018, The Linux Foundation.',
         '// WCD934x1.1 on Nabu: ADC1 -> DEC6 -> codec port6 -> shared channel134.',
         '#pragma once','#include <stdint.h>','namespace NabuTavilData {',
         'enum Kind : uint8_t { Update, Word, Read, Interface, Connect, Define, Reconfigure, Remove, Disconnect };',
         'struct Op {uint16_t reg;uint32_t value;uint16_t delay;uint8_t mask;Kind kind;};']
    current=[]
    def begin(name):
        nonlocal current
        current=[];out.append('static constexpr Op '+name+'[]={')
    def add(reg,value,mask=255,delay=0,kind='Update'):
        name=reg if isinstance(reg,str) else ''
        reg=names[reg] if isinstance(reg,str) else reg
        out.append(f'    {{0x{reg:04x},0x{value:x},{delay},0x{mask:02x},{kind}}},'+(' // '+name if name else ''))
        current.append(reg)
    def table(name):
        body=re.search(r'\b'+name+r'\[\]\s*=\s*\{(.*?)\n\};',s,re.S)[1]
        for reg,mask,value in re.findall(r'\{(WCD934X_\w+),\s*(0x[0-9a-fA-F]+),\s*(0x[0-9a-fA-F]+)\}',body):
            add(reg,int(value,16),int(mask,16))
    def end():out.append('};')
    begin('Initialize')
    add('WCD934X_CODEC_RPM_CLK_MCLK_CFG',1,3)
    table('tavil_codec_reg_defaults')
    # Master bias and MCLK sequence: resmgr deliberately skips unsupported ANA_CLK_TOP.
    add('WCD934X_ANA_BIAS',0x80,0x80);add('WCD934X_ANA_BIAS',0x40,0x40,1)
    add('WCD934X_ANA_BIAS',0,0x60)
    for mask,value in [(0x80,0x80),(0x30,0x10),(2,0),(1,1),(2,0)]:add('WCD934X_CLK_SYS_MCLK_PRG',value,mask)
    add('WCD934X_CDC_CLK_RST_CTRL_FS_CNT_CONTROL',1,1)
    add('WCD934X_CDC_CLK_RST_CTRL_MCLK_CONTROL',1,1)
    add('WCD934X_CODEC_RPM_CLK_GATE',0,3,1)
    add('WCD934X_CHIP_TIER_CTRL_EFUSE_CTL',0x10,0x1e)
    add('WCD934X_CHIP_TIER_CTRL_EFUSE_CTL',1,1,5)
    add('WCD934X_ANA_RCO',0x80,0x80,1)
    for mask,value in [(2,2),(1,1),(4,4)]:add('WCD934X_ANA_BUCK_CTL',value,mask,1)
    add('WCD934X_CHIP_TIER_CTRL_EFUSE_STATUS',1,1,kind='Read')
    add('WCD934X_CODEC_CPR_SVS2_MIN_CX_VDD',0x2c)
    add('WCD934X_CODEC_RPM_CLK_GATE',0,0x10)
    body=re.search(r'\bcpr_defaults\[\]\s*=\s*\{(.*?)\n\};',s,re.S)[1]
    for data,address in re.findall(r'\{\s*(0x[0-9a-fA-F]+),\s*(0x[0-9a-fA-F]+)\s*\}',body):
        add('WCD934X_CODEC_CPR_WR_DATA_0',int(data,16),kind='Word')
        add('WCD934X_CODEC_CPR_WR_ADDR_0',int(address,16),kind='Word')
    table('tavil_codec_reg_init_common_val');table('tavil_codec_reg_init_1_1_val')
    table('tavil_codec_mclk2_1_1_defaults')
    for i,v in enumerate((16,35,16,16),1):add('WCD934X_ANA_MICB'+str(i),v,0x3f)
    end()
    begin('Start')
    # Nabu main-mic XML, DAPM PRE/POST events, original48k/S16 channel scheduling.
    add('WCD934X_CDC_IF_ROUTER_TX_MUX_CFG1',0x20,0x30)
    add('WCD934X_CDC_TX_INP_MUX_ADC_MUX2_CFG1',4,12)
    add('WCD934X_CDC_TX_INP_MUX_ADC_MUX6_CFG0',1,7)
    add('WCD934X_CDC_TX6_TX_PATH_CFG0',0,1) # AMIC, not DMIC
    add('WCD934X_CDC_TX6_TX_PATH_CTL',4,15) #48k
    add('WCD934X_ANA_AMIC1',0x28,0x7f) # original ADC8, default power
    add('WCD934X_CDC_TX6_TX_VOL_CTL',0) # original DEC control84 is0dB (min-84)
    add('WCD934X_ANA_MICB3',0x50,0xff,1) #1.8V enabled
    add('WCD934X_ANA_AMIC2',0x40,0x40) #ADC1 hold
    add('WCD934X_ANA_AMIC1',0x80,0x80)
    add('WCD934X_CDC_TX6_TX_PATH_CFG0',0,6)
    add('WCD934X_CDC_TX6_TX_PATH_CTL',0x10,0x10)
    add('WCD934X_CDC_TX6_TX_PATH_CTL',0x20,0x20)
    add('WCD934X_CDC_TX6_TX_PATH_CFG0',0x40,0x60)
    add('WCD934X_CDC_TX6_TX_PATH_SEC2',2,2,1)
    add('WCD934X_CDC_TX6_TX_PATH_SEC2',0,2,40)
    add('WCD934X_CDC_TX6_TX_PATH_CTL',0,0x10,260)
    add('WCD934X_ANA_AMIC2',0,0x40)
    add('WCD934X_CDC_TX6_TX_PATH_CFG0',0,0x60)
    add('WCD934X_CDC_TX6_TX_PATH_SEC2',2,2,1)
    add('WCD934X_CDC_TX6_TX_PATH_SEC2',0,2)
    for reg,value in [(0x1f6,2),(0x118,0x40),(0x119,0),(0x56,5)]:add(reg,value,kind='Interface')
    for kind in ['Connect','Define','Reconfigure']:add(0,0,kind=kind)
    end()
    begin('Stop')
    add(0,0,kind='Remove');add(0,0,kind='Reconfigure');add(0,0,kind='Disconnect')
    add(0x56,0,kind='Interface')
    add('WCD934X_CDC_TX6_TX_PATH_CTL',0x10,0x10)
    add('WCD934X_CDC_TX6_TX_PATH_CTL',0,0x20)
    add('WCD934X_ANA_AMIC1',0,0x80)
    add('WCD934X_ANA_AMIC2',0,0x40)
    add('WCD934X_ANA_MICB3',0,0xc0)
    add('WCD934X_CDC_IF_ROUTER_TX_MUX_CFG1',0,0x30)
    end();out.append('} // namespace NabuTavilData')
    a.output.write_text('\n'.join(out)+'\n');print(a.output)

if __name__=='__main__':main()
