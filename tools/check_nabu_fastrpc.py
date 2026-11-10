#!/usr/bin/env python3
"""Check FastRPC framing against nabu kernel structs and Qualcomm listener codec."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include <sys/ioctl.h>
#include "adsprpc_shared.h"
#include "NabuFastRpcProtocol.h"
namespace N=NabuFastRpc;
extern "C" unsigned oracle_request(unsigned char *,unsigned,const unsigned char **,
                                    const unsigned *,unsigned,const unsigned *,unsigned);
extern "C" unsigned oracle_reply(unsigned char *,unsigned,const unsigned char **,
                                  const unsigned *,unsigned);
static void inspect_layout(const unsigned char *memory,const N::Layout &l,unsigned sc,
                           unsigned long long va,unsigned long long iova,const N::Arg *a){
    const auto *ra=reinterpret_cast<const remote_arg64_t *>(memory);
    const auto *list=smq_invoke_buf_start(const_cast<remote_arg64_t *>(ra),sc);
    const auto *page=smq_phy_page_start(sc,const_cast<smq_invoke_buf *>(list));
    for(unsigned i=0;i<l.count;++i){
        assert(ra[i].buf.len==a[i].bytes);
        assert(list[i].pgidx==int(i));
        assert(list[i].num==(a[i].bytes?1:0));
        if(!a[i].bytes){assert(ra[i].buf.pv==0);continue;}
        assert(ra[i].buf.pv==va+l.offset[i]);
        assert((l.offset[i]&127)==0);
        assert(page[i].addr==iova+(l.offset[i]&~4095u));
        assert(page[i].size==((l.offset[i]%4096+a[i].bytes+4095)&~4095u));
        assert(page[i].addr+page[i].size<=iova+l.page_bytes);
    }
    const auto *tail=reinterpret_cast<const unsigned char *>(page+l.count);
    for(unsigned i=0;i<16*8+64*4;++i)assert(tail[i]==0);
}
int main(){
    static_assert(sizeof(smq_msg)==40,"nabu wire size");
    static_assert(sizeof(smq_invoke_rsp)==16,"nabu reply size");
    static_assert(offsetof(smq_msg,invoke)==8,"invoke location");
    static_assert(sizeof(remote_arg64_t)==16,"remote argument size");
    static_assert(sizeof(smq_invoke_buf)==8&&sizeof(smq_phy_page)==16,"page list layout");
    constexpr unsigned long long va=0xfffffff400100000ULL,iova=0x180000000ULL;
    alignas(4096) static unsigned char memory[32768];
    unsigned char tgid[4];N::p32(tgid,0x4321);
    N::Arg attach[]={{tgid,4}};N::Layout l;
    assert(N::build_args(memory,sizeof memory,va,iova,N::AttachSc,attach,l));
    assert(l.used==516&&l.page_bytes==4096&&l.offset[0]==512);
    inspect_layout(memory,l,N::AttachSc,va,iova,attach);
    assert(!memcmp(memory+l.offset[0],tgid,4));
    unsigned char frame[40];
    N::encode_message(frame,0,0x4321,0x1000,N::SensorsPd,1,N::AttachSc,iova,l.used);
    smq_msg expected{};expected.pid=0;expected.tid=0x4321;
    expected.invoke.header.ctx=0x1002;expected.invoke.header.handle=1;
    expected.invoke.header.sc=REMOTE_SCALARS_MAKE(0,1,0);
    expected.invoke.page.addr=iova;expected.invoke.page.size=4096;
    assert(!memcmp(frame,&expected,sizeof expected));
    smq_invoke_rsp reply{};reply.ctx=0x1002;reply.retval=-9;N::Response response;
    assert(N::decode_response(reinterpret_cast<unsigned char *>(&reply),sizeof reply,response));
    assert(response.result==-9&&N::matches_context(response,0x1000));
    assert(!N::matches_context(response,0x2000));
    assert(!N::decode_response(reinterpret_cast<unsigned char *>(&reply),12,response));
    assert(N::build_args(nullptr,0,0,0,N::ListenerInit2Sc,nullptr,l));
    N::encode_message(frame,0x4321,0x4321,0x2000,N::SensorsPd,3,N::ListenerInit2Sc,0,l.used);
    assert(N::u64(frame+24)==0&&N::u64(frame+32)==4096);
    unsigned char in[16];N::listener_next_input(in,0,-1,0,8192);
    const unsigned char initial[]={0,0,0,0,255,255,255,255,0,0,0,0,0,32,0,0};
    assert(!memcmp(in,initial,16));
    N::Arg next[]={{in,16},{nullptr,0},{nullptr,16},{nullptr,8192}};
    assert(N::ListenerNext2Sc==REMOTE_SCALARS_MAKE(4,2,2));
    assert(N::build_args(memory,sizeof memory,va,iova,N::ListenerNext2Sc,next,l));
    inspect_layout(memory,l,N::ListenerNext2Sc,va,iova,next);
    assert(l.offset[0]==640&&l.offset[1]==0&&l.offset[2]==768&&l.offset[3]==896);
    assert(l.used==9088&&l.page_bytes==12288);
    assert(!N::build_args(memory,8192,va,iova,N::ListenerNext2Sc,next,l));
    assert(!N::build_args(memory,sizeof memory,va+8,iova,N::AttachSc,attach,l));
    assert(!N::build_args(memory,sizeof memory,va,iova,N::AttachSc|1,attach,l));

    // nabu selects protocol methods 4/5 when compat_ioctl is present, even
    // for a 64-bit process; the primitive field counts page-list bytes.
    unsigned char mmap_prim[24],mmap_page[16];N::Arg mmap_args[3];
    unsigned mmap_sc=N::mmap_args(mmap_prim,mmap_page,mmap_args,0x4321,0x1000,0,0x180200000ULL,0x9000);
    struct MmapPrimitive {int pid;uint32_t flags;uintptr_t desired;int page_bytes;} primitive{};
    static_assert(sizeof(primitive)==24,"nabu mmap primitive");
    primitive.pid=0x4321;primitive.flags=0x1000;primitive.desired=0;primitive.page_bytes=16;
    smq_phy_page backing{0x180200000ULL,0x9000};
    assert(mmap_sc==REMOTE_SCALARS_MAKE(4,2,1));
    assert(!memcmp(mmap_prim,&primitive,24)&&!memcmp(mmap_page,&backing,16));
    assert(N::build_args(memory,sizeof memory,va,iova,mmap_sc,mmap_args,l));
    inspect_layout(memory,l,mmap_sc,va,iova,mmap_args);
    N::p64(memory+l.offset[2],0x93000000);uint64_t dsp_va=0;
    assert(N::mmap_output({memory+l.offset[2],8},dsp_va)&&dsp_va==0x93000000);
    assert(dsp_va!=backing.addr);
    N::Arg unmap_arg[1];unsigned unmap_sc=N::munmap_args(mmap_prim,unmap_arg,0x4321,dsp_va,0x9000);
    struct MunmapPrimitive {int pid;uintptr_t dsp;size_t size;} unmap{};
    static_assert(sizeof(unmap)==24,"nabu munmap primitive");
    unmap.pid=0x4321;unmap.dsp=dsp_va;unmap.size=0x9000;
    assert(unmap_sc==REMOTE_SCALARS_MAKE(5,1,0)&&!memcmp(mmap_prim,&unmap,24));
    assert(N::mmap_args(mmap_prim,mmap_page,mmap_args,0x4321,0,0,backing.addr,backing.size,false)==REMOTE_SCALARS_MAKE(2,2,1));
    assert(N::u32(mmap_prim+16)==1);
    assert(N::munmap_args(mmap_prim,unmap_arg,0x4321,dsp_va,0x9000,false)==REMOTE_SCALARS_MAKE(3,1,0));

    // Upstream packs zero-length buffers without adding any padding. Exercise
    // every alignment residue and the output-length trailer, not just roundtrips.
    unsigned char payload[16];for(unsigned i=0;i<16;++i)payload[i]=i+1;
    const unsigned lengths[]={0,1,2,3,4,5,6,7,8,9,0};
    const unsigned char *data[11];for(auto &d:data)d=payload;
    const unsigned out_sizes[]={16,0,37};
    unsigned char packet[1024]{};
    unsigned size=oracle_request(packet,sizeof packet,data,lengths,11,out_sizes,3);
    N::ReverseCall call;
    assert(N::decode_reverse(N::scalars(19,11,3),{packet,size},call));
    assert(call.input_count==11&&call.output_count==3);
    for(unsigned i=0;i<11;++i){
        assert(call.input[i].size==lengths[i]);
        if(lengths[i])assert(!memcmp(call.input[i].data,payload,lengths[i]));
    }
    for(unsigned i=0;i<3;++i)assert(call.output_size[i]==out_sizes[i]);
    for(unsigned cut=0;cut<size;++cut)
        assert(!N::decode_reverse(N::scalars(19,11,3),{packet,cut},call));
    assert(!N::decode_reverse(N::scalars(19,11,3),{packet,size+1},call));
    unsigned char encoded[1024]{};N::MutableSpan spans[16];unsigned used;
    assert(N::prepare_reverse_reply(encoded,sizeof encoded,lengths,11,spans,used));
    for(unsigned i=0;i<11;++i)if(lengths[i])memcpy(spans[i].data,payload,lengths[i]);
    memset(packet,0,sizeof packet);
    unsigned expected_size=oracle_reply(packet,sizeof packet,data,lengths,11);
    assert(used==expected_size&&!memcmp(packet,encoded,used));
    assert(!N::prepare_reverse_reply(encoded,used-1,lengths,11,spans,used));
    const unsigned too_large[]={0xffffffffu};
    assert(!N::prepare_reverse_reply(encoded,sizeof encoded,too_large,1,spans,used));
    puts("PASS: nabu message/argument structs, sensor attach, 34-bit IOVA page metadata, mmap/munmap, listener next2, Qualcomm reverse framing, zero lengths, bounds and response context");
}
'''
ORACLE=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include "listener_buf.h"
extern "C" unsigned oracle_request(unsigned char *dest,unsigned capacity,
                                    const unsigned char **data,const unsigned *sizes,unsigned in,
                                    const unsigned *out_sizes,unsigned out){
    remote_arg args[32]{};assert(in+out<=32);
    for(unsigned i=0;i<in;++i){args[i].buf.pv=const_cast<unsigned char *>(data[i]);args[i].buf.nLen=sizes[i];}
    for(unsigned i=0;i<out;++i)args[in+i].buf.nLen=out_sizes[i];
    sbuf buf;sbuf_init(&buf,0,dest,capacity);
    pack_in_bufs(&buf,args,in);pack_out_lens(&buf,args+in,out);
    return sbuf_needed(&buf);
}
extern "C" unsigned oracle_reply(unsigned char *dest,unsigned capacity,
                                  const unsigned char **data,const unsigned *sizes,unsigned count){
    remote_arg args[32]{};assert(count<=32);
    for(unsigned i=0;i<count;++i)args[i].buf.nLen=sizes[i];
    sbuf buf;sbuf_init(&buf,0,dest,capacity);assert(!pack_out_bufs(&buf,args,count,1));
    for(unsigned i=0;i<count;++i)if(sizes[i])memcpy(args[i].buf.pv,data[i],sizes[i]);
    return sbuf_needed(&buf);
}
'''

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    # The reference implementations are used unchanged. These small headers
    # supply only their platform types/macros, not serialization behavior.
    for source,dest in [('adsprpc_shared.h','adsprpc_shared.h'),
                        ('quic-listener_buf.h','listener_buf.h'),('quic-sbuf.h','sbuf.h')]:
        shutil.copyfile(a.reference/source,a.output/dest)
    (a.output/'remote.h').write_text('#pragma once\n#include <stddef.h>\n'
        'typedef union {struct {void *pv;size_t nLen;} buf;} remote_arg;\n')
    (a.output/'AEEstd.h').write_text('#pragma once\n#define STD_MIN(a,b) ((a)<(b)?(a):(b))\n')
    (a.output/'AEEStdErr.h').write_text('#pragma once\n#define AEE_SUCCESS 0\n#define AEE_EBADPARM 14\n')
    (a.output/'verify.h').write_text('#pragma once\n#define C_ASSERT(x) static_assert(x,"oracle")\n'
        '#define VERIFY(x) do {if(!(x)){nErr=1;goto bail;}}while(0)\n')
    source=a.output/'fastrpc-host.cpp';source.write_text(HARNESS,newline='\n')
    oracle=a.output/'listener-oracle.cpp';oracle.write_text(ORACLE,newline='\n')
    binary=a.output/'fastrpc-host'
    command=host_command(['g++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-sign-compare',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-g',
        '-I'+host_path(ROOT/'patches/nabu-sensors'),'-I'+host_path(a.output.resolve()),
        host_path(source.resolve()),host_path(oracle.resolve()),'-o',host_path(binary.resolve())])
    compile_result=subprocess.run(command,capture_output=True)
    (a.output/'compile.log').write_bytes(compile_result.stdout+compile_result.stderr)
    if compile_result.returncode:raise SystemExit(compile_result.stderr.decode(errors='replace'))
    result=subprocess.run(host_command([host_path(binary.resolve())]),capture_output=True,timeout=30)
    (a.output/'run.log').write_bytes(result.stdout+result.stderr)
    report={'passed':result.returncode==0,'command':command,'reference':str(a.reference),
        'stdout':result.stdout.decode(errors='replace'),'device_execution':False,
        'limitation':'Wire and shared-memory layout only; no SMMU, FastRPC DSP, or iPadOS execution'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(report['stdout'])
    if result.returncode:raise SystemExit(result.stderr.decode(errors='replace'))

if __name__=='__main__':main()
