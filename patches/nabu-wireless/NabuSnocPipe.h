// SPDX-License-Identifier: ISC
// Host configuration derived from ath10k snoc.c:
// Copyright (c) 2018 The Linux Foundation. All rights reserved.
#pragma once
#include "NabuSnocRing.h"

// Register access is supplied by the native SNOC owner. read/write take offsets
// within the board's 0x18800000 WLAN window; write must order MMIO. Never call
// initialize before WLAN_MODE ACK and established IOMMU/coherent DMA mappings.
struct NabuSnocPipe {
    struct Host { unsigned source_entries,destination_entries,max_bytes,flags; };
    static constexpr Host hosts[] = {
        {16,0,2048,0},{0,512,2048,0},{0,64,2048,0},{32,0,2048,0},
        {2048,0,256,8},{0,512,512,0},{0,0,0,0},{2,2,2048,0},
        {0,128,2048,0},{0,512,2048,0},{0,512,2048,0},{0,512,2048,0}
    };
    static constexpr uint32_t base(unsigned id){return 0x240000+id*0x1000;}
    template<class Bus>
    static void initialize(Bus &bus,unsigned id,NabuSnocRing &ring,uint64_t dma,bool source) {
        const uint32_t b=base(id);
        // Same initial index ownership as ath10k_ce_init_{src,dest}_ring.
        for(unsigned i=0;i<ring.count;++i) {
            auto &d=ring.descriptors[i];d.address=0;d.bytes=0;d.metadata=0;d.hash=0;
            ring.contexts[i]=nullptr;
        }
        ring.consumer=bus.read(b+(source?0x44:0x48))&(ring.count-1);
        ring.producer=bus.read(b+(source?0x3c:0x40))&(ring.count-1);
        bus.write(b+(source?0:0x0c),(uint32_t)dma);
        if(source)bus.write(b+4,(dma>>32)&31);
        else bus.write(b+0x10,(bus.read(b+0x10)&~31u)|((dma>>32)&31));
        bus.write(b+(source?8:0x14),ring.count);
        uint32_t control=bus.read(b+0x18);
        if(source)control=(control&~0x2ffffu)|hosts[id].max_bytes;
        else control&=~0x40000u;
        bus.write(b+0x18,control);
        // Low watermark = 0, high watermark = entry count.
        bus.write(b+(source?0x4c:0x50),ring.count);
    }
    template<class Bus>
    static void interrupts(Bus &bus,unsigned id,bool enable) {
        uint32_t b=base(id),value=bus.read(b+0x2c)&~0x1fu;
        // CE7 is diagnostic and CE8 is target/uMC: neither has a host callback.
        if(enable&&!(hosts[id].flags&8)&&id!=6&&id!=7&&id!=8)value|=1;
        bus.write(b+0x2c,value);
        if(!enable)bus.write(b+0x34,bus.read(b+0x34)&~0x3e0u);
    }
};
