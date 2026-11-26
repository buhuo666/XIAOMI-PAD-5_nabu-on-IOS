"""A640 candidate for the reproduced discard/stencil/read-only-depth hang.

This selects the legal late-test path for the observed state class. It does not
drop writes, disable tests, inspect application identity, or claim validation.
"""
import argparse,json,subprocess,shutil
from pathlib import Path

ANCHOR='''   /* User defined early tests take precedence above all else */'''
CHANGE='''   /* GPU359: A640 repeatedly hangs with discard + stencil writes and a
    * read-only depth attachment while using EARLY_Z_LATE_Z. Complete the
    * ordinary tests after shading for this state class. Explicit shader
    * early_fragment_tests and FS bypass retain precedence below.
    * This workaround is a hardware-validation candidate, not yet qualified.
    */
   if (CHIP == A6XX && cmd->device->physical_device->dev_id.gpu_id == 640 &&
       zmode == A6XX_EARLY_Z_LATE_Z && fs_kill_fragments &&
       stencil_test_enable && stencil_write && !depth_write) {
      zmode = A6XX_LATE_Z;
   }

'''

def function(source):
    start=source.index('template <chip CHIP>\nstatic void\ntu6_build_depth_plane_z_mode')
    opening=source.index('{',start);depth=1;i=opening+1
    while depth:
        depth+=(source[i]=='{')-(source[i]=='}');i+=1
    return source[start:i]

def apply(path):
    old=path.read_text();assert old.count(ANCHOR)==1 and 'GPU359:' not in old
    new=old.replace(ANCHOR,CHANGE+ANCHOR)
    path.write_text(new,newline='\n');return old,new

