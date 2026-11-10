// SPDX-License-Identifier: BSD-2-Clause-Patent
// Physical SSC samples to the real IOService transport. The caller supplies a
// verified current-boot Mach timestamp; this layer never invents sample time.
#pragma once
#include "NabuSscCensus.h"
#include "NabuSensorHid.h"

namespace NabuSsc {
template<class IO> class Native {
    struct Source {
        Suid suid{};
        uint64_t last_received_ms=0;
        bool active=false;
    } sources[NabuSensorKindCount];
    IO &io;
    static const Candidate *candidate(const Census<IO> &census,unsigned kind,Suid suid){
        const auto &d=census.discovery[kind];
        for(unsigned i=0;i<d.count;++i)
            if(equal(d.candidates[i].suid,suid))return &d.candidates[i];
        return nullptr;
    }
    static const typename Census<IO>::Stream *stream(const Census<IO> &census,Suid suid){
        for(unsigned i=0;i<census.stream_count;++i)
            if(equal(census.streams[i].suid,suid))return &census.streams[i];
        return nullptr;
    }
    void invalidate(unsigned kind,int32_t reason){
        auto &s=sources[kind];if(!s.active)return;
        io.native_invalidate(kind,reason);s.active=false;++invalidations;
    }
public:
    unsigned accepted[NabuSensorKindCount]{};
    unsigned rejected=0,invalidations=0;
    constexpr explicit Native(IO &provider):io(provider){}
    bool active(unsigned kind)const{return kind<NabuSensorKindCount&&sources[kind].active;}
    bool source(unsigned kind,Suid &suid)const{
        if(!active(kind))return false;suid=sources[kind].suid;return true;
    }
    void sample(const Census<IO> &census,unsigned kind,Suid suid,uint64_t ticks,
                const Sample &sample,uint64_t mach_timestamp,uint64_t now_ms){
        if(kind>=NabuSensorKindCount)return;
        const Candidate *c=candidate(census,kind,suid);
        const auto *wire=stream(census,suid);
        if(!mach_timestamp||!c||c->state!=State::Ready||!wire||!wire->sent||wire->failed||
           wire->disabled||census.result.stopping||census.result.done){++rejected;return;}
        auto &source=sources[kind];
        if(source.active&&!equal(source.suid,suid)){++rejected;return;}
        const auto &a=c->attributes;
        NabuSensorDescription description{};
        description.abi_version=NabuSensorSourceAbi;description.kind=kind;
        description.physical_suid[0]=suid.low;description.physical_suid[1]=suid.high;
        const size_t product_bytes=strlen(a.name),vendor_bytes=strlen(a.vendor);
        if(!product_bytes||product_bytes>=sizeof(description.product)||
           !vendor_bytes||vendor_bytes>=sizeof(description.manufacturer)||
           sample.count<(kind==NabuSensorAmbientLight?1u:3u)){
            ++rejected;return;
        }
        memcpy(description.product,a.name,product_bytes+1);
        memcpy(description.manufacturer,a.vendor,vendor_bytes+1);
        NabuSensorRecord record{};record.kind=kind;
        record.value_count=kind==NabuSensorAmbientLight?1:3;
        record.accuracy=sample.status;record.ssc_ticks=ticks;record.mach_timestamp=mach_timestamp;
        memcpy(record.value_bits,sample.values,record.value_count*sizeof(uint32_t));
        if(io.native_submit(description,record)){++rejected;return;}
        source.suid=suid;source.active=true;source.last_received_ms=now_ms;++accepted[kind];
    }
    void tick(const Census<IO> &census,uint64_t now_ms,int32_t lost_reason,int32_t stale_reason){
        for(unsigned kind=0;kind<NabuSensorKindCount;++kind){
            const auto &source=sources[kind];if(!source.active)continue;
            const Candidate *c=candidate(census,kind,source.suid);
            const auto *wire=stream(census,source.suid);
            if(census.result.stopping||census.result.done||!c||c->state!=State::Ready||
               !wire||wire->failed||wire->disabled){invalidate(kind,lost_reason);continue;}
            // Existing streaming requests are 25Hz, unbatched. An on-change ALS
            // can legitimately retain one reading and has no periodic deadline.
            if(c->attributes.stream_type==0&&now_ms-source.last_received_ms>=io.native_timeout_ms(kind))
                invalidate(kind,stale_reason);
        }
    }
    void stop(int32_t reason){for(unsigned kind=0;kind<NabuSensorKindCount;++kind)invalidate(kind,reason);}
};
}
