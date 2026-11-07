// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

// WCN399x CE descriptors are 16 bytes, unlike the 8-byte legacy CE format.
// Caller owns DMA mapping, cache maintenance, serialization and MMIO barriers.
// source/destination rings reserve one entry and publish producer only after
// descriptor/cache release. Completion consumes only device-visible results.
struct NabuSnocRing {
    struct alignas(8) Descriptor {
        uint64_t address;
        uint16_t bytes, metadata;
        uint32_t hash;
    };
    static_assert(sizeof(Descriptor)==16,"WCN399x CE descriptor size");
    volatile Descriptor *descriptors;
    void **contexts;
    unsigned count, producer=0, consumer=0;
    bool stopped=false;
    unsigned next(unsigned index) const{return (index+1)&(count-1);}
    unsigned available() const{return (consumer-producer-1)&(count-1);}
    bool post(uint64_t dma,uint16_t size,uint16_t transfer,void *context) {
        if(stopped||!available()||dma>>35)return false;
        auto &d=descriptors[producer];
        d.address=dma;d.bytes=size;d.metadata=(transfer<<4)&0xfff0;d.hash=0;
        contexts[producer]=context;producer=next(producer);return true;
    }
    bool post_receive(uint64_t dma,void *context){return post(dma,0,0,context);}
    bool complete_receive(void *&context,uint16_t &size) {
        if(stopped||consumer==producer)return false;
        auto &d=descriptors[consumer];
        size=d.bytes;
        if(!size)return false; // Hardware may publish DRRI before the descriptor.
        context=contexts[consumer];contexts[consumer]=nullptr;d.bytes=0;
        consumer=next(consumer);return true;
    }
    bool complete_send(unsigned hardware_consumer,void *&context) {
        if(stopped||hardware_consumer>=count||consumer==producer||consumer==hardware_consumer)return false;
        context=contexts[consumer];contexts[consumer]=nullptr;consumer=next(consumer);return true;
    }
    // Do not recycle buffers on PFR. DMA ownership ends only after hardware stop.
    void invalidate(){stopped=true;}
};
