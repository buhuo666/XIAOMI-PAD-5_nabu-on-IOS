// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuSscProtocol.h"

namespace NabuSsc {
template<class IO> class Registry {
    IO &io;
    uint32_t node=0,port=0;
    uint64_t since=0;
    static void event(Suid from,uint32_t id,uint64_t,Span payload,void *context){
        auto &self=*static_cast<Registry *>(context);
        if(!equal(from,lookup_suid())||id!=SuidEvent)return;
        SuidList list;
        if(!parse_suids(payload,list)){++self.invalid;return;}
        if(strcmp(list.data_type,"registry"))return;
        ++self.events;self.candidates=list.count;self.ready=list.count!=0;
    }
public:
    enum : uint32_t {ClientPort=0x101};
    bool started=false,sent=false,ready=false,timeout=false,failed=false;
    unsigned responses=0,events=0,candidates=0,invalid=0;
    constexpr explicit Registry(IO &provider):io(provider){}
    void start(uint32_t remote_node,uint32_t remote_port,uint64_t now){node=remote_node;port=remote_port;since=now;started=true;}
    void tick(uint64_t now){
        if(!started||ready||timeout||failed)return;
        if(!sent){uint8_t bytes[512];size_t size=encode_lookup(bytes,sizeof bytes,1,"registry",true,true);
            sent=io.send_ssc(node,port,ClientPort,bytes,unsigned(size));}
        if(now-since>=15000)timeout=true;
    }
    void receive(uint32_t remote_node,uint32_t remote_port,const uint8_t *bytes,uint32_t size){
        if(!started||remote_node!=node||remote_port!=port){++invalid;return;}
        if(timeout||failed||ready)return;
        QmiPacket packet;if(!decode_qmi(bytes,size,packet)){++invalid;return;}
        if(packet.kind==2){++responses;failed=packet.result||packet.error||(packet.has_response&&packet.response);return;}
        if(!for_each_event(packet,event,this))++invalid;
    }
};
} // namespace NabuSsc
