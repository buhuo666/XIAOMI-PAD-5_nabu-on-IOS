// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuRmtfs.h"

// SNOC HTC wire protocol from pinned ath10k htc.[ch]. A single native worker
// owns this object; CE transport owns the buffers and reports actual submission.
struct NabuHtc {
    struct Endpoint { uint16_t service=0,max_bytes=0,credits=0;uint8_t sequence=0; } endpoints[9]{};
    enum State { WaitingReady, Ready, Connecting, Started, Failed, Lost } state=WaitingReady;
    uint16_t credit_count=0,reported_credits=0,credit_size=0,pending_service=0;
    uint8_t max_endpoints=0,connect_error=0;
    bool waiting=false;
    unsigned elapsed=0,bytes=0;
    uint8_t request[20]{};

    static void put16(uint8_t *p,unsigned value){p[0]=value;p[1]=value>>8;}
    void header(uint8_t *p,unsigned endpoint,unsigned payload) {
        memset(p,0,8);p[0]=endpoint;put16(p+2,payload);
        p[1]=endpoints[endpoint].service==0x100?1:0;
        p[5]=endpoints[endpoint].sequence;
    }
    unsigned endpoint_for(unsigned service) const {
        for(unsigned i=1;i<9;++i)if(endpoints[i].service==service)return i;
        return 0;
    }
    bool connect(unsigned service) {
        if(state!=Ready||bytes||waiting||endpoint_for(service)||
           (service!=0x100&&service!=0x300))return false;
        memset(request,0,sizeof(request));header(request,0,8);
        put16(request+8,2);put16(request+10,service);
        put16(request+12,service==0x100?(credit_count&255)<<8:8);
        bytes=16;pending_service=service;state=Connecting;return true;
    }
    bool setup() {
        if(state!=Ready||bytes||!endpoint_for(0x100)||!endpoint_for(0x300))return false;
        memset(request,0,sizeof(request));header(request,0,12);put16(request+8,5);
        // SNOC does not enable the SDIO receive-bundling options.
        bytes=20;return true;
    }
    void sent() {
        if(!bytes)return;
        ++endpoints[0].sequence;bytes=0;elapsed=0;
        if(state==Connecting)waiting=true;else state=Started;
    }
    void tick(){if(state==WaitingReady||waiting){if(++elapsed>=5000){state=Failed;waiting=false;bytes=0;}}}
    void invalidate(){state=Lost;waiting=false;bytes=0;for(auto &ep:endpoints)ep={};}
    bool control(const uint8_t *p,unsigned length) {
        if(length<8)return false;
        unsigned id=NabuRmtfs::u16(p);
        if(id==1&&state==WaitingReady) {
            unsigned count=NabuRmtfs::u16(p+2),size=NabuRmtfs::u16(p+4);
            if(!size||p[6]<3)return false;
            // Pinned WCN3990/SNOC hw_params.use_fw_tx_credits=false.
            reported_credits=count;credit_count=1;credit_size=size;
            max_endpoints=p[6];elapsed=0;state=Ready;return true;
        }
        if(id!=3||state!=Connecting||!waiting||NabuRmtfs::u16(p+2)!=pending_service)return false;
        connect_error=p[4];unsigned eid=p[5],size=NabuRmtfs::u16(p+6);
        waiting=false;
        if(connect_error||!eid||eid>=9||eid>=max_endpoints||!size||endpoints[eid].service){state=Failed;return false;}
        endpoints[eid].service=pending_service;endpoints[eid].max_bytes=size;
        endpoints[eid].credits=pending_service==0x100?(credit_count&255):0;
        pending_service=0;state=Ready;return true;
    }
    // Returns the actual endpoint payload, excluding HTC credit trailer.
    bool receive(const uint8_t *packet,unsigned size,unsigned &endpoint,const uint8_t *&payload,unsigned &length) {
        payload=nullptr;length=0;
        if(state==Lost||state==Failed||size<8)return false;
        endpoint=packet[0];unsigned total=NabuRmtfs::u16(packet+2),trailer=(packet[1]&2)?packet[4]:0;
        if(endpoint>=9||total>size-8||trailer>total)return false;
        if(endpoint&&!endpoints[endpoint].service)return false;
        const uint8_t *tail=packet+8+total-trailer;
        // Validate complete record boundaries before accepting any returned credits.
        for(unsigned at=0;at<trailer;) {
            if(trailer-at<4||tail[at+1]>trailer-at-4)return false;
            unsigned n=tail[at+1];
            if(tail[at]==1) {
                if(!n||(n&3))return false;
                for(unsigned i=0;i<n;i+=4)if(tail[at+4+i]>=9)return false;
            }
            at+=4+n;
        }
        for(unsigned at=0;at<trailer;at+=4+tail[at+1])if(tail[at]==1)
            for(unsigned i=0;i<tail[at+1];i+=4)endpoints[tail[at+4+i]].credits+=tail[at+5+i];
        payload=packet+8;length=total-trailer;
        return endpoint||(!length&&trailer)?true:control(payload,length);
    }
    bool prepare_wmi(uint8_t *packet,unsigned payload_bytes) {
        unsigned eid=endpoint_for(0x100);
        if(!eid||state==Lost||state==Failed||payload_bytes>endpoints[eid].max_bytes)return false;
        unsigned credits=(payload_bytes+8+credit_size-1)/credit_size;
        if(endpoints[eid].credits<credits)return false;
        header(packet,eid,payload_bytes);return true;
    }
    void wmi_sent(unsigned payload_bytes) {
        unsigned eid=endpoint_for(0x100);
        endpoints[eid].credits-=(payload_bytes+8+credit_size-1)/credit_size;
        ++endpoints[eid].sequence;
    }
};
