"""Compare actual before/after vertex binding and effective registers at every draw."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import shutil
from check_darwinboot_8796 import host_command,host_path
from nabu_turnip_vertex_state import function,FILES,PATCH

HARNESS=r'''
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdio>
#include <random>
#include <stdexcept>
#include <vector>
#define VKAPI_ATTR
#define VKAPI_CALL
#define MAX2(a,b) std::max(a,b)
#define VK_FROM_HANDLE(type,name,value) type *name=value
using VkDeviceSize=uint64_t;
constexpr VkDeviceSize VK_WHOLE_SIZE=~uint64_t(0);
constexpr int TU_RESOURCE_READ=1, TU_CMD_DIRTY_VERTEX_BUFFERS=1;
struct vk_buffer {uint64_t va,size;};
struct tu_buffer {vk_buffer vk; unsigned identity;};
using VkBuffer=tu_buffer*;
constexpr VkBuffer VK_NULL_HANDLE=nullptr;
static tu_buffer *tu_buffer_from_handle(VkBuffer b){return b;}
static uint64_t vk_buffer_address(vk_buffer *b,uint64_t offset){return b->va+offset;}
static uint64_t vk_buffer_range(vk_buffer *b,uint64_t offset,uint64_t size){return std::min(b->size-offset,size);}
struct Binding {uint64_t base=0;uint32_t size=0;bool operator==(const Binding&)const=default;};
using Registers=std::array<Binding,32>;
struct tu_cmd_buffer;
struct tu_cs {tu_cmd_buffer *owner=nullptr;size_t block=0;};
struct tu_draw_state {uint64_t iova=0;uint32_t size=0;};
struct vk_command {std::array<uint64_t,32> strides{};bool stride_dirty=false;};
struct tu_cmd_buffer {
  vk_command vk;
  struct {Registers vb{};uint32_t max_vbs_bound=0,dirty=0;tu_draw_state vertex_buffers{};
    uint64_t vertex_bind_calls=0,vertex_bind_reuses=0,vertex_state_builds=0;
    uint64_t vertex_state_baseline_dwords=0,vertex_state_emitted_dwords=0;} state;
  tu_cs sub_cs{this,0};
  std::vector<Registers> blocks;
  uint64_t allocated_dwords=0,group_loads=0;
  std::vector<unsigned> resources;
  Registers gpu{};
};
using VkCommandBuffer=tu_cmd_buffer*;
static void vk_cmd_set_vertex_binding_strides(vk_command *v,uint32_t first,uint32_t count,const uint64_t *p){
  for(uint32_t i=0;i<count;i++){v->stride_dirty|=v->strides[first+i]!=p[i];v->strides[first+i]=p[i];}
}
static void tu_cmd_use_buffer(tu_cmd_buffer *c,tu_buffer*b,int access){
  if(access!=1)throw std::runtime_error("resource access");c->resources.push_back(b->identity);
}
static tu_draw_state tu_cs_draw_state(tu_cs *parent,tu_cs *cs,uint32_t size){
  auto *c=parent->owner;cs->owner=c;cs->block=c->blocks.size();c->blocks.emplace_back();
  c->allocated_dwords+=size;return {cs->block+1,size};
}
struct Base {uint64_t qword;};
struct BaseReg {unsigned slot;uint64_t base;};
struct SizeReg {unsigned slot;uint32_t size;};
#define A6XX_VFD_VERTEX_BUFFER_BASE(i,...) BaseReg{i,Base{__VA_ARGS__}.qword}
#define A6XX_VFD_VERTEX_BUFFER_SIZE(i,s) SizeReg{i,s}
static void tu_cs_emit_regs(tu_cs *cs,BaseReg base,SizeReg size){
  if(base.slot!=size.slot)throw std::runtime_error("register mismatch");
  cs->owner->blocks.at(cs->block)[base.slot]={base.base,size.size};
}
namespace before {
/* BEFORE */
}
namespace after {
/* AFTER */
/* EMIT */
}
static void check(bool value,const char *what){if(!value)throw std::runtime_error(what);}
static void draw(tu_cmd_buffer &c,bool optimized,bool full=false){
  if(optimized && (c.state.dirty&TU_CMD_DIRTY_VERTEX_BUFFERS))after::tu_emit_vertex_buffer_state(&c);
  if((c.state.dirty&TU_CMD_DIRTY_VERTEX_BUFFERS)||full){
    if(c.state.vertex_buffers.iova)c.gpu=c.blocks.at(c.state.vertex_buffers.iova-1);
    c.group_loads++;
  }
  c.state.dirty=0;c.vk.stride_dirty=false;
}
static void compare(tu_cmd_buffer&a,tu_cmd_buffer&b,bool full=false){
  draw(a,false,full);draw(b,true,full);
  check(a.gpu==b.gpu,"effective vertex registers differ");
  check(a.vk.strides==b.vk.strides,"stride state differs");
  check(a.resources==b.resources,"resource reference sequence differs");
  check(a.state.max_vbs_bound==b.state.max_vbs_bound,"bound high-water differs");
}
static void bind(tu_cmd_buffer&a,tu_cmd_buffer&b,unsigned first,unsigned count,VkBuffer*buf,
                 uint64_t*off,uint64_t*sz=nullptr,uint64_t*stride=nullptr){
  before::tu_CmdBindVertexBuffers2(&a,first,count,buf,off,sz,stride);
  after::tu_CmdBindVertexBuffers2(&b,first,count,buf,off,sz,stride);
  check(a.vk.stride_dirty==b.vk.stride_dirty,"stride dirty differs");
}
int main(){
  tu_buffer buffers[]={{ {0x10000,4096},1},{{0x20000,8192},2},{{0x10000,4096},3},{{0x40000,0x200000020ULL},4}};
  unsigned draws=0;
  {
    tu_cmd_buffer a,b;VkBuffer buf[]={buffers};uint64_t off[]={16};
    for(unsigned i=0;i<1024;i++){bind(a,b,0,1,buf,off);compare(a,b);draws++;}
    check(a.blocks.size()==1024&&b.blocks.size()==1,"identical bind block reuse");
    check(a.group_loads==1024&&b.group_loads==1,"identical bind GPU group reuse");
    check(b.state.vertex_bind_reuses==1023,"reuse counter");
    printf("{\"case\":\"identical_draws\",\"before_blocks\":%zu,\"after_blocks\":%zu,\"before_gpu_loads\":%llu,\"after_gpu_loads\":%llu,\"saved_setup_dwords\":%llu}\n",
      a.blocks.size(),b.blocks.size(),(unsigned long long)a.group_loads,(unsigned long long)b.group_loads,
      (unsigned long long)(b.state.vertex_state_baseline_dwords-b.state.vertex_state_emitted_dwords));
    a.gpu={};b.gpu={};compare(a,b,true);draws++;
    check(b.gpu[0].base==0x10010,"full restoration after clobber");
    uint64_t stride[]={64};bind(a,b,0,1,buf,off,nullptr,stride);compare(a,b);draws++;
    check(b.blocks.size()==1&&b.vk.strides[0]==64,"stride-only rebind");
    buf[0]=buffers+2;bind(a,b,0,1,buf,off);compare(a,b);draws++;
    check(b.blocks.size()==1&&b.resources.back()==3,"alias buffer resource preserved");
    uint64_t size[]={28};bind(a,b,0,1,buf,off,size);compare(a,b);draws++;
    check(b.gpu[0].size==28,"range change");
    buf[0]=nullptr;bind(a,b,0,1,buf,off);compare(a,b);draws++;
    check(b.gpu[0].base==0&&b.gpu[0].size==0,"null binding");
  }
  {
    tu_cmd_buffer a,b;VkBuffer buf[]={buffers};uint64_t off[]={0};
    for(unsigned i=0;i<24;i++)bind(a,b,i,1,buf,off);
    check(b.blocks.empty(),"binds deferred before draw");compare(a,b);draws++;
    check(a.blocks.size()==24&&b.blocks.size()==1,"binding batch coalesced");
    printf("{\"case\":\"multiple_bindings_before_draw\",\"before_blocks\":%zu,\"after_blocks\":%zu,\"before_dwords\":%llu,\"after_dwords\":%llu}\n",
      a.blocks.size(),b.blocks.size(),(unsigned long long)a.allocated_dwords,(unsigned long long)b.allocated_dwords);
    buf[0]=buffers+3;bind(a,b,31,1,buf,off);compare(a,b);draws++;
    check(b.gpu[31].size==32,"existing 32-bit range representation");
  }
  {
    std::mt19937 rng(271126);tu_cmd_buffer a,b;
    for(unsigned step=0;step<10000;step++){
      unsigned first=rng()%29,count=1+rng()%3;VkBuffer buf[3];uint64_t off[3],sz[3],stride[3];
      for(unsigned i=0;i<count;i++){
        unsigned index=rng()%5;buf[i]=index==4?nullptr:buffers+index;
        off[i]=rng()%128;sz[i]=(rng()%2)?uint64_t(rng()%1024):VK_WHOLE_SIZE;stride[i]=4*(rng()%32);
      }
      bind(a,b,first,count,buf,off,rng()%2?sz:nullptr,rng()%2?stride:nullptr);
      if(rng()%3==0){compare(a,b);draws++;}
      if(step%333==0){a.gpu={};b.gpu={};compare(a,b,true);draws++;}
    }
    compare(a,b);draws++;
    check(b.state.vertex_state_emitted_dwords==b.allocated_dwords,"emission accounting");
    check(b.state.vertex_state_baseline_dwords==a.allocated_dwords,"baseline accounting");
  }
  {
    tu_cmd_buffer a,b;VkBuffer buf[]={nullptr};uint64_t off[]={0};
    bind(a,b,0,1,buf,off);compare(a,b);draws++;
    check(b.blocks.size()==1,"initial null high-water state");
    tu_cmd_buffer reset_a,reset_b;buf[0]=buffers;
    bind(reset_a,reset_b,0,1,buf,off);compare(reset_a,reset_b);draws++;
    check(reset_b.blocks.size()==1&&reset_b.state.vertex_bind_calls==1,"fresh recording/reset");
  }
  printf("{\"passed\":true,\"draw_register_comparisons\":%u,\"random_binding_calls\":10000}\n",draws);
}
'''

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    after=a.source.read_text(encoding='utf-8')
    if a.baseline:
        before=a.baseline.read_text(encoding='utf-8')
    else:
        with tempfile.TemporaryDirectory(prefix='nabu-vb-baseline-') as temporary:
            target=Path(temporary);directory=target/'src/freedreno/vulkan'
            directory.mkdir(parents=True)
            for name in FILES:shutil.copyfile(a.source.parent/name,directory/name)
            patch=Path(__file__).resolve().parents[1]/'patches/nabu-vulkan'/PATCH
            subprocess.run(['git','apply','--reverse',str(patch)],cwd=target,check=True)
            before=(directory/'tu_cmd_buffer.cc').read_text(encoding='utf-8')
    text=HARNESS.replace('/* BEFORE */',function(before,'tu_CmdBindVertexBuffers2'))
    text=text.replace('/* AFTER */',function(after,'tu_CmdBindVertexBuffers2'))
    text=text.replace('/* EMIT */',function(after,'tu_emit_vertex_buffer_state'))
    cpp=a.output/'actual-vertex-state.cpp';cpp.write_text(text,encoding='utf-8',newline='\n')
    results=[]
    for mode,flags in [('release',['-O2']),('sanitized',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
        exe=a.output/mode
        cmd=['clang++','-std=c++20','-Wall','-Wextra','-Werror',*flags,host_path(cpp),'-o',host_path(exe)]
        for phase,command in [('compile',cmd),('run',[host_path(exe)])]:
            r=subprocess.run(host_command(command),capture_output=True)
            (a.output/(mode+'-'+phase+'.log')).write_bytes(r.stdout+r.stderr)
            if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
        results.append(dict(mode=mode,results=[json.loads(line) for line in r.stdout.splitlines()]))
    report=dict(passed=True,results=results,actual_functions_extracted=True,
        covered=['repeated bindings','batch before draw','full state restore','stride-only updates',
            'alias resources','range changes','null binding','sparse high-water','32-bit size semantics',
            '10000 randomized binds','new recording'],
        limits='Host effective register and resource equivalence. No real GPU timing or physical pixel validation.')
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
