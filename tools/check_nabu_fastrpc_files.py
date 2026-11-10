#!/usr/bin/env python3
"""Exercise immutable FastRPC file service with Qualcomm-framed requests."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from check_darwinboot_8796 import host_command,host_path
from check_nabu_fastrpc import ORACLE

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <string>
#include <vector>
#include "NabuFastRpcFiles.h"
#include "AEE-error-source.h"
namespace N=NabuFastRpc;
using Bytes=std::vector<uint8_t>;
extern "C" unsigned oracle_request(unsigned char *,unsigned,const unsigned char **,
                                    const unsigned *,unsigned,const unsigned *,unsigned);
struct IO {
    unsigned logs=0;int result=0;std::string last;
    bool rpc_file_open(const char *path,const uint8_t *&data,uint32_t &size){
        static const uint8_t text[]={'s','e','n','s','o','r','\n'};
        if(strcmp(path,"/rpc/registry/item")&&strcmp(path,"/dsp/sdsp/libsample.so"))return false;
        data=text;size=sizeof text;return true;
    }
    const char *rpc_file_env(const char *name){return !strcmp(name,"ADSP_LIBRARY_PATH")?"/dsp;/dsp/sdsp":nullptr;}
    int rpc_file_list(const char *path,uint32_t index,char *name,uint32_t capacity,uint32_t &size){
        if(strcmp(path,"/rpc/registry"))return -1;
        if(index){name[0]=0;return 0;}
        assert(capacity>=5);memcpy(name,"item",5);size=7;return 1;
    }
    void rpc_file_log(uint32_t,uint32_t,const char *path,int32_t code){++logs;last=path;result=code;}
};
static Bytes words(std::initializer_list<uint32_t> values){Bytes b(values.size()*4);unsigned i=0;for(auto v:values){N::p32(b.data()+i,v);i+=4;}return b;}
static Bytes str(const char *s){return Bytes(s,s+strlen(s)+1);}
struct Returned {int32_t result;Bytes packed;std::vector<Bytes> out;};
template<class Service> static Returned call(Service &service,uint32_t handle,uint32_t method,
        const std::vector<Bytes> &in,const std::vector<unsigned> &out){
    const uint8_t *data[16]{};unsigned lengths[16]{};
    for(unsigned i=0;i<in.size();++i){data[i]=in[i].data();lengths[i]=in[i].size();}
    Bytes request(2048),response(2048);unsigned used=0;
    unsigned size=oracle_request(request.data(),request.size(),data,lengths,in.size(),out.data(),out.size());
    Returned r;r.result=service.invoke(handle,N::scalars(method,in.size(),out.size()),
        {request.data(),size},response.data(),response.size(),used);
    assert((r.result==0)||(used==0));response.resize(used);r.packed=response;
    if(!r.result){
        unsigned at=0;
        for(auto wanted:out){
            assert(at+4<=used&&N::u32(response.data()+at)==wanted);at+=4;
            if(wanted)at=(at+7)&~7u;
            assert(at+wanted<=used);r.out.emplace_back(response.begin()+at,response.begin()+at+wanted);at+=wanted;
        }
        assert(at==used);
    }
    return r;
}
int main(){
    static_assert(N::NoSuchFile==ENOENT&&N::BadFile==EBADF,"apps_std errno values");
    static_assert(N::InvalidArgument==EINVAL&&N::TooManyFiles==EMFILE,"file errno values");
    static_assert(N::BadParameter==AEE_EBADPARM&&N::Unsupported==AEE_EUNSUPPORTED&&N::InvalidHandle==AEE_EINVHANDLE,"HLOS AEE values");
    static IO io;static N::Files<IO> f(io);
    auto stdname=str("apps_std"),memname=str("apps_mem"),unknown=str("no_such_module");
    auto module=call(f,0,0,{words({unsigned(stdname.size()),32}),stdname},{8,32});
    assert(module.result==0&&N::u32(module.out[0].data())==1);
    auto rejected=call(f,0,0,{words({unsigned(unknown.size()),32}),unknown},{8,32});
    assert(rejected.result==N::Unsupported&&io.last=="no_such_module");
    auto filename=str("/rpc/registry/item"),readmode=str("rb"),write=str("w");
    auto opened=call(f,1,0,{words({unsigned(filename.size()),unsigned(readmode.size())}),filename,readmode},{4});
    assert(opened.result==0);uint32_t fd=N::u32(opened.out[0].data());
    auto read=call(f,1,4,{words({fd,4})},{8,4});
    assert(read.result==0&&N::u32(read.out[0].data())==4&&N::u32(read.out[0].data()+4)==0);
    assert(read.out[1]==Bytes({'s','e','n','s'}));
    read=call(f,1,4,{words({fd,6})},{8,6});
    assert(N::u32(read.out[0].data())==3&&N::u32(read.out[0].data()+4)==1);
    assert(read.out[1]==Bytes({'o','r','\n',0,0,0}));
    auto length=call(f,1,10,{words({fd})},{8});assert(length.result==0&&N::u64(length.out[0].data())==7);
    auto sought=call(f,1,9,{words({fd,uint32_t(-3),2})},{});assert(sought.result==0);
    auto tell=call(f,1,8,{words({fd})},{4});assert(N::u32(tell.out[0].data())==4);
    auto eof=call(f,1,12,{words({fd})},{4});assert(N::u32(eof.out[0].data())==0);
    assert(call(f,1,9,{words({fd,uint32_t(-9),0})},{}).result==N::InvalidArgument);
    assert(call(f,1,4,{words({fd,99})},{8,1}).result==N::BadParameter);
    auto mutation=call(f,1,0,{words({unsigned(filename.size()),unsigned(write.size())}),filename,write},{4});
    assert(mutation.result==N::Unsupported&&io.last=="/rpc/registry/item");
    assert(call(f,1,5,{words({fd,1}),Bytes({'X'})},{8}).result==N::Unsupported);
    assert(call(f,1,3,{words({fd})},{}).result==0);
    assert(call(f,1,4,{words({fd,1})},{8,1}).result==N::BadFile);
    auto env=str("ADSP_LIBRARY_PATH");
    auto environment=call(f,1,16,{words({unsigned(env.size()),8}),env},{4,8});
    assert(environment.result==0&&N::u32(environment.out[0].data())==strlen("/dsp;/dsp/sdsp")+1);
    assert(environment.out[1]==Bytes({'/','d','s','p',';','/','d',0}));
    auto missing_env=str("UNDEFINED_RPC_ENV");
    assert(call(f,1,16,{words({unsigned(missing_env.size()),4}),missing_env},{4,4}).result==-1);
    auto lib=str("libsample.so"),delim=str(";");
    auto library=call(f,1,19,{words({unsigned(env.size()),unsigned(delim.size()),unsigned(lib.size()),unsigned(readmode.size())}),env,delim,lib,readmode},{4});
    assert(library.result==0&&io.last=="/dsp/sdsp/libsample.so");
    auto absent=str("/missing");
    assert(call(f,1,0,{words({unsigned(absent.size()),unsigned(readmode.size())}),absent,readmode},{4}).result==N::NoSuchFile);
    auto exists=call(f,1,22,{words({unsigned(absent.size())}),absent},{1});
    assert(exists.result==0&&exists.out[0][0]==0);
    auto dirname=str("/rpc/registry");
    auto dir=call(f,1,26,{words({unsigned(dirname.size())}),dirname},{8});assert(dir.result==0);
    uint64_t dh=N::u64(dir.out[0].data());Bytes dhbytes(8);N::p64(dhbytes.data(),dh);
    auto entry=call(f,1,28,{dhbytes},{264});assert(entry.result==0&&!strcmp(reinterpret_cast<char *>(entry.out[0].data()+4),"item"));
    assert(N::u32(entry.out[0].data()+260)==0);
    entry=call(f,1,28,{dhbytes},{264});assert(entry.result==0&&N::u32(entry.out[0].data()+260)==1);
    assert(call(f,1,27,{dhbytes},{}).result==0);
    assert(call(f,1,28,{dhbytes},{264}).result==N::BadFile);
    auto stat=call(f,1,31,{words({31,unsigned(filename.size())}),filename},{96});
    assert(stat.result==0&&N::u64(stat.out[0].data()+40)==7&&N::u32(stat.out[0].data()+24)==0100444u);
    assert(call(f,1,31,{words({99})},{}).result==N::Unsupported&&f.last.method==99);
    assert(call(f,1,0,{words({8,3}),Bytes({'x','x'}),readmode},{4}).result==N::BadParameter);
    module=call(f,0,0,{words({unsigned(memname.size()),0}),memname},{8,0});
    assert(module.result==0&&N::u32(module.out[0].data())==2);
    Bytes mem(32);N::p32(mem.data(),uint32_t(-1));N::p32(mem.data()+4,1);N::p32(mem.data()+8,0x1000);
    N::p64(mem.data()+16,0x12340000);N::p64(mem.data()+24,0x8000);
    auto map=call(f,2,2,{mem},{16});
    assert(map.result==N::Unsupported&&f.pending_memory.valid&&f.pending_memory.method==2);
    assert(f.pending_memory.heap_id==0xffffffff&&f.pending_memory.rflags==0x1000&&f.pending_memory.vin==0x12340000&&f.pending_memory.size==0x8000);
    assert(call(f,0,1,{words({1,0})},{4,0}).result==0);
    assert(call(f,1,0,{words({unsigned(filename.size()),unsigned(readmode.size())}),filename,readmode},{4}).result==N::InvalidHandle);
    assert(io.logs==f.calls&&f.failures>0&&f.unknown>0);
    puts("PASS: apps_remotectl, immutable file bytes, EOF/seek/length, env search, directories/stat, unknown and mutation errors, pending apps_mem request ABI");
}
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    for src,dst in [('quic-listener_buf.h','listener_buf.h'),('quic-sbuf.h','sbuf.h'),('quic-AEEStdErr.h','AEE-error-source.h')]:shutil.copyfile(a.reference/src,a.output/dst)
    (a.output/'remote.h').write_text('#pragma once\n#include <stddef.h>\ntypedef union {struct {void *pv;size_t nLen;} buf;} remote_arg;\n')
    (a.output/'AEEstd.h').write_text('#pragma once\n#define STD_MIN(a,b) ((a)<(b)?(a):(b))\n')
    (a.output/'AEEStdErr.h').write_text('#pragma once\n#define AEE_SUCCESS 0\n#define AEE_EBADPARM 14\n')
    (a.output/'verify.h').write_text('#pragma once\n#define C_ASSERT(x) static_assert(x,"oracle")\n#define VERIFY(x) do {if(!(x)){nErr=1;goto bail;}}while(0)\n')
    source=a.output/'fastrpc-files.cpp';source.write_text(HARNESS,newline='\n')
    oracle=a.output/'listener-oracle.cpp';oracle.write_text(ORACLE,newline='\n')
    binary=a.output/'fastrpc-files'
    command=host_command(['g++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-sign-compare','-Wno-misleading-indentation',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-g',
        '-I'+host_path(ROOT/'patches/nabu-sensors'),'-I'+host_path(a.output.resolve()),
        host_path(source.resolve()),host_path(oracle.resolve()),'-o',host_path(binary.resolve())])
    r=subprocess.run(command,capture_output=True);(a.output/'compile.log').write_bytes(r.stdout+r.stderr)
    if r.returncode:raise SystemExit(r.stderr.decode(errors='replace'))
    r=subprocess.run(host_command([host_path(binary.resolve())]),capture_output=True,timeout=30)
    (a.output/'run.log').write_bytes(r.stdout+r.stderr)
    report={'passed':r.returncode==0,'command':command,'stdout':r.stdout.decode(errors='replace'),
        'device_execution':False,'limitation':'In-memory fixture, not original DSP execution or calibration persistence'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['stdout'])
    if r.returncode:raise SystemExit(r.stderr.decode(errors='replace'))

if __name__=='__main__':main()
