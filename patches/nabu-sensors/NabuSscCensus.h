// SPDX-License-Identifier: BSD-2-Clause-Patent
// Finite live SSC discovery/sampling. The transport supplies a freshly discovered
// service endpoint. No native service is published by this diagnostic.
#pragma once
#include "NabuSscProtocol.h"

namespace NabuSsc {
template<class IO> class Census {
public:
    enum : unsigned {TypeCount=7,StreamLimit=16,RequestLimit=160,ClientPort=0x100};
    enum RequestKind : uint8_t {Lookup,AttributesRequest,ConfigureRequest,DisableRequest};
    struct Stream {
        Suid suid;
        unsigned type=0,samples=0,nonmonotonic=0;
        uint64_t first=0,last=0;
        bool sent=false,configured=false,disabled=false;
        Sample latest;
    };
    struct Result {
        bool started=false,stopping=false,done=false,has_client=false;
        uint64_t client=0;
        unsigned sent=0,responses=0,invalid=0,foreign=0,qmi_failures=0,errors=0;
    };
    Discovery discovery[TypeCount]{};
    Stream streams[StreamLimit]{};
    unsigned stream_count=0;
    Result result{};
    static const char *type(unsigned i){
        const char *names[]={"accel","gyro","mag","ambient_light","pressure","proximity","ambient_light_back"};
        return i<TypeCount?names[i]:"unknown";
    }
private:
    struct Request {
        Suid suid;
        unsigned type=0;
        RequestKind kind=Lookup;
        bool sent=false,responded=false;
    };
    IO &io;
    Request requests[RequestLimit]{};
    unsigned request_count=0;
    uint32_t node=0,port=0;
    uint64_t started_ms=0,stop_ms=0;

    bool add(RequestKind kind,unsigned index,Suid suid={}){
        if(request_count==RequestLimit){++result.errors;return false;}
        Request &q=requests[request_count++];q.kind=kind;q.type=index;q.suid=suid;return true;
    }
    bool resolved()const{
        for(const auto &d:discovery){
            if(d.state==State::Lookup)return false;
            for(unsigned i=0;i<d.count;++i)if(d.candidates[i].state==State::Attributes)return false;
        }
        return true;
    }
    void configure(unsigned index,Suid suid,const Attributes &a){
        if(a.stream_type!=0&&a.stream_type!=1)return;
        for(unsigned i=0;i<stream_count;++i)if(equal(streams[i].suid,suid))return;
        if(stream_count==StreamLimit){++result.errors;return;}
        if(add(ConfigureRequest,index,suid)){
            auto &s=streams[stream_count++];s.suid=suid;s.type=index;
        }
    }
    const Attributes *attributes(const Request &q)const{
        const auto &d=discovery[q.type];
        for(unsigned i=0;i<d.count;++i)if(equal(d.candidates[i].suid,q.suid))return &d.candidates[i].attributes;
        return nullptr;
    }
    void send_pending(){
        for(unsigned i=0;i<request_count;++i){
            Request &q=requests[i];if(q.sent)continue;
            if(result.stopping&&q.kind!=DisableRequest)continue;
            uint8_t bytes[512];size_t size=0;uint16_t txn=uint16_t(i+1);
            switch(q.kind){
            case Lookup:size=encode_lookup(bytes,sizeof bytes,txn,type(q.type));break;
            case AttributesRequest:size=encode_attributes(bytes,sizeof bytes,txn,q.suid);break;
            case ConfigureRequest:{
                const auto *a=attributes(q);if(!a){++result.errors;return;}
                // The requested rate is constant. Sample/attribute float words
                // are decoded as raw bits, with no in-kernel unit arithmetic.
                size=encode_configure(bytes,sizeof bytes,txn,q.suid,a->stream_type==1,25.0f);break;
            }
            case DisableRequest:size=encode_disable(bytes,sizeof bytes,txn,q.suid);break;
            }
            if(!size){++result.errors;return;}
            if(!io.send_ssc(node,port,ClientPort,bytes,unsigned(size)))return;
            q.sent=true;++result.sent;
            if(q.kind==ConfigureRequest)for(unsigned s=0;s<stream_count;++s)
                if(equal(streams[s].suid,q.suid))streams[s].sent=true;
        }
    }
    void stop(uint64_t now){
        result.stopping=true;stop_ms=now;
        for(unsigned i=0;i<stream_count;++i)if(streams[i].sent)add(DisableRequest,streams[i].type,streams[i].suid);
    }
    void response(const QmiPacket &p){
        if(!p.transaction||p.transaction>request_count){++result.invalid;return;}
        Request &q=requests[p.transaction-1];
        if(!q.sent||q.responded){++result.invalid;return;}
        if(p.has_client&&result.has_client&&p.client!=result.client){++result.foreign;return;}
        q.responded=true;++result.responses;
        if(p.result||p.error||(p.has_response&&p.response)){
            ++result.qmi_failures;
            if(q.kind==Lookup)discovery[q.type].state=State::Unavailable;
            return;
        }
        if(p.has_client){result.has_client=true;result.client=p.client;}
        for(unsigned i=0;i<stream_count;++i)if(equal(streams[i].suid,q.suid)){
            if(q.kind==ConfigureRequest)streams[i].configured=true;
            if(q.kind==DisableRequest)streams[i].disabled=true;
        }
    }
    static void event(Suid suid,uint32_t id,uint64_t ticks,Span payload,void *context){
        auto &self=*static_cast<Census *>(context);
        if(equal(suid,lookup_suid())&&id==SuidEvent){
            SuidList list;if(!parse_suids(payload,list)){++self.result.invalid;return;}
            for(unsigned d=0;d<TypeCount;++d)if(self.discovery[d].accept_suids(list)){
                self.io.ssc_event(d,suid,id,ticks,payload);
                if(!self.result.stopping)for(unsigned i=0;i<list.count;++i)self.add(AttributesRequest,d,list.ids[i]);
            }
        }else if(id==AttrEvent){
            Attributes a;if(!parse_attributes(payload,a)){++self.result.invalid;return;}
            for(unsigned d=0;d<TypeCount;++d)if(self.discovery[d].accept_attributes(suid,a)){
                self.io.ssc_event(d,suid,id,ticks,payload);
                if(!self.result.stopping)for(unsigned i=0;i<self.discovery[d].count;++i){
                    const auto &c=self.discovery[d].candidates[i];
                    if(equal(c.suid,suid)&&c.state==State::Ready)self.configure(d,suid,a);
                }
            }
        }else if(id==SampleEvent){
            for(unsigned i=0;i<self.stream_count;++i){
                auto &s=self.streams[i];if(!equal(s.suid,suid)||!s.sent||self.result.stopping)continue;
                Sample sample;if(!parse_sample(payload,sample)){++self.result.invalid;return;}
                if(s.samples&&ticks<=s.last)++s.nonmonotonic;
                if(!s.samples)s.first=ticks;
                ++s.samples;s.last=ticks;s.latest=sample;
                if(s.samples<=3)self.io.ssc_event(s.type,suid,id,ticks,payload);
            }
        }else if(id==PhysicalConfig){
            for(unsigned i=0;i<self.stream_count;++i)if(equal(self.streams[i].suid,suid))
                self.io.ssc_event(self.streams[i].type,suid,id,ticks,payload);
        }else if(id==ErrorEvent){
            ++self.result.errors;
            self.io.ssc_event(TypeCount,suid,id,ticks,payload);
        }
    }
public:
    constexpr explicit Census(IO &provider):io(provider){}
    void start(uint32_t remote_node,uint32_t remote_port,uint64_t now){
        if(result.started)return;
        node=remote_node;port=remote_port;started_ms=now;result.started=true;
        for(unsigned i=0;i<TypeCount;++i){discovery[i].start(type(i),now,3000);add(Lookup,i);}
    }
    void receive(uint32_t remote_node,uint32_t remote_port,uint32_t local_port,const uint8_t *bytes,uint32_t size){
        if(!result.started||result.done||remote_node!=node||remote_port!=port||local_port!=ClientPort){++result.foreign;return;}
        QmiPacket p;if(!decode_qmi(bytes,size,p)){++result.invalid;return;}
        if(p.kind==2){response(p);return;}
        if(!result.has_client||p.client!=result.client){++result.foreign;return;}
        if(!for_each_event(p,event,this))++result.invalid;
    }
    void tick(uint64_t now){
        if(!result.started||result.done)return;
        for(auto &d:discovery)d.expire(now);
        if(!result.stopping&&((now-started_ms>=8000)||(!stream_count&&resolved())))stop(now);
        send_pending();
        if(result.stopping){
            bool drained=true;
            for(unsigned i=0;i<request_count;++i)if(requests[i].kind==DisableRequest&&!requests[i].responded)drained=false;
            if(drained||now-stop_ms>=500)result.done=true;
        }
    }
};
} // namespace NabuSsc
