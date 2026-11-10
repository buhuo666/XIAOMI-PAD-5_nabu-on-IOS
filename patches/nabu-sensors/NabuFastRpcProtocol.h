// SPDX-License-Identifier: BSD-2-Clause-Patent
// FastRPC wire codec for nabu's SLPI channel. Protocol facts are documented in
// analysis/nabu-slpi-fastrpc-abi-20261109.md. No Linux, allocator, or DSP calls.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace NabuFastRpc {
enum : unsigned {
    PageBytes=4096, BufferAlignment=128, MaxArgs=16, MessageBytes=40,
    ResponseBytes=16, KernelHandle=1, RemotectlHandle=0, ListenerHandle=3,
    RootPd=0, UserPd=1, SensorsPd=2,
    FdListBytes=16*8, CrcListBytes=64*4
};
constexpr uint32_t scalars(unsigned method,unsigned in,unsigned out){
    return ((method&31u)<<24)|((in&255u)<<16)|((out&255u)<<8);
}
constexpr unsigned inputs(uint32_t sc){return (sc>>16)&255u;}
constexpr unsigned outputs(uint32_t sc){return (sc>>8)&255u;}
constexpr unsigned method(uint32_t sc){return (sc>>24)&31u;}
enum : uint32_t {
    AttachSc=scalars(0,1,0), ReleaseSc=scalars(1,1,0),
    OpenSc=scalars(0,2,2), CloseSc=scalars(1,1,2),
    ListenerInit2Sc=scalars(3,0,0), ListenerNext2Sc=scalars(4,2,2),
    ListenerGetInBufs2Sc=scalars(5,1,2),
    MmapLegacySc=scalars(2,2,1), MmapSc=scalars(4,2,1),
    MunmapLegacySc=scalars(3,1,0), MunmapSc=scalars(5,1,0)
};
inline uint32_t u32(const uint8_t *p){
    return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24);
}
inline uint64_t u64(const uint8_t *p){return uint64_t(u32(p))|(uint64_t(u32(p+4))<<32);}
inline void p32(uint8_t *p,uint32_t n){for(unsigned i=0;i<4;++i){p[i]=uint8_t(n);n>>=8;}}
inline void p64(uint8_t *p,uint64_t n){p32(p,uint32_t(n));p32(p+4,uint32_t(n>>32));}
inline uint32_t align(uint32_t n,unsigned boundary){return (n+boundary-1)&~uint32_t(boundary-1);}
inline uint32_t page_size(uint32_t n){return n?align(n,PageBytes):PageBytes;}

struct Arg {const uint8_t *input;uint32_t bytes;};
struct Span {const uint8_t *data;uint32_t size;};
struct MutableSpan {uint8_t *data;uint32_t size;};
struct Layout {
    uint32_t count=0,used=0,page_bytes=PageBytes;
    uint32_t offset[MaxArgs]{};
};

// Caller supplies one 4 KiB-aligned shared mapping. iova is the address the
// SLPI SMMU resolves (including its high domain bits), not an APPS physical PA.
// Each argument is independent; DMA handles and aliased arguments are unused.
inline bool build_args(uint8_t *memory,uint32_t capacity,uint64_t host_va,
                       uint64_t iova,uint32_t sc,const Arg *args,Layout &layout){
    layout.count=layout.used=0;layout.page_bytes=PageBytes;
    unsigned count=inputs(sc)+outputs(sc);
    if((sc&255u)||count>MaxArgs||((host_va|iova)&(PageBytes-1)))return false;
    if(!count)return true;
    uint32_t metadata=count*(16+8+16)+FdListBytes+CrcListBytes;
    if(metadata>capacity)return false;
    uint32_t used=metadata;
    for(unsigned i=0;i<count;++i){
        layout.offset[i]=0;
        if(!args[i].bytes)continue;
        if(used>UINT32_MAX-(BufferAlignment-1))return false;
        used=align(used,BufferAlignment);
        if(used>capacity||args[i].bytes>capacity-used)return false;
        layout.offset[i]=used;used+=args[i].bytes;
    }
    if(used>UINT32_MAX-(PageBytes-1)||page_size(used)>capacity)return false;
    memset(memory,0,page_size(used));
    uint32_t list=count*16,pages=list+count*8;
    for(unsigned i=0;i<count;++i){
        uint32_t offset=layout.offset[i],length=args[i].bytes;
        p64(memory+i*16,length?host_va+offset:0);
        p64(memory+i*16+8,length);
        p32(memory+list+i*8,length?1:0);
        p32(memory+list+i*8+4,i);
        if(!length)continue;
        p64(memory+pages+i*16,iova+(offset&~uint32_t(PageBytes-1)));
        p64(memory+pages+i*16+8,page_size((offset&(PageBytes-1))+length));
        if(i<inputs(sc)&&args[i].input)memcpy(memory+offset,args[i].input,length);
    }
    layout.count=count;layout.used=used;layout.page_bytes=page_size(used);
    return true;
}

