// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8150 nabu SLPI contracts from the connected Android DT and slpi_nb MDT.
// No hardware access: callers supply memory, MMIO operations and deadlines.
#pragma once
#include <stdint.h>
#include <stddef.h>
#include "../nabu-wireless/NabuSmem.h"

namespace NabuSlpi {
enum : uint32_t {
    MemoryBase=0x97b00000, MemorySize=0x01400000, MemoryEnd=0x98f00000,
    MetadataLimit=16384, MaxSegments=32, SmemSize=0x200000, Host=3, PasId=12,
    Incoming=430, Outgoing=481, Smp2pBytes=340, Smp2pDoorbell=26,
    GlinkDoorbell=24, GlinkDescriptor=478, GlinkTx=479, GlinkRx=480,
    GlinkFifoBytes=16384, SscService=400,
};
inline uint16_t le16(const uint8_t *p) {return uint16_t(p[0]) | uint16_t(p[1])<<8;}
inline uint32_t le32(const uint8_t *p) {return uint32_t(le16(p)) | uint32_t(le16(p+2))<<16;}
struct Segment {uint32_t index, original, physical, file_bytes, memory_bytes;const uint8_t *file;};
struct Image {const uint8_t *metadata;uint32_t metadata_bytes,count,link_base,load_bytes;bool relocated;Segment segments[MaxSegments];};

// Qualcomm relocatable MDT uses the lowest PT_LOAD paddr as its link base.
// PAS authenticates the original MDT; only destinations are relocated.
inline bool parse_image(const uint8_t *data,uint64_t bytes,Image &image) {
    image={};
    if(!data||bytes<52||bytes>MetadataLimit||le32(data)!=0x464c457f||
       data[4]!=1||data[5]!=1||le16(data+40)!=52||le16(data+42)!=32)return false;
    uint32_t offset=le32(data+28),count=le16(data+44),low=UINT32_MAX,high=0;
    if(!count||count>MaxSegments||offset<52||offset>bytes||count*32>bytes-offset)return false;
    for(uint32_t i=0;i<count;++i) {
        const uint8_t *ph=data+offset+i*32;
        uint32_t pa=le32(ph+12),file=le32(ph+16),mem=le32(ph+20),flags=le32(ph+24);
        if(le32(ph)!=1||!mem||((flags>>24)&7)==2)continue;
        if(file>mem||mem>UINT32_MAX-pa)return false;
        if(pa<low)low=pa;if(pa+mem>high)high=pa+mem;
        image.relocated|=(flags&0x08000000u)!=0;
        image.segments[image.count++]={i,pa,pa,file,mem,nullptr};
    }
    if(!image.count||high<low||high-low>MemorySize)return false;
    image.link_base=low;
    image.load_bytes=(high-low+4095u)&~4095u;
    if(image.load_bytes>MemorySize)return false;
    for(uint32_t i=0;i<image.count;++i) {
        Segment &s=image.segments[i];
        if(image.relocated)s.physical=MemoryBase+(s.original-low);
        if(s.physical<MemoryBase||s.physical>=MemoryEnd||s.memory_bytes>MemoryEnd-s.physical)return false;
        for(uint32_t j=0;j<i;++j) {
            const Segment &a=image.segments[j];
            if(s.physical<a.physical+a.memory_bytes&&a.physical<s.physical+s.memory_bytes)return false;
        }
    }
    image.metadata=data;image.metadata_bytes=uint32_t(bytes);return true;
}
inline bool partition(const NabuSmem &smem,uint32_t &base,uint32_t &line) {
    return smem.partition(Host,&base,&line)||smem.partition(0xfffe,&base,&line);
}
inline bool find(const NabuSmem &smem,uint16_t id,NabuSmemItem &item) {
    uint32_t base,line;return partition(smem,base,line)&&smem.item_in(base,line,id,&item);
}
// Caller holds the shared APPS allocation mutex and SMEM hardware spinlock3.
template<class Writer> bool allocate(const NabuSmem &smem,Writer &w,uint16_t id,uint32_t bytes,uint32_t &offset) {
    uint32_t base,line;if(!partition(smem,base,line))return false;
    NabuSmemItem item;
    if(smem.item_in(base,line,id,&item)){offset=item.offset;return item.size==bytes;}
    uint32_t size=(bytes+7)&~7u,free=smem.u32(base+12),limit=smem.u32(base+16);
    if(free<32||limit<free||limit-free<16+size)return false;
    uint32_t at=base+free;
    w.put(at,0xa5a5|(uint32_t(id)<<16));w.put(at+4,size);w.put(at+8,size-bytes);w.put(at+12,0);
    offset=at+16;for(uint32_t i=0;i<size;i+=4)w.put(offset+i,0);
    w.put(base+12,free+16+size);return true;
}
template<class Writer> void publish_smp2p(Writer &w,uint32_t at) {
    w.put(at,0x504d5324);w.put(at+8,Host<<16);w.put(at+12,0x10010);w.put(at+16,0);
    const char name[16]="master-kernel";
    for(unsigned i=0;i<16;i+=4)w.put(at+20+i,le32((const uint8_t*)name+i));
    w.put(at+36,0);w.put(at+4,0x101);
}
struct Peer {bool valid;uint32_t features,flags,state;};
inline Peer peer(const NabuSmem &smem) {
    NabuSmemItem item;
    if(!find(smem,Incoming,item)||item.size<Smp2pBytes||smem.u32(item.offset)!=0x504d5324||
       (smem.u32(item.offset+4)&255)!=1||smem.u32(item.offset+8)!=Host||smem.u16(item.offset+14)>16)return {};
    Peer p{true,smem.u32(item.offset+4)>>8,smem.u32(item.offset+16),0};
    const char name[16]="slave-kernel";
    for(unsigned i=0;i<smem.u16(item.offset+14);++i) {
        uint32_t at=item.offset+20+i*20;unsigned j=0;
        for(;j<16&&smem.data[at+j]==uint8_t(name[j]);++j){}
        if(j==16){p.state=smem.u32(at+16);return p;}
    }
    return {};
}
struct Outcome {bool prepared,aop_attempted,aop_on,proxy,pas_requested,init,memory,copied,auth,ready,stop_ack,shutdown,off,retained;};
template<class Operations> Outcome run(Operations &ops) {
    Outcome r{};r.prepared=ops.prepare();
    if(r.prepared) {
        r.aop_attempted=true;r.aop_on=ops.aop_vote(true);
        if(r.aop_on&&(r.proxy=ops.proxy_vote())) {
            r.pas_requested=true;r.init=ops.init_image();
            if(r.init&&(r.memory=ops.memory_setup())&&(r.copied=ops.copy_segments())) {
                r.auth=ops.auth_reset();
                if(r.auth){r.ready=ops.wait_ready();ops.observe();if(r.ready){ops.probe();r.stop_ack=ops.request_stop();}}
            }
        }
    }
    if(r.pas_requested){r.shutdown=ops.shutdown();if(!r.shutdown){r.retained=true;return r;}}
    if(r.aop_attempted)r.off=ops.aop_vote(false);
    ops.release();return r;
}
} // namespace NabuSlpi