HARNESS=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
enum chip {A6XX,A7XX};
enum a6xx_ztest_mode {A6XX_EARLY_Z,A6XX_LATE_Z,A6XX_EARLY_Z_LATE_Z};
enum VkCompareOp {VK_COMPARE_OP_NEVER,VK_COMPARE_OP_LESS,VK_COMPARE_OP_EQUAL,VK_COMPARE_OP_LESS_OR_EQUAL,VK_COMPARE_OP_GREATER,VK_COMPARE_OP_NOT_EQUAL,VK_COMPARE_OP_GREATER_OR_EQUAL,VK_COMPARE_OP_ALWAYS};
enum VkFormat {VK_FORMAT_UNDEFINED,VK_FORMAT_D32_SFLOAT_S8_UINT,VK_FORMAT_S8_UINT};
constexpr unsigned VK_ATTACHMENT_UNUSED=~0u,VK_IMAGE_ASPECT_DEPTH_BIT=2,MESA_SHADER_FRAGMENT=0;
struct Variant {bool has_kill,writes_smask,writes_pos;struct {bool early_fragment_tests;} fs;};
struct tu_shader {Variant *variant;struct {bool sample_shading;struct {bool force_late_z;} lrz;} fs;};
struct tu_render_pass {struct {VkFormat format;} attachments[1];};
struct tu_subpass {struct {unsigned attachment;} depth_stencil_attachment;};
struct Physical {struct {unsigned gpu_id;} dev_id;};
struct Device {Physical *physical_device;};
struct tu_cmd_buffer {
 Device *device;
 struct {struct {struct {struct {bool test_enable,write_enable;VkCompareOp compare_op;} depth;struct {bool test_enable;} stencil;} ds;struct {bool alpha_to_coverage_enable;} ms;unsigned feedback_loops;} dynamic_graphics_state;} vk;
 struct {tu_shader *shaders[1];tu_render_pass *pass;tu_subpass *subpass;struct {bool enabled,force_late_z;} lrz;unsigned pipeline_feedback_loops;bool occlusion_query_may_be_running,stencil_written_on_depth_fail,disable_fs;} state;
 struct {a6xx_ztest_mode zmode;} darwin_gmem;
 bool stencil_write,reads_dynamic;
};
struct tu_cs {};
static bool tu6_writes_depth(tu_cmd_buffer *c,bool enabled){return enabled&&c->vk.dynamic_graphics_state.ds.depth.write_enable&&c->vk.dynamic_graphics_state.ds.depth.compare_op!=VK_COMPARE_OP_NEVER;}
static bool tu6_writes_stencil(tu_cmd_buffer *c){return c->stencil_write;}
static bool tu_fs_reads_dynamic_ds_input_attachment(tu_cmd_buffer *c,const tu_shader*){return c->reads_dynamic;}
static bool vk_format_has_depth(VkFormat f){return f==VK_FORMAT_D32_SFLOAT_S8_UINT;}
#define GRAS_SU_DEPTH_PLANE_CNTL(...) 0
#define A6XX_RB_DEPTH_PLANE_CNTL(...) 0
static void tu_cs_emit_regs(tu_cs *,int){}
__FUNCTIONS__
int main(){
 Physical phys{};Device device{&phys};Variant v{};tu_shader shader{};shader.variant=&v;
 tu_render_pass pass{};tu_subpass sub{};tu_cmd_buffer c{};c.device=&device;c.state.shaders[0]=&shader;c.state.pass=&pass;c.state.subpass=&sub;tu_cs cs;
 unsigned changed=0,checked=0;uint32_t random=0x359;
 for(unsigned iteration=0;iteration<100000;iteration++){
  random=random*1664525u+1013904223u;uint32_t bits=random;
  auto bit=[&](){bool result=bits&1;bits>>=1;return result;};
  auto &ds=c.vk.dynamic_graphics_state.ds;ds.depth.test_enable=bit();ds.depth.write_enable=bit();ds.stencil.test_enable=bit();
  c.stencil_write=ds.stencil.test_enable&&bit();v.has_kill=bit();v.writes_smask=bit();c.vk.dynamic_graphics_state.ms.alpha_to_coverage_enable=bit();
  c.state.pipeline_feedback_loops=bit()?2:0;c.vk.dynamic_graphics_state.feedback_loops=bit()?2:0;c.reads_dynamic=bit();
  c.state.lrz.enabled=bit();v.writes_pos=bit();c.state.occlusion_query_may_be_running=bit();c.state.stencil_written_on_depth_fail=bit();
  shader.fs.sample_shading=bit();shader.fs.lrz.force_late_z=bit();c.state.lrz.force_late_z=bit();v.fs.early_fragment_tests=bit();c.state.disable_fs=bit();
  phys.dev_id.gpu_id=bit()?640:650;pass.attachments[0].format=bit()?VK_FORMAT_D32_SFLOAT_S8_UINT:VK_FORMAT_S8_UINT;sub.depth_stencil_attachment.attachment=0;
  ds.depth.compare_op=VkCompareOp(bits&7);
  tu6_build_depth_plane_z_mode_old<A6XX>(&c,&cs);auto before=c.darwin_gmem.zmode;
  tu6_build_depth_plane_z_mode_new<A6XX>(&c,&cs);auto after=c.darwin_gmem.zmode;
  bool expected=phys.dev_id.gpu_id==640&&before==A6XX_EARLY_Z_LATE_Z&&(v.has_kill||v.writes_smask||c.vk.dynamic_graphics_state.ms.alpha_to_coverage_enable)&&ds.stencil.test_enable&&c.stencil_write&&!tu6_writes_depth(&c,ds.depth.test_enable);
  assert(after==(expected?A6XX_LATE_Z:before));changed+=expected;checked++;
  tu6_build_depth_plane_z_mode_old<A7XX>(&c,&cs);before=c.darwin_gmem.zmode;tu6_build_depth_plane_z_mode_new<A7XX>(&c,&cs);assert(c.darwin_gmem.zmode==before);
 }
 // Actual GPU357/GPU358 state: alpha discard, stencil replace on pass,
 // LEQUAL depth test, no depth write, no explicit early tests, LRZ off.
 c={};c.device=&device;c.state.shaders[0]=&shader;c.state.pass=&pass;c.state.subpass=&sub;v={};shader.fs={};phys.dev_id.gpu_id=640;
 pass.attachments[0].format=VK_FORMAT_D32_SFLOAT_S8_UINT;sub.depth_stencil_attachment.attachment=0;
 c.vk.dynamic_graphics_state.ds.depth.test_enable=true;c.vk.dynamic_graphics_state.ds.depth.compare_op=VK_COMPARE_OP_LESS_OR_EQUAL;c.vk.dynamic_graphics_state.ds.stencil.test_enable=true;c.stencil_write=true;v.has_kill=true;
 tu6_build_depth_plane_z_mode_old<A6XX>(&c,&cs);assert(c.darwin_gmem.zmode==A6XX_EARLY_Z_LATE_Z);
 tu6_build_depth_plane_z_mode_new<A6XX>(&c,&cs);assert(c.darwin_gmem.zmode==A6XX_LATE_Z);
 v.fs.early_fragment_tests=true;tu6_build_depth_plane_z_mode_new<A6XX>(&c,&cs);assert(c.darwin_gmem.zmode==A6XX_EARLY_Z);
 assert(changed>0);printf("actual depth policy: %u combinations, %u targeted changes; A7xx, explicit early tests and FS bypass preserved\n",checked,changed);
}
'''

def check(old,new,out):
    out.mkdir(parents=True,exist_ok=True)
    functions=function(old).replace('tu6_build_depth_plane_z_mode','tu6_build_depth_plane_z_mode_old')+'\n'+function(new).replace('tu6_build_depth_plane_z_mode','tu6_build_depth_plane_z_mode_new')
    source=out/'policy.cpp';source.write_text(HARNESS.replace('__FUNCTIONS__',functions))
    compiler=shutil.which('clang++-18') or 'clang++'
    for name,flags in [('release',['-O2']),('asan-ubsan',['-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer'])]:
        exe=out/name;subprocess.run([compiler,'-std=c++20','-Wall','-Wextra','-Werror',*flags,source,'-o',exe],check=True)
        result=subprocess.run([exe],capture_output=True,check=True);(out/(name+'.log')).write_bytes(result.stdout+result.stderr);print(result.stdout.decode().strip())
    (out/'report.json').write_text(json.dumps(dict(passed=True,actual_depth_mode_functions=True,release=True,asan_ubsan=True,combinations=100000,explicit_early_tests_preserved=True,other_hardware_preserved=True,device_tested=False,game_hang_fixed=False),indent=2)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    old,new=apply(a.source);check(old,new,a.output)
