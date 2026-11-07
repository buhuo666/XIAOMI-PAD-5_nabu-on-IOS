// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuWlanDma.h"
#include "NabuSnocPipe.h"
#include "NabuHtc.h"

// One serialized worker; real native adapters are in NabuWlanRuntime.cpp.
// RX/descriptor ownership is explicit. Descriptor/RRI chunks use uncached CPU
// aliases, so a cache-line clean cannot overwrite a neighbor written by CE DMA.
struct NabuWlanTransport {
    using Buffer=NabuWlanDma::Buffer;
    struct Ops {
        void *cookie;
        bool (*allocate)(void *,unsigned,unsigned,Buffer &);
        void *(*alias)(void *,const Buffer &);
        void (*sync)(void *,Buffer &);
        uint32_t (*read)(void *,unsigned);
        void (*write)(void *,unsigned,uint32_t);
        void (*barrier)(void *);
        void (*event)(void *,const char *,unsigned,unsigned);
    } ops{};
    struct Ring {
        NabuSnocRing ce{nullptr,nullptr,0};Buffer descriptors{};
        Buffer *packets=nullptr;unsigned id=0;bool source=false;
    } rings[24]{};
    static constexpr unsigned total_buffers=4852;
    Buffer packets[total_buffers]{};
    void *contexts[total_buffers]{};
    Buffer rri{};volatile uint32_t *read_indices=nullptr;
    unsigned ring_count=0,buffer_count=0,ticks=0;
    unsigned tx_packets=0,tx_completed=0,rx_packets=0,htc_packets=0,wmi_packets=0,other_packets=0,malformed=0;
    uint32_t last_wmi_event=0;
    bool htc_ready_seen=false,wmi_connected_seen=false;
    NabuHtc htc{};
    enum Phase { Empty, Prepared, Running, Failed, Lost } phase=Empty;
    void event(const char *name,unsigned a=0,unsigned b=0){ops.event(ops.cookie,name,a,b);}
    uint32_t read(unsigned at){return ops.read(ops.cookie,at);}
    void write(unsigned at,uint32_t value){ops.write(ops.cookie,at,value);}
    void barrier(){ops.barrier(ops.cookie);}
    Ring *find(unsigned id,bool source) {
        for(unsigned i=0;i<ring_count;++i)if(rings[i].id==id&&rings[i].source==source)return &rings[i];
        return nullptr;
    }
    bool prepare(const Ops &platform) {
        if(phase!=Empty)return false;ops=platform;
        // Each descriptor array has a dedicated whole chunk; no WB packet data
        // shares its uncached alias. Original WB aliases are never touched again.
        for(unsigned id=0;id<12;++id)for(unsigned direction=0;direction<2;++direction) {
            bool source=direction==0;const auto &host=NabuSnocPipe::hosts[id];
            unsigned count=source?host.source_entries:host.destination_entries;if(!count)continue;
            Ring &r=rings[ring_count++];r.id=id;r.source=source;
            if(!ops.allocate(ops.cookie,65536,65536,r.descriptors))return fail("descriptor-allocation",id);
            auto *alias=(volatile NabuSnocRing::Descriptor *)ops.alias(ops.cookie,r.descriptors);
            if(!alias)return fail("descriptor-alias",id);
            r.ce={alias,contexts+buffer_count,count};r.packets=packets+buffer_count;buffer_count+=count;
        }
        if(buffer_count!=total_buffers)return fail("host-ring-count",buffer_count);
        if(!ops.allocate(ops.cookie,65536,65536,rri))return fail("rri-allocation");
        read_indices=(volatile uint32_t *)ops.alias(ops.cookie,rri);
        if(!read_indices)return fail("rri-alias");
        for(unsigned n=0;n<ring_count;++n) {
            Ring &r=rings[n];unsigned bytes=NabuSnocPipe::hosts[r.id].max_bytes;
            for(unsigned i=0;i<r.ce.count;++i)
                if(!ops.allocate(ops.cookie,bytes,64,r.packets[i]))return fail("packet-allocation",r.id,i);
        }
        phase=Prepared;event("resources-allocated",ring_count,buffer_count);return true;
    }
    bool fail(const char *reason,unsigned a=0,unsigned b=0) {
        phase=Failed;htc.invalidate();
        for(unsigned i=0;i<ring_count;++i)rings[i].ce.invalidate();
        event(reason,a,b);return false;
    }
    bool start() {
        if(phase!=Prepared)return false;
        // Called only after real CFG/MODE ACK, while the owner remains attached.
        for(unsigned id=0;id<12;++id)NabuSnocPipe::interrupts(*this,id,false);
        for(unsigned id=0;id<12;++id)read_indices[id]=0;
        barrier();write(0x24c004,rri.iova);write(0x24c008,0);
        for(unsigned id=0;id<12;++id) {
            unsigned at=NabuSnocPipe::base(id)+0x18;write(at,read(at)|0x80000);
        }
        for(unsigned i=0;i<ring_count;++i) {
            auto &r=rings[i];NabuSnocPipe::initialize(*this,r.id,r.ce,r.descriptors.iova,r.source);
            // New firmware instance must start empty. Never overwrite descriptors
            // still owned by a prior hardware queue.
            if(r.ce.consumer!=r.ce.producer)return fail("nonempty-ce-at-start",r.id,r.ce.consumer);
        }
        phase=Running;
        for(unsigned i=0;i<ring_count;++i) {
            auto &r=rings[i];if(r.source)continue;
            // Leave one slot unposted; each consumed buffer is reposted afterward.
            for(unsigned j=0;j+1<r.ce.count;++j) {
                Buffer &b=r.packets[j];ops.sync(ops.cookie,b);
                if(!r.ce.post_receive(b.iova,&b))return fail("initial-rx-post",r.id,j);
            }
            barrier();write(NabuSnocPipe::base(r.id)+0x40,r.ce.producer);
        }
        event("ce-polling-started",ring_count,0);return true;
    }
    bool transmit(unsigned pipe,const uint8_t *data,unsigned bytes) {
        if(phase!=Running)return false;
        Ring *r=find(pipe,true);
        if(!r||!r->ce.available()||bytes>NabuSnocPipe::hosts[pipe].max_bytes)return false;
        Buffer &b=r->packets[r->ce.producer];memcpy(b.cpu,data,bytes);ops.sync(ops.cookie,b);
        if(!r->ce.post(b.iova,(uint16_t)bytes,0,&b))return false;
        barrier();
        // WCN3990 shadow_reg_support: source ring doorbells are NOT CE+0x3c.
        write(0x32000+pipe*4,r->ce.producer);++tx_packets;return true;
    }
    void receive(unsigned pipe,Buffer &b,unsigned bytes) {
        ++rx_packets;
        if(bytes>b.bytes){++malformed;fail("rx-length",pipe,bytes);return;}
        ops.sync(ops.cookie,b);
        // CE5 raw HTT/CE7 diagnostic/CE8 uMC are not consumed as HTC control.
        if(pipe==5||pipe==7||pipe==8){++other_packets;return;}
        unsigned endpoint=0,length=0;const uint8_t *payload=nullptr;
        if(!htc.receive((const uint8_t *)b.cpu,bytes,endpoint,payload,length)) {
            ++malformed;event("htc-rejected",pipe,bytes);return;
        }
        ++htc_packets;
        if(endpoint&&htc.endpoints[endpoint].service==0x100) {
            ++wmi_packets;
            if(length>=4)last_wmi_event=NabuRmtfs::u32(payload)&0xffffff;
            if(wmi_packets<=8)event("wmi-event",last_wmi_event,length);
        }
    }
    void poll() {
        if(phase!=Running)return;++ticks;
        barrier();
        for(unsigned n=0;n<ring_count&&phase==Running;++n) {
            Ring &r=rings[n];void *context=nullptr;
            if(r.source) {
                unsigned consumed=(r.id==4)?(read_indices[r.id]&0xffff):read(NabuSnocPipe::base(r.id)+0x44);
                if(consumed==0xffffffff){fail("ce-read-failed",r.id);break;}
                consumed&=r.ce.count-1;
                for(unsigned budget=0;budget<32&&r.ce.complete_send(consumed,context);++budget)++tx_completed;
                continue;
            }
            unsigned processed=0;uint16_t bytes=0;
            while(processed<32&&r.ce.complete_receive(context,bytes)) {
                Buffer &b=*(Buffer *)context;receive(r.id,b,bytes);if(phase!=Running)break;
                ops.sync(ops.cookie,b); // Return this whole packet buffer to the device.
                if(!r.ce.post_receive(b.iova,&b)){fail("rx-repost",r.id);break;}
                ++processed;
            }
            if(processed&&phase==Running){barrier();write(NabuSnocPipe::base(r.id)+0x40,r.ce.producer);}
        }
        if(phase!=Running)return;
        if(!htc_ready_seen&&htc.state==NabuHtc::Ready) {
            htc_ready_seen=true;event("htc-ready",htc.reported_credits,htc.credit_size);
        }
        if(htc.state==NabuHtc::Ready&&!htc.endpoint_for(0x100))htc.connect(0x100);
        if(htc.bytes&&transmit(0,htc.request,htc.bytes))htc.sent();
        if(!wmi_connected_seen&&htc.endpoint_for(0x100)) {
            wmi_connected_seen=true;event("wmi-connected",htc.endpoint_for(0x100),htc.endpoints[htc.endpoint_for(0x100)].max_bytes);
            event("htt-and-setup-deferred",0,0);
        }
        htc.tick();
        if(htc.state==NabuHtc::Failed)fail("htc-timeout-or-error");
    }
    void lost() {
        if(phase==Failed||phase==Lost)return;
        phase=Lost;htc.invalidate();for(unsigned i=0;i<ring_count;++i)rings[i].ce.invalidate();
    }
};
