#!/usr/bin/env python3
"""End-to-end host checks of SLPI FastRPC session and SSC registry readiness."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
from check_darwinboot_8796 import host_command,host_path
from check_nabu_fastrpc import ORACLE

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <initializer_list>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>
#include "NabuFastRpcSession.h"
#include "NabuFastRpcArchive.h"
#include "NabuSscRegistry.h"
namespace N=NabuFastRpc;
namespace S=NabuSsc;
using Bytes=std::vector<uint8_t>;
static unsigned checks=0,failures=0;
static void check(bool pass,const char *what){++checks;if(!pass){++failures;printf("FAIL: %s\n",what);}}
static void require(bool pass,const char *what){if(!pass)throw std::runtime_error(what);}
static Bytes read(const char *path){std::ifstream f(path,std::ios::binary);require(f.good(),"fixture file missing");return Bytes(std::istreambuf_iterator<char>(f),{});}
static Bytes words(std::initializer_list<uint32_t> values){Bytes b(values.size()*4);unsigned i=0;for(auto n:values){N::p32(b.data()+i,n);i+=4;}return b;}
static Bytes string(const char *s){return Bytes(s,s+strlen(s)+1);}
extern "C" unsigned oracle_request(unsigned char *,unsigned,const unsigned char **,
                                    const unsigned *,unsigned,const unsigned *,unsigned);
static Bytes packed(const std::vector<Bytes> &in,const std::vector<unsigned> &out){
    const uint8_t *data[16]{};unsigned size[16]{};
    for(unsigned i=0;i<in.size();++i){data[i]=in[i].data();size[i]=in[i].size();}
    Bytes result(4096);unsigned used=oracle_request(result.data(),result.size(),data,size,in.size(),out.data(),out.size());
    result.resize(used);return result;
}
static std::vector<Bytes> unpack(N::Span packed,unsigned count){
    std::vector<Bytes> result;unsigned at=0;
    for(unsigned i=0;i<count;++i){
        require(packed.size-at>=4,"reply length missing");unsigned n=N::u32(packed.data+at);at+=4;
        if(n)at=(at+7)&~7u;
        require(at<=packed.size&&n<=packed.size-at,"reply data missing");
        result.emplace_back(packed.data+at,packed.data+at+n);at+=n;
    }
    require(at==packed.size,"unexpected reply tail");return result;
}
struct Frame {
    uint32_t pid,tid,handle,sc;uint64_t context,iova,bytes;
};
struct IO {
    uint8_t *shared=nullptr;uint64_t base=0x180000000ULL;
    N::Archive archive;std::vector<Frame> frames;
    unsigned publications=0,consumptions=0,file_logs=0;bool blocked=false;
    explicit IO(const Bytes &files){
        shared=static_cast<uint8_t *>(aligned_alloc(4096,8u<<20));require(shared,"shared allocation");
        memset(shared,0,8u<<20);require(archive.load(files.data(),files.size()),"archive header");
    }
    ~IO(){free(shared);}
    void rpc_publish(uint8_t *p,unsigned n){require(p>=shared&&size_t(p-shared)+n<=(8u<<20),"publish range");++publications;}
    void rpc_consume(uint8_t *p,unsigned n){require(p>=shared&&size_t(p-shared)+n<=(8u<<20),"consume range");++consumptions;}
    bool rpc_send(const uint8_t *p,unsigned n){
        require(n==40,"wire message size");if(blocked)return false;
        frames.push_back({N::u32(p),N::u32(p+4),N::u32(p+16),N::u32(p+20),N::u64(p+8),N::u64(p+24),N::u64(p+32)});return true;
    }
    bool rpc_file_open(const char *p,const uint8_t *&data,uint32_t &size){return archive.open(p,data,size);}
    const char *rpc_file_env(const char *s){return !strcmp(s,"ADSP_LIBRARY_PATH")?"/dsp;/dsp/sdsp":nullptr;}
    int rpc_file_list(const char *p,uint32_t index,char *name,uint32_t cap,uint32_t &size){return archive.list(p,index,name,cap,size);}
    void rpc_file_log(uint32_t,uint32_t,const char *,int32_t){++file_logs;}
    void rpc_call_log(unsigned,uint64_t,int32_t){}
    void rpc_reverse_log(uint32_t,uint32_t,uint32_t,uint32_t,int32_t){}
    Frame last(uint32_t handle,uint32_t sc)const{
        for(auto i=frames.rbegin();i!=frames.rend();++i)if(i->handle==handle&&i->sc==sc)return *i;
        throw std::runtime_error("expected frame missing");
    }
    unsigned count(uint32_t handle,uint32_t sc)const{
        return std::count_if(frames.begin(),frames.end(),[&](const Frame &f){return f.handle==handle&&f.sc==sc;});
    }
    N::Span arg(const Frame &f,unsigned index)const{
        require(index<N::inputs(f.sc)+N::outputs(f.sc),"argument index");
        require(f.iova>=base&&f.iova-base<(8u<<20),"message IOVA");
        auto *meta=shared+(f.iova-base)+index*16;uint64_t pointer=N::u64(meta),length=N::u64(meta+8);
        if(!length)return {nullptr,0};
        auto *p=reinterpret_cast<const uint8_t *>(uintptr_t(pointer));
        require(p>=shared&&size_t(p-shared)+length<=(8u<<20),"argument range");
        return {p,uint32_t(length)};
    }
    void output(const Frame &f,unsigned index,const Bytes &data){
        auto a=arg(f,N::inputs(f.sc)+index);require(data.size()<=a.size,"output size");
        if(!data.empty())memcpy(const_cast<uint8_t *>(a.data),data.data(),data.size());
    }
};
struct Trial {
    IO io;N::Session<IO> session;uint64_t now=0;
    explicit Trial(const Bytes &archive):io(archive),session(io){session.start(io.shared,io.base,0);session.tick(0);}
    void tick(){session.tick(++now);}
    void response(const Frame &f,int32_t result=0){
        uint8_t data[16]{};N::p64(data,f.context);N::p32(data+8,uint32_t(result));session.receive(data,16);
    }
    void finish(const Frame &f,int32_t result=0){response(f,result);tick();require(!session.result.failed,"unexpected session failure");}
    void to_open(){
        auto attach=io.last(1,N::AttachSc);check(attach.pid==0&&(attach.context&3)==2,"attach pid=0 and sensors PD");
        check(N::u32(io.arg(attach,0).data)==N::Session<IO>::Client,"attach client identity");
        finish(attach);auto init=io.last(3,N::ListenerInit2Sc);
        check(init.pid==N::Session<IO>::Client,"listener init uses client pid");
        check(io.count(0,N::OpenSc)==0,"registration waits for init2 completion");
        finish(init);
        check(io.count(0,N::OpenSc)==1&&io.count(3,N::ListenerNext2Sc)==1,"open and next2 independently pending");
    }
    void to_ready(){
        to_open();auto open=io.last(0,N::OpenSc);
        io.output(open,0,words({0xabc,0}));finish(open);
        check(!session.result.ready,"open alone does not set ready");
        finish(io.last(0xabc,0));check(session.result.ready&&session.result.registered,"register completion sets ready");
        check(io.count(0,N::CloseSc)==0,"default listener handle retained");
    }
    Frame reverse(uint32_t context,uint32_t handle,uint32_t method,const std::vector<Bytes> &in,
                  const std::vector<unsigned> &out){
        auto next=io.last(3,N::ListenerNext2Sc);auto request=packed(in,out);
        io.output(next,0,words({context,handle,N::scalars(method,in.size(),out.size()),unsigned(request.size())}));
        io.output(next,1,request);finish(next);return io.last(3,N::ListenerNext2Sc);
    }
    void module(const char *name,uint32_t context){
        auto n=string(name);auto next=reverse(context,0,0,{words({unsigned(n.size()),0}),n},{8,0});
        auto p=io.arg(next,0);require(N::u32(p.data+4)==0,"module registration failed");
    }
};
static void session_checks(const Bytes &archive){
    Trial t(archive);t.to_ready();
    unsigned sent=t.io.frames.size();t.now=60000;t.session.tick(t.now);
    check(!t.session.result.failed&&t.io.frames.size()==sent,"idle outstanding next2 does not time out");
    auto old=t.io.last(0xabc,0);unsigned invalid=t.session.result.invalid;t.response(old);
    check(t.session.result.invalid==invalid+1,"completed control context cannot satisfy listener");
    t.module("apps_std",10);
    auto path=string("/dsp/sdsp/libprobe.so"),mode=string("rb");
    auto next=t.reverse(11,1,0,{words({unsigned(path.size()),unsigned(mode.size())}),path,mode},{4});
    auto returned=unpack(t.io.arg(next,1),1);uint32_t fd=N::u32(returned[0].data());
    next=t.reverse(12,1,4,{words({fd,12})},{8,12});returned=unpack(t.io.arg(next,1),2);
    check(N::u32(returned[0].data())==12&&returned[1]==Bytes({'a','r','c','h','i','v','e',' ','p','r','o','b'}),"reverse reads original archive bytes");
    t.module("apps_mem",13);
    Bytes mem(32);N::p32(mem.data(),0xffffffff);N::p32(mem.data()+8,0x1000);N::p64(mem.data()+24,8192);
    unsigned next_before=t.io.count(3,N::ListenerNext2Sc);
    t.reverse(14,2,2,{mem},{16});
    check(t.io.count(3,N::ListenerNext2Sc)==next_before,"next2 reply waits for real DSP mmap");
    auto map=t.io.last(1,N::MmapSc);
    check(map.pid==0&&N::u32(t.io.arg(map,0).data)==N::Session<IO>::Client,"mmap uses kernel pid and client primitive");
    uint64_t backing=N::u64(t.io.arg(map,1).data);
    check(backing==t.io.base+3*N::Session<IO>::CallBytes+N::Session<IO>::PayloadBytes,"memory allocation excludes three call regions and reply workspace");
    Bytes dsp(8);N::p64(dsp.data(),0x91024000);t.io.output(map,0,dsp);t.finish(map);
    next=t.io.last(3,N::ListenerNext2Sc);returned=unpack(t.io.arg(next,1),1);
    check(N::u64(returned[0].data())==0&&N::u64(returned[0].data()+8)==0x91024000&&backing!=0x91024000,"map reply carries actual DSP VA, not IOVA");
    check(t.session.result.maps==1,"successful DSP map counted once");
    Bytes unmap(16);N::p64(unmap.data(),0x91024000);N::p64(unmap.data()+8,8192);
    t.reverse(15,2,3,{unmap},{});auto munmap=t.io.last(1,N::MunmapSc);
    check(munmap.pid==0&&N::u64(t.io.arg(munmap,0).data+8)==0x91024000,"unmap targets DSP VA");
    t.finish(munmap);check(t.session.result.unmaps==1,"unmap completion observed");
    puts("PASS CASE: initialized session, persistent listener, real file and memory responses");
}
static void concurrency_checks(const Bytes &archive){
    Trial t(archive);t.to_open();auto open=t.io.last(0,N::OpenSc);
    t.module("apps_mem",20);
    Bytes mem(32);N::p32(mem.data()+8,0x1000);N::p64(mem.data()+24,4096);
    t.reverse(21,2,2,{mem},{16});auto map=t.io.last(1,N::MmapSc);auto listener=t.io.last(3,N::ListenerNext2Sc);
    check(open.context!=map.context&&open.context!=listener.context&&map.context!=listener.context,"control/listener/mmap contexts are distinct");
    check(open.iova!=map.iova&&open.iova!=listener.iova&&map.iova!=listener.iova,"three contexts own separate parameter regions");
    unsigned before=t.session.result.invalid;uint8_t wrong[16]{};N::p64(wrong,0x9900000012ULL);t.session.receive(wrong,16);
    check(t.session.result.invalid==before+1,"unknown context rejected while open and mmap pending");
    t.io.output(open,0,words({0xabd,0}));Bytes remote(8);N::p64(remote.data(),0x92200000);t.io.output(map,0,remote);
    // Complete independent calls together, opposite to their send order.
    t.response(map);t.response(open);t.tick();
    auto next=t.io.last(3,N::ListenerNext2Sc);auto out=unpack(t.io.arg(next,1),1);
    check(N::u64(out[0].data()+8)==0x92200000,"out-of-order mmap response preserved across control completion");
    auto registration=t.io.last(0xabd,0);t.finish(registration);
    check(t.session.result.ready&&!t.session.result.failed,"register succeeds while new next2 stays pending");
    puts("PASS CASE: three-call concurrency and out-of-order responses");
}
static void unsupported_map_flags(const Bytes &archive){
    Trial t(archive);t.to_ready();t.module("apps_mem",30);
    Bytes mem(32);N::p32(mem.data()+8,0x1001);N::p64(mem.data()+24,4096);
    unsigned maps=t.io.count(1,N::MmapSc);auto next=t.reverse(31,2,2,{mem},{16});
    bool rejected=t.io.count(1,N::MmapSc)==maps;
    if(rejected)rejected=N::u32(t.io.arg(next,0).data+4)==uint32_t(N::Unsupported);
    check(rejected,"unsupported ADD_PAGES flag combination is not mapped");
}
static void unmap_size_width(const Bytes &archive){
    Trial t(archive);t.to_ready();t.module("apps_mem",40);
    Bytes mem(32);N::p32(mem.data()+8,0x1000);N::p64(mem.data()+24,4096);
    t.reverse(41,2,2,{mem},{16});auto map=t.io.last(1,N::MmapSc);Bytes remote(8);N::p64(remote.data(),0x92500000);
    t.io.output(map,0,remote);t.finish(map);
    Bytes unmap(16);N::p64(unmap.data(),0x92500000);N::p64(unmap.data()+8,UINT64_C(0x100001000));
    unsigned unmaps=t.io.count(1,N::MunmapSc);t.reverse(42,2,3,{unmap},{});
    check(t.io.count(1,N::MunmapSc)==unmaps,"unmap matches full 64-bit requested size without truncation");
}
static void map_failure(const Bytes &archive){
    Trial t(archive);t.to_ready();t.module("apps_mem",50);
    Bytes mem(32);N::p32(mem.data()+8,0x1000);N::p64(mem.data()+24,4096);
    t.reverse(51,2,2,{mem},{16});auto map=t.io.last(1,N::MmapSc);
    t.finish(map,-12);auto next=t.io.last(3,N::ListenerNext2Sc);auto primitive=t.io.arg(next,0);
    check(int32_t(N::u32(primitive.data+4))==-12&&N::u32(primitive.data+8)==0,"failed DSP mmap returns its error with no fake output");
    check(t.session.result.maps==0&&!t.session.result.failed,"failed map is not counted as an active mapping");
}
static void archive_checks(const Bytes &archive){
    N::Archive a;require(a.load(archive.data(),archive.size()),"archive load");
    const uint8_t *original,*alias;uint32_t n,m;
    require(a.open("/vendor/dsp/sdsp/libprobe.so",original,n),"canonical fixture path");
    check(a.open("/dsp/sdsp/libprobe.so",alias,m)&&alias==original&&m==n,"DSP archive alias returns exact immutable bytes");
    check(a.open("/vendor/lib/rfsa/adsp/libprobe.so",alias,m)&&alias==original&&m==n,"rfsa archive alias preserves subdirectory and content");
    char name[256];uint32_t size;
    check(a.list("/vendor/dsp",0,name,sizeof name,size)==1&&!strcmp(name,"sdsp")&&size==0,"archive lists nested directories once");
    check(a.list("/vendor/dsp",1,name,sizeof name,size)==0,"archive directory ends without phantom entries");
    check(a.list("/absent",0,name,sizeof name,size)==-1,"archive distinguishes missing directory");
}
struct RegistryIO {
    Bytes request;bool blocked=false;
    bool send_ssc(uint32_t node,uint32_t port,uint32_t from,const uint8_t *data,unsigned size){
        require(node==9&&port==12&&from==0x101,"registry endpoint");
        if(blocked)return false;request.assign(data,data+size);return true;
    }
};
static Bytes qmi_response(unsigned transaction=1,unsigned client=39){
    Bytes b={2,1,0,0x20,0,25,0,2,4,0,0,0,0,0,0x10,8,0,39,0,0,0,0,0,0,0,0x11,4,0,0,0,0,0};
    S::put16(b.data()+1,transaction);N::p64(b.data()+17,client);return b;
}
static Bytes suid_event(const char *type,bool nonempty,unsigned client=39){
    uint8_t id[24],payload[128],event[256],top[320];S::Writer uid(id,sizeof id),p(payload,sizeof payload),e(event,sizeof event),t(top,sizeof top);
    uid.fixed(1,0xababababababababULL,8);uid.fixed(2,0xababababababababULL,8);
    p.string(1,type);
    if(nonempty){uint8_t candidate[24];S::Writer c(candidate,sizeof candidate);c.fixed(1,1,8);c.fixed(2,2,8);p.message(2,candidate,c.size);}
    e.fixed(1,768,4);e.fixed(2,19200000,8);e.message(3,payload,p.size);
    t.message(1,id,uid.size);t.message(2,event,e.size);
    Bytes result(7+11+5+t.size);result[0]=4;S::put16(result.data()+3,0x22);S::put16(result.data()+5,result.size()-7);
    result[7]=1;S::put16(result.data()+8,8);N::p64(result.data()+10,client);
    result[18]=2;S::put16(result.data()+19,t.size+2);S::put16(result.data()+21,t.size);memcpy(result.data()+23,top,t.size);return result;
}
static void registry_checks(){
    RegistryIO io;S::Registry<RegistryIO> registry(io);registry.start(9,12,100);registry.tick(100);
    uint8_t expected[512];size_t n=S::encode_lookup(expected,sizeof expected,1,"registry",true,true);
    check(io.request==Bytes(expected,expected+n),"registry request enables updates and only default values");
    auto ack=qmi_response();registry.receive(9,12,ack.data(),ack.size());
    check(registry.responses==1&&!registry.ready&&!registry.failed,"QMI acknowledgement alone is not registry readiness");
    auto empty=suid_event("registry",false);registry.receive(9,12,empty.data(),empty.size());
    check(registry.events==1&&registry.candidates==0&&!registry.ready,"empty registry list does not set ready");
    auto other=suid_event("accel",true);registry.receive(9,12,other.data(),other.size());
    check(registry.events==1&&!registry.ready,"other datatype cannot satisfy registry readiness");
    auto event=suid_event("registry",true);registry.receive(9,12,event.data(),event.size());
    check(registry.ready&&registry.events==2&&registry.candidates==1,"nonempty registry SUID event sets readiness");
    RegistryIO time_io;S::Registry<RegistryIO> deadline(time_io);deadline.start(9,12,100);deadline.tick(15099);
    check(!deadline.timeout,"registry deadline allows time before 15 seconds");deadline.tick(15100);
    check(deadline.timeout&&!deadline.ready,"registry expires at 15 seconds");
    deadline.receive(9,12,event.data(),event.size());
    check(!deadline.ready,"late SUID event cannot revive timed-out registry discovery");
    RegistryIO fail_io;S::Registry<RegistryIO> failed(fail_io);failed.start(9,12,0);failed.tick(0);
    auto error=qmi_response();error[10]=1;failed.receive(9,12,error.data(),error.size());
    failed.receive(9,12,event.data(),event.size());
    check(failed.failed&&!failed.ready,"failed registry query cannot later report readiness");
    puts("PASS CASE: registry response/event distinctions and fixed deadline checked");
}
int main(int argc,char **argv){
    require(argc==2,"archive fixture argument");auto archive=read(argv[1]);
    try {archive_checks(archive);session_checks(archive);concurrency_checks(archive);unsupported_map_flags(archive);unmap_size_width(archive);map_failure(archive);registry_checks();}
    catch(const std::exception &error){printf("HARNESS FAILURE: %s\n",error.what());return 2;}
    printf("CHECKS %u FAILURES %u\n",checks,failures);return failures?1:0;
}
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    for name in ('NabuFastRpcProtocol.h','NabuFastRpcFiles.h','NabuFastRpcSession.h','NabuFastRpcArchive.h','NabuSscProtocol.h','NabuSscRegistry.h'):
        shutil.copyfile(ROOT/'patches/nabu-sensors'/name,a.output/name)
    for src,dst in [('quic-listener_buf.h','listener_buf.h'),('quic-sbuf.h','sbuf.h')]:shutil.copyfile(a.reference/src,a.output/dst)
    (a.output/'remote.h').write_text('#pragma once\n#include <stddef.h>\ntypedef union {struct {void *pv;size_t nLen;} buf;} remote_arg;\n')
    (a.output/'AEEstd.h').write_text('#pragma once\n#define STD_MIN(a,b) ((a)<(b)?(a):(b))\n')
    (a.output/'AEEStdErr.h').write_text('#pragma once\n#define AEE_SUCCESS 0\n#define AEE_EBADPARM 14\n')
    (a.output/'verify.h').write_text('#pragma once\n#define C_ASSERT(x) static_assert(x,"oracle")\n#define VERIFY(x) do {if(!(x)){nErr=1;goto bail;}}while(0)\n')
    source=a.output/'fastrpc-session.cpp';source.write_text(HARNESS,newline='\n')
    oracle=a.output/'listener-oracle.cpp';oracle.write_text(ORACLE,newline='\n')
    files={'/vendor/dsp/sdsp/libprobe.so':b'archive probe\n','/mnt/vendor/persist/sensors/registry/registry/a':b'{"sensor":true}\n'}
    position=16+264*len(files);entries=bytearray();payload=bytearray()
    for name,data in sorted(files.items()):
        entries.extend(struct.pack('<256sII',name.encode(),position,len(data)));payload.extend(data);position+=len(data)
    fixture=a.output/'fixture-files.bin';fixture.write_bytes(b'NABURPC1'+struct.pack('<II',len(files),position)+entries+payload)
    binary=a.output/'fastrpc-session'
    command=host_command(['g++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-sign-compare','-Wno-misleading-indentation',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-g','-I'+host_path(a.output.resolve()),
        host_path(source.resolve()),host_path(oracle.resolve()),'-o',host_path(binary.resolve())])
    r=subprocess.run(command,capture_output=True);(a.output/'compile.log').write_bytes(r.stdout+r.stderr)
    if r.returncode:raise SystemExit(r.stderr.decode(errors='replace'))
    r=subprocess.run(host_command([host_path(binary.resolve()),host_path(fixture.resolve())]),capture_output=True,timeout=45)
    (a.output/'run.log').write_bytes(r.stdout+r.stderr)
    report={'passed':r.returncode==0,'exit_code':r.returncode,'command':command,'stdout':r.stdout.decode(errors='replace'),
        'device_execution':False,'source_snapshot':str(a.output.resolve()),
        'limitation':'Controlled host responses and immutable fixture archive; no SMMU, DSP or iPadOS execution'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['stdout'])
    if r.returncode:raise SystemExit(r.stderr.decode(errors='replace') or 'Session/registry checks failed; see saved run.log')

if __name__=='__main__':main()
