// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "NabuFastRpcProtocol.h"
#include "NabuFastRpcFiles.h"

namespace NabuFastRpc {
template<class IO> class Session {
public:
    enum : unsigned {CallBytes=1u<<20,PayloadBytes=256u<<10,PoolBytes=8u<<20,Client=0x4e4253};
    enum Phase {Idle,Attach,WaitListener,OpenListener,RegisterListener,Running,Failed,
                InitListener=10,Next,MapMemory,UnmapMemory};
    struct Result {
        bool started=false,attached=false,registered=false,ready=false,failed=false;
        unsigned calls=0,responses=0,reverse_calls=0,invalid=0,maps=0,unmaps=0;
        int32_t status=0;
        uint32_t last_handle=0,last_scalars=0;
    } result;
private:
    struct Call {
        uint8_t *memory=nullptr;uint64_t iova=0,context=0,since=0;
        Layout layout{};uint8_t message[MessageBytes]{};
        bool active=false,pending=false,received=false;
        int32_t result=0;Phase operation=Idle;
    } calls[3];
    struct Mapping {uint64_t address=0;uint32_t offset=0,bytes=0;bool active=false;} mappings[32]{};
    IO &io;Files<IO> files;
    Phase phase=Idle;
    uint8_t *memory=nullptr;uint64_t iova=0;
    uint32_t listener_handle=0,reverse_context=0,reply_bytes=0,pool_cursor=3*CallBytes+PayloadBytes;
    int32_t reverse_result=-1;
    bool listener_initialized=false,waiting_memory=false;
    unsigned mapping_index=0;
    uint8_t *reply=nullptr;
    void fail(int32_t error){phase=Failed;result.failed=true;result.status=error;}
    bool submit(unsigned slot,Phase operation,uint32_t handle,uint32_t sc,const Arg *args,uint64_t now){
        Call &c=calls[slot];if(c.active)return false;
        if(!build_args(c.memory,CallBytes,reinterpret_cast<uintptr_t>(c.memory),c.iova,sc,args,c.layout)){fail(-1001);return false;}
        c.context+=16;c.since=now;c.operation=operation;c.active=true;c.pending=c.received=false;
        encode_message(c.message,handle==KernelHandle?0u:uint32_t(Client),slot+1,c.context,SensorsPd,handle,sc,c.iova,c.layout.used);
        io.rpc_publish(c.memory,c.layout.page_bytes);result.last_handle=handle;result.last_scalars=sc;return true;
    }
    void memory_request(uint64_t now){
        const auto &request=files.pending_memory;
        uint8_t primitive[24]{},page[16]{};Arg args[3]{};
        if(request.method==2&&request.rflags==0x1000&&request.size&&request.size<=PoolBytes){
            unsigned slot=0;while(slot<32&&mappings[slot].active)++slot;
            uint32_t bytes=page_size(uint32_t(request.size));
            if(slot==32||bytes>PoolBytes-pool_cursor){reverse_result=0x10002;return;}
            mapping_index=slot;mappings[slot]={0,pool_cursor,bytes,false};
            memset(memory+pool_cursor,0,bytes);io.rpc_publish(memory+pool_cursor,bytes);
            uint32_t sc=mmap_args(primitive,page,args,Client,request.rflags,0,iova+pool_cursor,bytes);
            if(submit(2,MapMemory,KernelHandle,sc,args,now))waiting_memory=true;
        }else if(request.method==3){
            if(!request.size||request.size>PoolBytes){reverse_result=BadParameter;return;}
            unsigned slot=0;
            while(slot<32&&(!mappings[slot].active||mappings[slot].address!=request.vin||
                mappings[slot].bytes!=page_size(uint32_t(request.size))))++slot;
            if(slot==32){reverse_result=BadParameter;return;}
            mapping_index=slot;
            uint32_t sc=munmap_args(primitive,args,Client,request.vin,mappings[slot].bytes);
            if(submit(2,UnmapMemory,KernelHandle,sc,args,now))waiting_memory=true;
        }
    }
    void complete(unsigned slot,uint64_t now){
        Call &c=calls[slot];io.rpc_consume(c.memory,c.layout.page_bytes);
        c.active=c.pending=c.received=false;
        io.rpc_call_log(unsigned(c.operation),c.context,c.result);
        if(c.operation==MapMemory||c.operation==UnmapMemory){
            waiting_memory=false;reverse_result=c.result;reply_bytes=0;
            Mapping &mapping=mappings[mapping_index];
            if(c.result)return;
            if(c.operation==MapMemory){
                uint64_t remote=0;
                if(!mmap_output({c.memory+c.layout.offset[2],8},remote)){reverse_result=BadParameter;return;}
                mapping.address=remote;mapping.active=true;pool_cursor+=mapping.bytes;++result.maps;
                uint32_t length=16;MutableSpan out;
                if(!prepare_reverse_reply(reply,PayloadBytes,&length,1,&out,reply_bytes)){fail(-1006);return;}
                p64(out.data,0);p64(out.data+8,remote);
            }else{mapping.active=false;++result.unmaps;}
            return;
        }
        if(c.result){fail(c.result);return;}
        switch(c.operation){
        case Attach:
            result.attached=true;phase=WaitListener;
            submit(1,InitListener,ListenerHandle,ListenerInit2Sc,nullptr,now);break;
        case InitListener:listener_initialized=true;phase=OpenListener;break;
        case OpenListener:{
            const uint8_t *out=c.memory+c.layout.offset[2];listener_handle=u32(out);
            int32_t error=int32_t(u32(out+4));
            if(error||listener_handle==UINT32_MAX){fail(error?error:-1002);return;}
            phase=RegisterListener;break;
        }
        case RegisterListener:result.registered=true;result.ready=true;phase=Running;break;
        case Next:{
            ReverseHeader request;
            if(!listener_next_output({c.memory+c.layout.offset[2],16},request)||request.needed>PayloadBytes){fail(-1003);return;}
            reverse_context=request.context;
            reverse_result=files.invoke(request.handle,request.sc,{c.memory+c.layout.offset[3],request.needed},
                                        reply,PayloadBytes,reply_bytes);
            ++result.reverse_calls;
            if(files.pending_memory.valid)memory_request(now);
            io.rpc_reverse_log(request.handle,request.sc,request.needed,reply_bytes,waiting_memory?-1007:reverse_result);
            break;
        }
        default:fail(-1004);break;
        }
    }
    void drive(uint64_t now){
        uint8_t primitive[16]{};Arg args[4]{};
        if(listener_initialized&&!calls[1].active&&!waiting_memory){
            listener_next_input(primitive,reverse_context,reverse_result,reply_bytes,PayloadBytes);
            args[0]={primitive,16};args[1]={reply,reply_bytes};args[2]={nullptr,16};args[3]={nullptr,PayloadBytes};
            submit(1,Next,ListenerHandle,ListenerNext2Sc,args,now);
        }
        if(calls[0].active)return;
        if(phase==Attach){p32(primitive,Client);args[0]={primitive,4};submit(0,Attach,KernelHandle,AttachSc,args,now);}
        else if(phase==OpenListener){
            const char name[]="adsp_default_listener";
            p32(primitive,sizeof name);p32(primitive+4,256);
            args[0]={primitive,8};args[1]={reinterpret_cast<const uint8_t *>(name),sizeof name};
            args[2]={nullptr,8};args[3]={nullptr,256};submit(0,OpenListener,RemotectlHandle,OpenSc,args,now);
        }else if(phase==RegisterListener)submit(0,RegisterListener,listener_handle,0,nullptr,now);
    }
public:
    constexpr explicit Session(IO &provider):io(provider),files(provider){}
    void start(uint8_t *shared,uint64_t address,uint64_t){
        if(result.started)return;
        memory=shared;iova=address;reply=memory+3*CallBytes;phase=Attach;result.started=true;
        for(unsigned i=0;i<3;++i){calls[i].memory=memory+i*CallBytes;calls[i].iova=iova+i*CallBytes;calls[i].context=uint64_t(i+1)<<32;}
    }
    void receive(const uint8_t *data,uint32_t size){
        Response response;
        if(!decode_response(data,size,response)){++result.invalid;return;}
        for(auto &c:calls)if(c.pending&&!c.received&&matches_context(response,c.context)){
            c.result=response.result;c.received=true;++result.responses;return;
        }
        ++result.invalid;
    }
    void tick(uint64_t now){
        if(!result.started||result.failed)return;
        for(unsigned i=0;i<3;++i)if(calls[i].received)complete(i,now);
        if(result.failed)return;
        drive(now);
        for(auto &c:calls)if(c.active){
            if(!c.pending&&io.rpc_send(c.message,sizeof c.message)){c.pending=true;++result.calls;}
            if(now-c.since>=10000&&(c.operation!=Next||!c.pending)){fail(-1005);break;}
        }
    }
    unsigned stage()const{return unsigned(phase);}
};
} // namespace NabuFastRpc