inline void encode_message(uint8_t *out,uint32_t pid,uint32_t tid,uint64_t context,
                           unsigned pd,uint32_t handle,uint32_t sc,
                           uint64_t iova,uint32_t used){
    p32(out,pid);p32(out+4,tid);p64(out+8,(context&~UINT64_C(3))|(pd&3u));
    p32(out+16,handle);p32(out+20,sc);p64(out+24,used?iova:0);
    p64(out+32,page_size(used));
}
struct Response {uint64_t context=0;int32_t result=0;};
inline bool decode_response(const uint8_t *data,uint32_t size,Response &out){
    if(size<ResponseBytes)return false;
    out.context=u64(data);out.result=int32_t(u32(data+8));return true;
}
inline bool matches_context(const Response &response,uint64_t context){
    return (response.context&~UINT64_C(3))==(context&~UINT64_C(3));
}

// nabu's driver selects the compatibility wire protocol whenever its compat
// ioctl exists, including 64-bit callers. It transmits page-list BYTES (16),
// not the legacy page COUNT (1). This is independent of uintptr_t being 64-bit.
inline uint32_t mmap_args(uint8_t *primitive,uint8_t *page,Arg *args,uint32_t pid,
                          uint32_t flags,uint64_t desired_va,uint64_t iova,
                          uint64_t bytes,bool compat=true){
    memset(primitive,0,24);p32(primitive,pid);p32(primitive+4,flags);
    p64(primitive+8,desired_va);p32(primitive+16,compat?16:1);
    p64(page,iova);p64(page+8,bytes);
    args[0]={primitive,24};args[1]={page,16};args[2]={nullptr,8};
    return compat?MmapSc:MmapLegacySc;
}
inline uint32_t munmap_args(uint8_t *primitive,Arg *args,uint32_t pid,
                            uint64_t dsp_va,uint64_t bytes,bool compat=true){
    memset(primitive,0,24);p32(primitive,pid);p64(primitive+8,dsp_va);p64(primitive+16,bytes);
    args[0]={primitive,24};return compat?MunmapSc:MunmapLegacySc;
}
inline bool mmap_output(Span output,uint64_t &dsp_va){
    if(output.size!=8)return false;
    dsp_va=u64(output.data);return true;
}

// next2 primitive input: prior reverse context, result, packed reply bytes,
// receive capacity. Primitive output: next context, handle, scalars, needed.
inline void listener_next_input(uint8_t *out,uint32_t context,int32_t result,
                                uint32_t reply_bytes,uint32_t receive_capacity){
    p32(out,context);p32(out+4,uint32_t(result));p32(out+8,reply_bytes);p32(out+12,receive_capacity);
}
struct ReverseHeader {uint32_t context=0,handle=0,sc=0,needed=0;};
inline bool listener_next_output(Span data,ReverseHeader &out){
    if(data.size!=16)return false;
    out.context=u32(data.data);out.handle=u32(data.data+4);
    out.sc=u32(data.data+8);out.needed=u32(data.data+12);return true;
}
inline void listener_get_input(uint8_t *out,uint32_t context,uint32_t offset,uint32_t capacity){
    p32(out,context);p32(out+4,offset);p32(out+8,capacity);
}

struct ReverseCall {
    unsigned input_count=0,output_count=0;
    Span input[MaxArgs]{};
    uint32_t output_size[MaxArgs]{};
};
// Input records have len/data; output records carry only their expected len.
// Zero-length records consume only their four-byte size, without alignment.
inline bool decode_reverse(uint32_t sc,Span data,ReverseCall &out){
    out.input_count=out.output_count=0;
    const unsigned in=inputs(sc),output=outputs(sc);
    if((sc&255u)||in>MaxArgs||output>MaxArgs)return false;
    uint32_t at=0;
    for(unsigned i=0;i<in;++i){
        if(data.size-at<4)return false;
        uint32_t size=u32(data.data+at);at+=4;
        if(size){
            if(at>UINT32_MAX-7)return false;
            at=align(at,8);
            if(at>data.size||size>data.size-at)return false;
        }
        out.input[i]={size?data.data+at:nullptr,size};at+=size;
    }
    for(unsigned i=0;i<output;++i){
        if(data.size-at<4)return false;
        out.output_size[i]=u32(data.data+at);at+=4;
    }
    if(at!=data.size)return false;
    out.input_count=in;out.output_count=output;return true;
}

// Allocate the packed reply directly in caller storage. The returned spans
// point to payloads the reverse file service fills before the next invocation.
inline bool prepare_reverse_reply(uint8_t *data,uint32_t capacity,
                                  const uint32_t *lengths,unsigned count,
                                  MutableSpan *buffers,uint32_t &used){
    used=0;if(count>MaxArgs)return false;
    uint32_t at=0;
    for(unsigned i=0;i<count;++i){
        if(capacity-at<4)return false;
        p32(data+at,lengths[i]);at+=4;
        if(lengths[i]){
            if(at>UINT32_MAX-7)return false;
            uint32_t begin=align(at,8);
            if(begin>capacity||lengths[i]>capacity-begin)return false;
            memset(data+at,0,begin-at+lengths[i]);at=begin;
        }
        buffers[i]={lengths[i]?data+at:nullptr,lengths[i]};at+=lengths[i];
    }
    used=at;return true;
}
} // namespace NabuFastRpc
