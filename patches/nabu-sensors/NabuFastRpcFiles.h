// SPDX-License-Identifier: BSD-2-Clause-Patent
// Read-only apps_std service over the actual FastRPC listener framing.
#pragma once
#include "NabuFastRpcProtocol.h"

namespace NabuFastRpc {
// apps_std intentionally mixes errno from file operations (ENOENT=2,
// EBADF=9, EINVAL=22, EMFILE=24) with HLOS AEE protocol errors (offset=0).
// Do not replace an absent file's ENOENT with AEE_ENOSUCH (39).
enum FileResult : int32_t {
    Success=0,Failed=1,NoSuchFile=2,BadFile=9,BadParameter=14,
    Unsupported=20,InvalidArgument=22,TooManyFiles=24,InvalidHandle=44
};
struct MemoryRequest {
    bool valid=false;
    uint32_t method=0,sc=0,heap_id=0,ion_flags=0,rflags=0;
    int32_t fd=-1;
    uint64_t offset=0,vin=0,size=0;
};
struct FileCall {
    uint32_t handle=0,sc=0,method=0;
    int32_t result=0;
    char path[384]{};
};

// IO owns an immutable archive and implements:
// bool rpc_file_open(path, const uint8_t *&data, uint32_t &size)
// const char *rpc_file_env(name)  // nullptr for an undefined variable
// int rpc_file_list(path,index,name,name_capacity,size) // 1 entry,0 EOF,-1 absent
// void rpc_file_log(handle,method,path,result)
template<class IO> class Files {
    enum : unsigned {FileCount=24,DirCount=8,FileBase=100,DirBase=0x10000,PathBytes=384};
    struct File {const uint8_t *data=nullptr;uint32_t size=0,position=0;bool open=false,eof=false;char path[PathBytes]{};};
    struct Directory {uint32_t index=0;bool open=false;char path[PathBytes]{};};
    IO &io;
    File files[FileCount]{};
    Directory directories[DirCount]{};
    unsigned module_refs[3]{};
    static bool shape(const ReverseCall &c,unsigned in,unsigned out,unsigned in0=0,unsigned out0=0){
        return c.input_count==in&&c.output_count==out&&
            (!in0||(in&&c.input[0].size>=in0))&&(!out0||(out&&c.output_size[0]>=out0));
    }
    static bool string(Span span,const char *&text){
        if(!span.size||span.size>PathBytes||span.data[span.size-1])return false;
        text=reinterpret_cast<const char *>(span.data);return true;
    }
    static bool string_arg(const ReverseCall &c,unsigned index,unsigned length_offset,const char *&s){
        if(index>=c.input_count||c.input[0].size<length_offset+4)return false;
        uint32_t n=u32(c.input[0].data+length_offset);
        if(n>c.input[index].size)return false;
        return string({c.input[index].data,n},s);
    }
    void path(const char *s){
        size_t n=strlen(s);if(n>=PathBytes)n=PathBytes-1;
        memcpy(last.path,s,n);last.path[n]=0;
    }
    File *file(uint32_t fd){
        if(fd<FileBase||fd-FileBase>=FileCount||!files[fd-FileBase].open)return nullptr;
        File &f=files[fd-FileBase];path(f.path);return &f;
    }
    Directory *directory(uint64_t fd){
        if(fd<DirBase||fd-DirBase>=DirCount||!directories[fd-DirBase].open)return nullptr;
        Directory &d=directories[fd-DirBase];path(d.path);return &d;
    }
    int32_t open(const char *name,const char *mode,uint8_t *output){
        path(name);
        if(strcmp(mode,"r")&&strcmp(mode,"rb"))return Unsupported;
        const uint8_t *data;uint32_t bytes;
        if(!io.rpc_file_open(name,data,bytes))return NoSuchFile;
        for(unsigned i=0;i<FileCount;++i)if(!files[i].open){
            File &f=files[i];f.data=data;f.size=bytes;f.position=0;f.open=true;f.eof=false;
            memcpy(f.path,last.path,strlen(last.path)+1);p32(output,FileBase+i);return Success;
        }
        return TooManyFiles;
    }
    int32_t open_env(const char *env,const char *delimiter,const char *name,const char *mode,uint8_t *output){
        path(name);
        if(strcmp(mode,"r")&&strcmp(mode,"rb"))return Unsupported;
        if(name[0]=='/')return open(name,mode,output);
        const char *list=io.rpc_file_env(env);
        if(!list)return NoSuchFile;
        size_t delimiter_bytes=strlen(delimiter),name_bytes=strlen(name);
        if(!delimiter_bytes)return BadParameter;
        char candidate[PathBytes];
        while(*list){
            const char *end=nullptr;
            for(const char *cursor=list;*cursor;++cursor){
                size_t i=0;while(i<delimiter_bytes&&cursor[i]&&cursor[i]==delimiter[i])++i;
                if(i==delimiter_bytes){end=cursor;break;}
            }
            size_t prefix=end?size_t(end-list):strlen(list);
            if(prefix+name_bytes+2>sizeof candidate)return BadParameter;
            memcpy(candidate,list,prefix);
            unsigned at=unsigned(prefix);
            if(at&&candidate[at-1]!='/')candidate[at++]='/';
            memcpy(candidate+at,name,name_bytes+1);
            int32_t result=open(candidate,mode,output);
            if(result!=NoSuchFile)return result;
            if(!end)break;
            list=end+delimiter_bytes;
        }
        path(name);return NoSuchFile;
    }
    int32_t module(const ReverseCall &c,MutableSpan *out,unsigned method){
        if(method==0){
            const char *name;
            if(!shape(c,2,2,8,8)||!string_arg(c,1,0,name)||u32(c.input[0].data+4)>c.output_size[1])return BadParameter;
            path(name);unsigned h=0;
            if(!strcmp(name,"apps_std"))h=1;
            else if(!strcmp(name,"apps_mem"))h=2;
            else return Unsupported;
            ++module_refs[h];p32(out[0].data,h);p32(out[0].data+4,0);return Success;
        }
        if(method==1){
            if(!shape(c,1,2,8,4)||u32(c.input[0].data+4)>c.output_size[1])return BadParameter;
            unsigned h=u32(c.input[0].data);
            if(h<1||h>2||!module_refs[h])return InvalidHandle;
            --module_refs[h];p32(out[0].data,0);return Success;
        }
        return Unsupported;
    }
    int32_t memory(const ReverseCall &c,unsigned method){
        pending_memory=MemoryRequest{};pending_memory.method=method;pending_memory.sc=last.sc;
        if(c.input_count!=1)return BadParameter;
        const auto &p=c.input[0];
        if(method==2){
            if(!shape(c,1,1,32,16))return BadParameter;
            pending_memory.heap_id=u32(p.data);pending_memory.ion_flags=u32(p.data+4);
            pending_memory.rflags=u32(p.data+8);pending_memory.vin=u64(p.data+16);
            pending_memory.size=u64(p.data+24);pending_memory.fd=-1;pending_memory.offset=0;
        }else if(method==3){
            if(!shape(c,1,0,16))return BadParameter;
            pending_memory.vin=u64(p.data);pending_memory.size=u64(p.data+8);
            pending_memory.fd=-1;pending_memory.offset=0;
        }else if(method==4){
            if(!shape(c,1,1,8,16))return BadParameter;
            pending_memory.fd=int32_t(u32(p.data));pending_memory.size=u32(p.data+4);
        }else if(method==6){
            if(!shape(c,1,0,12))return BadParameter;
            pending_memory.fd=int32_t(u32(p.data));pending_memory.offset=u32(p.data+4);
            pending_memory.size=u32(p.data+8);
        }else return Unsupported;
        pending_memory.valid=true;return Unsupported;
    }
    int32_t standard(const ReverseCall &c,MutableSpan *out,unsigned method){
        const char *name=nullptr,*mode=nullptr;
        if(method==0){
            if(!shape(c,3,1,8,4)||!string_arg(c,1,0,name)||!string_arg(c,2,4,mode))return BadParameter;
            return open(name,mode,out[0].data);
        }
        if(method==19){
            const char *env,*delimiter;
            if(!shape(c,5,1,16,4)||!string_arg(c,1,0,env)||!string_arg(c,2,4,delimiter)||
               !string_arg(c,3,8,name)||!string_arg(c,4,12,mode))return BadParameter;
            return open_env(env,delimiter,name,mode,out[0].data);
        }
        if(method==16){
            if(!shape(c,2,2,8,4)||!string_arg(c,1,0,name)||u32(c.input[0].data+4)>c.output_size[1])return BadParameter;
            path(name);const char *value=io.rpc_file_env(name);if(!value)return -1; // ROM apps_std_getenv
            uint32_t size=uint32_t(strlen(value))+1,capacity=u32(c.input[0].data+4);
            p32(out[0].data,size);
            if(capacity){uint32_t copied=size<capacity?size:capacity;memcpy(out[1].data,value,copied);out[1].data[copied-1]=0;}
            return Success;
        }
        if(method==26){
            if(!shape(c,2,1,4,8)||!string_arg(c,1,0,name))return BadParameter;
            path(name);char entry[255];uint32_t size;
            if(io.rpc_file_list(name,0,entry,sizeof entry,size)<0)return NoSuchFile;
            for(unsigned i=0;i<DirCount;++i)if(!directories[i].open){
                Directory &d=directories[i];d.open=true;d.index=0;memcpy(d.path,last.path,strlen(last.path)+1);
                p64(out[0].data,DirBase+i);return Success;
            }
            return TooManyFiles;
        }
        if(method==27||method==28){
            if(!shape(c,1,method==27?0:1,8,method==27?0:264))return BadParameter;
            Directory *d=directory(u64(c.input[0].data));if(!d)return BadFile;
            if(method==27){d->open=false;return Success;}
            uint32_t size;
            int found=io.rpc_file_list(d->path,d->index,reinterpret_cast<char *>(out[0].data+4),255,size);
            if(found<0)return NoSuchFile;
            p32(out[0].data,0);p32(out[0].data+260,found==0);
            if(found)++d->index;return Success;
        }
        if(method==31){
            if(!shape(c,2,1,8,96)||!string_arg(c,1,4,name))return BadParameter;
            path(name);const uint8_t *data;uint32_t size;bool regular=io.rpc_file_open(name,data,size);
            if(!regular){char entry[255];if(io.rpc_file_list(name,0,entry,sizeof entry,size)<0)return NoSuchFile;size=0;}
            // Metadata describes the projected read-only archive, not Android's
            // inode numbers or times. Only type, permissions, link count and size.
            p32(out[0].data+24,regular?0100444u:0040555u);p32(out[0].data+28,1);
            p64(out[0].data+40,size);return Success;
        }
        if(method==22){
            if(!shape(c,2,1,4,1)||!string_arg(c,1,0,name))return BadParameter;
            path(name);const uint8_t *data;uint32_t size;
            out[0].data[0]=io.rpc_file_open(name,data,size);return Success;
        }
        if(method==15){
            if(!shape(c,2,0,4)||!string_arg(c,1,0,name))return BadParameter;
            path(name);return Success; // rpc_file_log emits the requested string.
        }
        if(method==3||method==4||method==8||method==9||method==10||method==11||method==12||method==13||method==14||method==2){
            unsigned in0=(method==4?8:method==9?12:4);
            unsigned outcount=method==4?2:(method==8||method==10||method==12||method==13)?1:0;
            unsigned out0=method==4?8:method==10?8:outcount?4:0;
            if(!shape(c,1,outcount,in0,out0))return BadParameter;
            File *f=file(u32(c.input[0].data));if(!f)return BadFile;
            switch(method){
            case 3:f->open=false;return Success;
            case 4:{
                uint32_t wanted=u32(c.input[0].data+4);
                if(wanted>out[1].size)return BadParameter;
                uint32_t available=f->position<f->size?f->size-f->position:0;
                uint32_t take=wanted<available?wanted:available;
                if(take)memcpy(out[1].data,f->data+f->position,take);
                f->position+=take;f->eof=take<wanted;
                p32(out[0].data,take);p32(out[0].data+4,f->eof);return Success;
            }
            case 8:p32(out[0].data,f->position);return Success;
            case 9:{
                uint32_t whence=u32(c.input[0].data+8);if(whence>2)return InvalidArgument;
                int64_t base=whence==0?0:whence==1?f->position:f->size;
                int64_t offset=int32_t(u32(c.input[0].data+4)),position=base+offset;
                if(position<0||position>UINT32_MAX)return InvalidArgument;
                f->position=uint32_t(position);f->eof=false;return Success;
            }
            case 10:p64(out[0].data,f->size);return Success;
            case 11:f->position=0;f->eof=false;return Success;
            case 12:p32(out[0].data,f->eof);return Success;
            case 13:p32(out[0].data,0);return Success; // immutable reads do not incur host IO errors
            case 14:f->eof=false;return Success;
            case 2:return Success; // no buffered writes exist for read-only files
            }
        }
        // Registry mutation and DMA/FD operations are deliberately unimplemented.
        if(c.input_count&&c.input[0].size>=4)(void)file(u32(c.input[0].data));
        return Unsupported;
    }
public:
    FileCall last{};
    MemoryRequest pending_memory{};
    unsigned calls=0,failures=0,unknown=0;
    constexpr explicit Files(IO &provider):io(provider){}
    int32_t invoke(uint32_t handle,uint32_t sc,Span request,uint8_t *reply,
                   uint32_t capacity,uint32_t &used){
        used=0;last.handle=handle;last.sc=sc;last.method=method(sc);last.path[0]=0;
        pending_memory.valid=false;
        ReverseCall call;MutableSpan output[MaxArgs]{};int32_t result;
        if(!decode_reverse(sc,request,call))result=BadParameter;
        else if(last.method==31&&(!call.input_count||call.input[0].size<4))result=BadParameter;
        else{
            if(last.method==31)last.method=u32(call.input[0].data);
            if(handle>2||(handle&&!module_refs[handle]))result=InvalidHandle;
            else if(handle==2)result=memory(call,last.method);
            else if(!prepare_reverse_reply(reply,capacity,call.output_size,call.output_count,output,used))result=BadParameter;
            else result=handle==0?module(call,output,last.method):standard(call,output,last.method);
        }
        if(result)used=0;
        last.result=result;++calls;if(result)++failures;if(result==Unsupported)++unknown;
        io.rpc_file_log(last.handle,last.method,last.path,result);
        return result;
    }
};
} // namespace NabuFastRpc
